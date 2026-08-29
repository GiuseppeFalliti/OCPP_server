"""Esegue le migrazioni PostgreSQL del server OCPP 1.6J."""

import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv


async def run_migrations(database_url: str) -> None:
    """Applica tutti i file SQL ordinati presenti nella cartella db."""
    migrations_dir = Path(__file__).parent
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=1)
    try:
        async with pool.acquire() as connection:
            for migration in sorted(migrations_dir.glob("[0-9]*.sql")):
                await connection.execute(migration.read_text(encoding="utf-8"))
                print(f"Applicata migrazione: {migration.name}")
    finally:
        await pool.close()


def main() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL non e' impostata.")
    asyncio.run(run_migrations(database_url))


if __name__ == "__main__":
    main()
