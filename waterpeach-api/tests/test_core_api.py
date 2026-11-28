"""End-to-end tests for the core backend (Mobile Banking, Guardian Hub, Fraud Ops, demo)."""

from collections.abc import Callable
from datetime import datetime

import pytest
from httpx import AsyncClient

from app.core.config import DEV_B2B_API_KEY
from app.schemas.ai import GuardianRelationship
from app.services.family_service import infer_guardian_relationship

API = "/api/v1"
VICTIM = "usr_minh_01"
GUARDIAN = "usr_nam_02"
OPS = "usr_linh_03"

Events = Callable[[], list[str]]


async def balance(api: AsyncClient) -> int:
    return (await api.get(f"{API}/users/{VICTIM}/profile")).json()["balance"]


async def run_scenario(api: AsyncClient, scenario_id: int) -> dict:
    response = await api.post(f"{API}/demo/scenario/{scenario_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def decide(api: AsyncClient, tx_id: str, decision: str, guardian: str = GUARDIAN):
    return await api.post(
        f"{API}/guardian/transactions/{tx_id}/decision",
        json={"guardian_id": guardian, "decision": decision, "note": "test"},
    )


async def ops_action(api: AsyncClient, tx_id: str, action: str, **extra: object):
    return await api.post(
        f"{API}/ops/incidents/{tx_id}/action", json={"ops_id": OPS, "action": action, **extra}
    )


def transfer_body(**overrides: object) -> dict:
    body: dict[str, object] = {
        "sender_id": VICTIM,
        "recipient_name": "NGUYEN THI LAN",
        "recipient_account": "1903456789012",
        "recipient_bank": "Techcombank",
        "amount": 300_000,
        "transfer_note": "Tien an trua",
    }
    body.update(overrides)
    return body


# ----------------------------------------------------------------------------- profile & lookup


async def test_profile_is_victim_only(api: AsyncClient) -> None:
    body = (await api.get(f"{API}/users/{VICTIM}/profile")).json()
    assert body["balance"] == 85_000_000
    assert len(body["recent_transactions"]) == 3
    assert body["recent_transactions"][0]["created_at"].endswith("+07:00")

    guardian = await api.get(f"{API}/users/{GUARDIAN}/profile")
    assert guardian.status_code == 403
    assert guardian.json() == {
        "detail": "Mobile Banking profile is only for the account owner",
        "error_code": "PROFILE_VICTIM_ONLY",
    }
    missing = await api.get(f"{API}/users/usr_nobody/profile")
    assert (missing.status_code, missing.json()["error_code"]) == (404, "USER_NOT_FOUND")


async def test_lookup_account(api: AsyncClient) -> None:
    def lookup(account: str):
        return api.get(
            f"{API}/transactions/lookup-account",
            params={"bank": "Techcombank", "account": account, "sender_id": VICTIM},
        )

    familiar = (await lookup("1903456789012")).json()
    assert familiar["account_holder_name"] == "NGUYEN THI LAN"
    assert familiar["is_familiar_recipient"] is True
    assert familiar["blacklist_status"] == "none"
    assert familiar["warning_banner"] is None

    stranger = (await lookup("5555666677")).json()
    assert stranger["account_holder_name"] == "CHU TAI KHOAN ****6677"
    assert stranger["is_familiar_recipient"] is False

    blacklisted = (await lookup("0123456789999")).json()
    assert blacklisted["blacklist_status"] == "confirmed_blacklisted"
    assert blacklisted["warning_banner"]


# ----------------------------------------------------------------------------- transfers


async def test_low_risk_familiar_transfer_completes(api: AsyncClient, events: Events) -> None:
    response = await api.post(f"{API}/transactions/transfer", json=transfer_body())
    assert response.status_code == 201
    tx = response.json()
    assert tx["status"] == "completed"
    assert tx["cooling_off_expires_at"] is None
    assert await balance(api) == 85_000_000 - 300_000
    assert events() == []

    fetched = await api.get(f"{API}/transactions/{tx['tx_id']}")
    assert fetched.json()["tx_id"] == tx["tx_id"]
    assert (await api.get(f"{API}/transactions/tx_missing")).json()["error_code"] == "TX_NOT_FOUND"


async def test_transfer_validation_errors(api: AsyncClient) -> None:
    too_much = await api.post(f"{API}/transactions/transfer", json=transfer_body(amount=10**9))
    assert (too_much.status_code, too_much.json()["error_code"]) == (400, "INSUFFICIENT_BALANCE")
    not_owner = await api.post(f"{API}/transactions/transfer", json=transfer_body(sender_id=OPS))
    assert (not_owner.status_code, not_owner.json()["error_code"]) == (403, "ROLE_NOT_ALLOWED")


async def test_transfer_to_confirmed_blacklist_is_blocked(api: AsyncClient, events: Events) -> None:
    tx = (
        await api.post(
            f"{API}/transactions/transfer",
            json=transfer_body(
                recipient_name="TRAN VAN B", recipient_account="0123456789999", amount=2_000_000
            ),
        )
    ).json()
    assert tx["status"] == "blocked"
    assert tx["blacklist_hit"] is True
    assert await balance(api) == 85_000_000
    assert events() == ["OPS_INCIDENT_ESCALATED"]


# ----------------------------------------------------------------------------- scenario 1


async def test_scenario_1_police_impersonation_end_to_end(api: AsyncClient, events: Events) -> None:
    result = await run_scenario(api, 1)
    tx = result["transaction"]
    assert tx["status"] == "cooling_off"
    assert tx["guardian_notified"] is True
    assert tx["ai_risk_score"] >= 80
    assert tx["ai_analysis"]["risk_level"] == "CRITICAL"
    assert datetime.fromisoformat(tx["cooling_off_expires_at"]) > datetime.fromisoformat(
        tx["created_at"]
    )
    assert await balance(api) == 60_000_000  # funds held
    assert events() == ["TX_COOLING_OFF_TRIGGERED"]

    alerts = (await api.get(f"{API}/guardian/alerts", params={"guardian_id": GUARDIAN})).json()
    assert [a["tx_id"] for a in alerts["alerts"]] == [tx["tx_id"]]  # seeds are completed: hidden
    alert = alerts["alerts"][0]
    assert "balance" not in alert
    assert alert["relationship"] == "Con trai"
    assert alert["is_new_recipient"] is True
    assert alert["reasoning_for_guardian"]

    queue = (await api.get(f"{API}/ops/incidents")).json()
    assert queue["incidents"][0]["priority_badge"] == "HIGH_RISK_PENDING"

    flagged = await decide(api, tx["tx_id"], "flag_scam")
    assert flagged.status_code == 200
    assert flagged.json()["status"] == "blocked"
    assert await balance(api) == 85_000_000  # refunded
    assert events()[-2:] == ["GUARDIAN_DECISION_MADE", "OPS_INCIDENT_ESCALATED"]

    queue = (await api.get(f"{API}/ops/incidents", params={"filter": "active"})).json()
    assert queue["incidents"][0]["priority_badge"] == "CRITICAL_GUARDIAN_FLAGGED"
    assert queue["stats"]["critical_queue_count"] == 1

    brief = (await api.get(f"{API}/ops/incidents/{tx['tx_id']}/brief")).json()
    assert brief["priority_badge"] == "CRITICAL_GUARDIAN_FLAGGED"
    assert brief["deescalation_copilot"]["call_script"]
    assert brief["network_threat_intel"]["blacklist_status"] == "none"

    action = await ops_action(
        api, tx["tx_id"], "blacklist_recipient", notes="Xác nhận lừa đảo giả danh công an"
    )
    assert action.status_code == 200
    body = action.json()
    assert body["transaction"]["ops_decision"] == "confirmed_fraud"
    assert body["blacklist_entry"]["status"] == "confirmed_blacklisted"
    assert body["incident_report"]["action"] == "blacklist_recipient"
    assert body["incident_report"]["ops_name"] == "Chị Linh"
    assert events()[-1] == "OPS_CONTAINMENT_EXECUTED"

    retry = (await run_scenario(api, 1))["transaction"]
    assert retry["status"] == "blocked"
    assert await balance(api) == 85_000_000

    # Guardian can no longer act on a resolved transaction
    late = await decide(api, tx["tx_id"], "approve_safe")
    assert (late.status_code, late.json()["error_code"]) == (409, "TX_NOT_PENDING")


# ----------------------------------------------------------------------------- scenario 2


async def test_scenario_2_guardian_approves_false_positive(api: AsyncClient) -> None:
    tx = (await run_scenario(api, 2))["transaction"]
    assert tx["status"] == "cooling_off"
    assert await balance(api) == 67_000_000

    approved = (await decide(api, tx["tx_id"], "approve_safe")).json()
    assert approved["status"] == "released"
    assert approved["ops_decision"] == "false_positive"
    assert await balance(api) == 67_000_000  # held funds leave the account

    resolved = (await api.get(f"{API}/ops/incidents", params={"filter": "auto_resolved"})).json()
    assert [i["tx_id"] for i in resolved["incidents"]] == [tx["tx_id"]]
    assert resolved["incidents"][0]["priority_badge"] == "AUTO_RESOLVED_SAFE"
    assert resolved["stats"]["auto_resolved_count"] == 1
    assert resolved["stats"]["false_positive_reduction_pct"] == 100.0
    active = (await api.get(f"{API}/ops/incidents", params={"filter": "active"})).json()
    assert active["incidents"] == []


async def test_hold_verify_extends_cooling_off(api: AsyncClient) -> None:
    tx = (await run_scenario(api, 2))["transaction"]
    held = (await decide(api, tx["tx_id"], "hold_verify")).json()
    assert held["status"] == "cooling_off"
    assert len(held["suggested_verification_questions"]) == 3
    extended = datetime.fromisoformat(held["cooling_off_expires_at"])
    original = datetime.fromisoformat(tx["cooling_off_expires_at"])
    assert (extended - original).total_seconds() >= 30 * 60 - 1

    assert (await decide(api, tx["tx_id"], "pending")).json()["error_code"] == "INVALID_DECISION"
    assert (await decide(api, tx["tx_id"], "approve_safe")).json()["status"] == "released"


async def test_guardian_permissions(api: AsyncClient) -> None:
    tx = (await run_scenario(api, 2))["transaction"]
    not_guardian = await decide(api, tx["tx_id"], "flag_scam", guardian=OPS)
    assert (not_guardian.status_code, not_guardian.json()["error_code"]) == (403, "ROLE_NOT_ALLOWED")

    link = (
        await api.post(
            f"{API}/family/members",
            json={
                "victim_id": VICTIM,
                "guardian_name": "Chị Lan",
                "guardian_phone": "0912345678",
                "relationship": "Con gái",
            },
        )
    ).json()
    await api.delete(f"{API}/family/members/{link['link_id']}")
    outsider = await decide(api, tx["tx_id"], "flag_scam", guardian=link["guardian_id"])
    assert (outsider.status_code, outsider.json()["error_code"]) == (403, "NOT_GUARDIAN_OF_SENDER")
    empty = await api.get(f"{API}/guardian/alerts", params={"guardian_id": link["guardian_id"]})
    assert empty.json() == {"alerts": []}


# ----------------------------------------------------------------------------- scenario 3


async def test_scenario_3_scam_scan_feeds_blacklist_and_family(
    api: AsyncClient, events: Events
) -> None:
    report = (await run_scenario(api, 3))["scam_report"]
    assert report["verdict"] in ("SUSPICIOUS", "HIGH_RISK_SCAM")
    assert report["shared_to_family"] is True
    assert "190388889999" in report["extracted_entities"]["bank_accounts"]
    assert report["blacklisted_entities_count"] >= 3
    assert events() == ["FAMILY_SCAM_ALERT_SHARED"]

    entries = (await api.get(f"{API}/ops/blacklist", params={"status": "suspected"})).json()
    values = {e["entity_value"] for e in entries["entries"]}
    assert {"190388889999", "0987654321", "http://thue-xacminh-vn.xyz"} <= values

    feed = (await api.get(f"{API}/family/safety-feed", params={"family_member_id": GUARDIAN})).json()
    assert [i["report_id"] for i in feed["items"]] == [report["report_id"]]
    ops_feed = await api.get(f"{API}/family/safety-feed", params={"family_member_id": OPS})
    assert ops_feed.status_code == 403

    lookup = (
        await api.get(
            f"{API}/transactions/lookup-account",
            params={"bank": "Techcombank", "account": "190388889999", "sender_id": VICTIM},
        )
    ).json()
    assert lookup["blacklist_status"] == "suspected"

    tx = (await run_scenario(api, 1))["transaction"]
    assert "SUSPECTED_BLACKLIST_HIT" in tx["ai_analysis"]["detected_signals"]
    intel = (await api.get(f"{API}/ops/incidents/{tx['tx_id']}/brief")).json()[
        "network_threat_intel"
    ]
    assert intel["matched_reports_count"] == 1
    assert intel["matched_entities"] == ["190388889999"]
    assert intel["cross_family_alert"] is False


async def test_scam_check_endpoint_validation(api: AsyncClient) -> None:
    ok = await api.post(
        f"{API}/scam-check/analyze",
        data={"submitted_by": GUARDIAN, "raw_text": "Chao ban, hen gap o quan cafe nhe"},
    )
    assert ok.status_code == 200
    assert ok.json()["shared_to_family"] is False

    empty = await api.post(f"{API}/scam-check/analyze", data={"submitted_by": VICTIM})
    assert (empty.status_code, empty.json()["error_code"]) == (400, "INVALID_SCAM_INPUT")

    huge = await api.post(
        f"{API}/scam-check/analyze",
        data={"submitted_by": VICTIM},
        files={"file": ("big.png", b"0" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert (huge.status_code, huge.json()["error_code"]) == (400, "FILE_TOO_LARGE")


# ----------------------------------------------------------------------------- trusted circle


async def test_trusted_circle_management(api: AsyncClient) -> None:
    circle = (await api.get(f"{API}/family/trusted-circle", params={"victim_id": VICTIM})).json()
    assert [m["guardian_name"] for m in circle["members"]] == ["Anh Nam"]
    assert circle["settings"]["protection_threshold"] == 5_000_000
    assert circle["privacy_commitment"]

    body = {
        "victim_id": VICTIM,
        "guardian_name": "Chị Lan",
        "guardian_phone": "0912345678",
        "relationship": "Con gái",
    }
    created = await api.post(f"{API}/family/members", json=body)
    assert created.status_code == 201
    link = created.json()
    assert link["privacy_mode"] == "alert_only"
    assert link["status"] == "active"

    duplicate = await api.post(f"{API}/family/members", json=body)
    assert (duplicate.status_code, duplicate.json()["error_code"]) == (409, "MEMBER_EXISTS")
    own_phone = await api.post(
        f"{API}/family/members", json={**body, "guardian_phone": "0901234567"}
    )
    assert own_phone.json()["error_code"] == "PHONE_IN_USE"
    guardian_circle = await api.get(f"{API}/family/trusted-circle", params={"victim_id": GUARDIAN})
    assert guardian_circle.status_code == 403

    removed = await api.delete(f"{API}/family/members/{link['link_id']}")
    assert removed.json() == {"deleted": True, "link_id": link["link_id"]}
    assert (await api.delete(f"{API}/family/members/{link['link_id']}")).status_code == 404

    settings = await api.put(
        f"{API}/family/settings",
        json={"victim_id": VICTIM, "protection_threshold": 3_000_000, "sensitive_hours_enabled": False},
    )
    assert settings.json() == {
        "protection_threshold": 3_000_000,
        "sensitive_hours_enabled": False,
        "auto_trigger_high_risk": True,
    }


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Con gái", GuardianRelationship.CHILD_OF_VICTIM),
        ("Bố", GuardianRelationship.PARENT_OF_VICTIM),
        ("Vợ", GuardianRelationship.SPOUSE),
        ("Hàng xóm", GuardianRelationship.OTHER),
        ("", GuardianRelationship.OTHER),
    ],
)
def test_infer_guardian_relationship(label: str, expected: GuardianRelationship) -> None:
    assert infer_guardian_relationship(label) == expected


# ----------------------------------------------------------------------------- ops actions


async def test_ops_cancel_release_and_export(api: AsyncClient) -> None:
    tx = (await run_scenario(api, 2))["transaction"]
    cancelled = (await ops_action(api, tx["tx_id"], "cancel_and_refund")).json()
    assert cancelled["transaction"]["status"] == "blocked"
    assert cancelled["blacklist_entry"] is None
    assert await balance(api) == 85_000_000

    released = (await ops_action(api, tx["tx_id"], "release_transaction")).json()
    assert released["transaction"]["status"] == "released"
    assert released["transaction"]["ops_decision"] == "false_positive"
    assert await balance(api) == 67_000_000

    again = await ops_action(api, tx["tx_id"], "release_transaction")
    assert (again.status_code, again.json()["error_code"]) == (409, "TX_ALREADY_RESOLVED")
    refund = await ops_action(api, tx["tx_id"], "cancel_and_refund")
    assert refund.json()["error_code"] == "TX_ALREADY_RESOLVED"

    exported = (await ops_action(api, tx["tx_id"], "export_report", add_to_blacklist=True)).json()
    assert exported["incident_report"]["transaction"]["tx_id"] == tx["tx_id"]
    assert exported["blacklist_entry"]["entity_value"] == "0071000123456"


async def test_release_of_blocked_tx_requires_balance(
    api: AsyncClient, session_factory: object
) -> None:
    from app.models import User
    from app.services import transaction_service

    tx = (await run_scenario(api, 2))["transaction"]
    await ops_action(api, tx["tx_id"], "cancel_and_refund")
    async with session_factory() as db:  # type: ignore[operator]
        user = await db.get(User, VICTIM)
        user.balance = 1_000
        await db.commit()
        # atomic debit refuses to overdraw
        assert await transaction_service.adjust_balance(db, VICTIM, -2_000) is False
        assert await transaction_service.adjust_balance(db, VICTIM, 500) is True
        await db.commit()

    refused = await ops_action(api, tx["tx_id"], "release_transaction")
    assert (refused.status_code, refused.json()["error_code"]) == (400, "INSUFFICIENT_BALANCE")
    assert await balance(api) == 1_500
    status = (await api.get(f"{API}/transactions/{tx['tx_id']}")).json()["status"]
    assert status == "blocked"


async def test_ops_action_guards(api: AsyncClient) -> None:
    tx = (await run_scenario(api, 2))["transaction"]
    wrong_role = await api.post(
        f"{API}/ops/incidents/{tx['tx_id']}/action",
        json={"ops_id": GUARDIAN, "action": "cancel_and_refund"},
    )
    assert (wrong_role.status_code, wrong_role.json()["error_code"]) == (403, "ROLE_NOT_ALLOWED")
    seed = await ops_action(api, "tx_seed_01", "cancel_and_refund")
    assert (seed.status_code, seed.json()["error_code"]) == (409, "TX_NOT_AN_INCIDENT")


async def test_manual_blacklist(api: AsyncClient) -> None:
    created = await api.post(
        f"{API}/ops/blacklist",
        json={"entity_type": "phone", "entity_value": "+84 912 000 111"},
    )
    assert created.status_code == 201
    assert created.json()["entity_value"] == "0912000111"
    assert created.json()["status"] == "confirmed_blacklisted"

    downgrade = await api.post(
        f"{API}/ops/blacklist",
        json={"entity_type": "phone", "entity_value": "0912000111", "status": "suspected"},
    )
    assert downgrade.json()["status"] == "confirmed_blacklisted"
    assert downgrade.json()["report_count"] == 2

    invalid = await api.post(
        f"{API}/ops/blacklist",
        json={"entity_type": "url", "entity_value": "http://x.vn", "status": "none"},
    )
    assert invalid.json()["error_code"] == "INVALID_STATUS"

    phones = (await api.get(f"{API}/ops/blacklist", params={"entity_type": "phone"})).json()
    assert [e["entity_value"] for e in phones["entries"]] == ["0912000111"]
    search = (await api.get(f"{API}/ops/blacklist", params={"q": "0123"})).json()
    assert [e["entity_value"] for e in search["entries"]] == ["0123456789999"]


# ----------------------------------------------------------------------------- b2b & demo


async def test_b2b_risk_evaluate(api: AsyncClient) -> None:
    body = transfer_body(
        partner_tx_ref="MOMO-20261125-001",
        recipient_name="NGUYEN VAN A",
        recipient_account="190388889999",
        amount=25_000_000,
        transfer_note="Nop tien tam giu xac minh ho so",
    )
    assert (await api.post(f"{API}/risk/evaluate", json=body)).status_code == 401
    response = await api.post(
        f"{API}/risk/evaluate", json=body, headers={"X-API-Key": DEV_B2B_API_KEY}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["partner_tx_ref"] == "MOMO-20261125-001"
    assert data["status"] == "cooling_off"
    assert data["cooling_off_seconds"] == 900
    assert data["guardian_notified"] is True


async def test_demo_reset_and_invalid_scenario(api: AsyncClient, events: Events) -> None:
    await run_scenario(api, 1)
    reset = (await api.post(f"{API}/demo/reset")).json()
    assert reset == {"reset": True, "users": 3, "transactions": 3}
    assert events()[-1] == "DEMO_DATA_RESET"
    assert await balance(api) == 85_000_000
    assert (await api.post(f"{API}/demo/scenario/4")).status_code == 422
