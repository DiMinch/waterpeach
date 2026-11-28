"""Load demo seed data: ``uv run python -m app.seed`` (add ``--reset`` to wipe first)."""

import asyncio
import sys

from app.db.session import dispose_engine, get_sessionmaker
from app.services import demo_service


async def main(force_reset: bool) -> None:
    async with get_sessionmaker()() as db:
        if force_reset:
            result = await demo_service.reset(db)
            print(f"Reset demo data: {result.users} users, {result.transactions} transactions")
        elif await demo_service.seed_if_empty(db):
            print("Seeded demo data")
        else:
            print("Demo data already present (use --reset to wipe)")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main("--reset" in sys.argv))
