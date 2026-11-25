from io import BytesIO

import numpy as np
from PIL import Image

from app.schemas.ai import ForensicAnalysis

EDITING_SOFTWARE_SIGNATURES: tuple[str, ...] = (
    "photoshop",
    "canva",
    "gimp",
    "picsart",
    "corel",
    "illustrator",
    "figma",
    "photopea",
    "snapseed",
    "lightroom",
)


def _extract_software_signature(img: Image.Image) -> str | None:
    """Inspect image info and EXIF tags for known editing software markers."""
    candidates: list[str] = []
    for key, val in img.info.items():
        if isinstance(val, (str, bytes)):
            decoded = val.decode("utf-8", errors="ignore") if isinstance(val, bytes) else val
            candidates.append(f"{key}:{decoded}")

    try:
        exif = img.getexif()
        for tag_id in (0x0131, 0x013B, 0x010E):  # Software, Artist, ImageDescription
            value = exif.get(tag_id)
            if value:
                candidates.append(str(value))
    except Exception:
        pass

    joined = " ".join(candidates).lower()
    for sig in EDITING_SOFTWARE_SIGNATURES:
        if sig in joined:
            return sig.title()
    return None


def _compute_ela_anomaly_score(img: Image.Image) -> float:
    """Compute Error Level Analysis (ELA) localized block anomaly score (0..100)."""
    rgb_img = img.convert("RGB")
    # Downscale oversized screenshots for deterministic fast CPU latency
    rgb_img.thumbnail((1024, 1024))

    buffer = BytesIO()
    rgb_img.save(buffer, format="JPEG", quality=90)
    buffer.seek(0)
    recompressed = Image.open(buffer).convert("RGB")

    orig_arr = np.asarray(rgb_img, dtype=np.float32)
    recomp_arr = np.asarray(recompressed, dtype=np.float32)
    diff = np.abs(orig_arr - recomp_arr)
    gray_diff = diff.mean(axis=2)

    h, w = gray_diff.shape
    block_size = 16
    h_trim = (h // block_size) * block_size
    w_trim = (w // block_size) * block_size
    if h_trim < block_size or w_trim < block_size:
        return round(float(min(100.0, gray_diff.mean() * 4.0)), 2)

    cropped = gray_diff[:h_trim, :w_trim]
    blocks = cropped.reshape(h_trim // block_size, block_size, w_trim // block_size, block_size)
    block_means = blocks.mean(axis=(1, 3))

    global_mean = float(block_means.mean())
    global_std = float(block_means.std())
    p95 = float(np.percentile(block_means, 95))
    p50 = float(np.percentile(block_means, 50))

    # Localized splicing creates sharp spikes between quiet background blocks (p50) and edited blocks (p95)
    contrast_ratio = (p95 - p50) / (global_mean + 1.0)
    raw_score = (contrast_ratio * 18.0) + (global_std * 2.5)
    return round(float(max(0.0, min(100.0, raw_score))), 2)


def analyze_image_forensics(image_bytes: bytes, mime_type: str | None = None) -> ForensicAnalysis:
    """Run metadata signature scan and pixel-level ELA tampering check on uploaded image."""
    if mime_type and not mime_type.startswith("image/"):
        return ForensicAnalysis(
            software_signature=None,
            ela_anomaly_score=0.0,
            tampering_suspected=False,
            forensic_note="Tệp âm thanh/phi hình ảnh, bỏ qua kiểm tra ELA điểm ảnh.",
        )

    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception:
        return ForensicAnalysis(
            software_signature=None,
            ela_anomaly_score=0.0,
            tampering_suspected=False,
            forensic_note="Không thể giải mã cấu trúc ảnh để chạy giám định ELA.",
        )

    software = _extract_software_signature(img)
    ela_score = _compute_ela_anomaly_score(img)
    tampered = bool(software is not None or ela_score >= 45.0)

    notes: list[str] = []
    if software:
        notes.append(f"Phát hiện chữ ký phần mềm chỉnh sửa ({software}) trong metadata")
    if ela_score >= 45.0:
        notes.append(
            f"Bất thường mức nén điểm ảnh cục bộ (ELA={ela_score:.1f}/100), nghi ngờ cắt ghép chữ/con dấu"
        )

    note_text = "; ".join(notes) + "." if notes else "Không phát hiện dấu hiệu chỉnh sửa ảnh bất thường."
    return ForensicAnalysis(
        software_signature=software,
        ela_anomaly_score=ela_score,
        tampering_suspected=tampered,
        forensic_note=note_text,
    )
