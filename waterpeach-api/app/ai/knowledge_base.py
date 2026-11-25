"""Vietnamese Scam Knowledge Base grounded in AIS 24 Scenarios, VN SMS Dataset, and PhishVN."""

COERCIVE_AUTHORITY_PATTERNS: tuple[str, ...] = (
    "tam giu",
    "xac minh ho so",
    "chung minh tai chinh",
    "dieu tra",
    "khoi to",
    "lenh bat",
    "toa an",
    "vien kiem sat",
    "bo cong an",
    "cong an",
    "canh sat",
    "phong toa tai khoan",
    "dinh danh muc 2",
    "vneid",
    "chi cuc thue",
    "cuc thue",
    "phi hai quan",
    "hai quan",
    "mo khoa tai khoan",
    "bao lanh",
    "nop phat nguoi",
)

TASK_SCAM_AND_GREED_PATTERNS: tuple[str, ...] = (
    "lam nhiem vu",
    "nhiem vu",
    "hoan tien",
    "hoa hong",
    "ctv",
    "cong tac vien",
    "don hang ao",
    "tang tuong tac",
    "mo khoa rut tien",
    "rut von",
    "san thuong mai",
    "dau tu loi nhuan",
    "trung thuong",
    "nhan qua mien phi",
)

FAKE_DELIVERY_OR_BILL_PATTERNS: tuple[str, ...] = (
    "giao hang that bai",
    "dong phi giao hang",
    "shipper",
    "cat dien",
    "dien luc evn",
    "quyet toan thue",
    "cap nhat sinh trac hoc",
    "xac thuc tai khoan",
)

URGENCY_MARKERS: tuple[str, ...] = (
    "khan cap",
    "trong vong",
    "ngay lap tuc",
    "qua han",
    "sau 2 gio",
    "bi khoa",
    "lap tuc",
    "cuoi cung",
    "gap",
)

FEAR_MARKERS: tuple[str, ...] = (
    "bat giam",
    "truy to",
    "phong toa",
    "xu ly hinh su",
    "mat trang",
    "khoa vinh vien",
    "cuong che",
    "vi pham phap luat",
)

CASUAL_PEER_PATTERNS: tuple[str, ...] = (
    "tien dien",
    "tien nuoc",
    "tien nha",
    "tien phong",
    "an trua",
    "an toi",
    "ca phe",
    "tra sua",
    "nhau",
    "chia bill",
    "share bill",
    "sinh nhat",
    "mung cuoi",
    "di tre",
    "choi game",
)

MERCHANT_PURCHASE_PATTERNS: tuple[str, ...] = (
    "mua xe",
    "thanh toan don",
    "mua hang",
    "dat coc",
    "hoa don",
    "tien hoc",
    "kham benh",
    "vien phi",
    "tien thuoc",
    "xe may",
)

PHISHVN_SUSPICIOUS_TLDS: tuple[str, ...] = (
    ".xyz",
    ".top",
    ".vip",
    ".cc",
    ".click",
    ".icu",
    ".buzz",
    ".loan",
    ".work",
    ".shop",
    ".site",
    ".online",
    ".cfd",
    ".tk",
    ".ml",
)

PHISHVN_IMPERSONATED_BRANDS: tuple[str, ...] = (
    "thue",
    "gdt",
    "dichvucong",
    "vneid",
    "congan",
    "bocongan",
    "evn",
    "vietcombank",
    "vcb",
    "techcombank",
    "mbbank",
    "bidv",
    "agribank",
    "momo",
    "zalopay",
    "shopee",
    "vnpost",
    "viettelpost",
)

OFFICIAL_VN_ALLOWLIST_SUFFIXES: tuple[str, ...] = (
    ".gov.vn",
    "vietcombank.com.vn",
    "techcombank.com",
    "mbbank.com.vn",
    "bidv.com.vn",
    "momo.vn",
    "evn.com.vn",
    "vnpost.vn",
)

CORPORATE_NAME_MARKERS: tuple[str, ...] = (
    "CONG TY",
    "CTCP",
    "TNHH",
    "CHI NHANH",
    "TAP DOAN",
    "BENH VIEN",
    "TRUONG DAI HOC",
    "KHO BAC",
    "TONG CUC",
)

MERCHANT_HKD_MARKERS: tuple[str, ...] = (
    "HKD",
    "HO KINH DOANH",
    "CUA HANG",
    "SHOP",
    "NHA THUOC",
    "SIEU THI",
    "GARAGE",
    "SHOWROOM",
)
