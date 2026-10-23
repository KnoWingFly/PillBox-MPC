# Procedure: change the database schema

1. Decide the owner with `docs/ai/architecture.md`. Account tables (`users`, `auth_identities`, `refresh_tokens`, `password_reset_otps`, `push_tokens`) = Prisma. Everything else = Backend SQL.
2. Backend SQL: create `Backend/migrations/NNNN_short_name.sql` with the next number (check `ls Backend/migrations`; 0001-0006 exist as of 23 Oct 2026). Rules: additive and idempotent where possible; uuid PK `gen_random_uuid()`; `timestamptz`; enums as VARCHAR + CHECK whose values match the constants module; `ENABLE ROW LEVEL SECURITY` on new tables with no policies; add only indexes a real query needs.
3. Prisma: edit `Mobile/prisma/schema.prisma`, create the migration against a local or throwaway Postgres, never against the shared database. Apply to shared with `prisma migrate deploy` only after review. Never run `migrate reset` or `db push`.
4. Destructive changes (drop, rename, type change, NOT NULL on existing data): stop and ask first. Prefer expand-then-contract.
5. Update in the same PR: ORM models (`Backend/app/models/`) or Prisma schema, enums that mirror CHECK values (`Backend/app/models/enums.py`), the ERD (dbdiagram) and the API list if a field changed, and `docs/ai/` if a rule changed.
6. Verify on a local or disposable database: Prisma migrations first, then `uv run python -m scripts.migrate` in `Backend/`, then `uv run pytest` (its `TEST_DATABASE_URL` applies both migration sets). State clearly what you did and did not run.
