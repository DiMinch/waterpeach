from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.schemas.banking import (
    AccountLookupResponse,
    TransactionDetail,
    TransferRequest,
    UserProfile,
)
from app.services import transaction_service

router = APIRouter(tags=["Mobile Banking"])


@router.get("/users/{user_id}/profile", response_model=UserProfile)
async def get_profile(user_id: str, db: DbSession) -> UserProfile:
    """Mobile Banking home screen of the account owner (victim only, includes balance)."""
    return await transaction_service.get_profile(db, user_id)


@router.get("/transactions/lookup-account", response_model=AccountLookupResponse)
async def lookup_account(
    db: DbSession,
    bank: Annotated[str, Query(max_length=100)],
    account: Annotated[str, Query(min_length=4, max_length=32)],
    sender_id: Annotated[str, Query(max_length=32)],
) -> AccountLookupResponse:
    """Resolve the recipient name and check familiarity / Threat Blacklist status."""
    return await transaction_service.lookup_account(
        db, sender_id=sender_id, bank=bank, account=account
    )


@router.post(
    "/transactions/transfer",
    response_model=TransactionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def transfer(payload: TransferRequest, db: DbSession) -> TransactionDetail:
    """Create a transfer through Risk Engine + Social Circuit Breaker."""
    outcome = await transaction_service.create_transfer(db, payload)
    return transaction_service.to_detail(
        outcome.transaction, guardian_notified=outcome.guardian_notified
    )


@router.get("/transactions/{tx_id}", response_model=TransactionDetail)
async def get_transaction(tx_id: str, db: DbSession) -> TransactionDetail:
    """Latest transaction state (cooling-off countdown, guardian and Fraud Ops decisions)."""
    return transaction_service.to_detail(await transaction_service.get_transaction(db, tx_id))
