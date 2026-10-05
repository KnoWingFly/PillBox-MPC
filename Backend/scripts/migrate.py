"""Apply Backend/migrations/*.sql to DATABASE_URL (from Backend/.env).

Run from Backend/:  uv run python -m scripts.migrate
Prisma migrations (Mobile/prisma) must be applied first: they create `users`
and `push_tokens`, which these tables reference.
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.migrate import apply_migrations


async def _main() -> None:
    settings = get_settings()
    configure_logging("INFO", as_json=False)
    applied = await apply_migrations(settings.database_url)
    logging.getLogger("migrate").info(
        "done: %s", ", ".join(applied) if applied else "nothing to apply"
    )


if __name__ == "__main__":
    asyncio.run(_main())
