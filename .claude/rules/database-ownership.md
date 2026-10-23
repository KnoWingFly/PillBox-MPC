---
paths:
  - "Backend/migrations/**"
  - "Backend/app/models/**"
  - "Backend/app/db/**"
  - "Mobile/prisma/**"
  - "Mobile/src/server/**"
---

# Database ownership

Full context: docs/ai/architecture.md (ownership table and conflicts 1, 5, 6, 8).

- Account tables (`users`, `auth_identities`, `refresh_tokens`, `password_reset_otps`, `push_tokens`) belong to Prisma. Change them only in `Mobile/prisma/schema.prisma`. Backend reads them and never runs DDL or writes rows there.
- The other 12 tables belong to `Backend/migrations/NNNN_*.sql` (0001-0006 exist; the next is 0007). The Prisma schema must not model them.
- New Backend tables: uuid PK `gen_random_uuid()`, `timestamptz`, `ENABLE ROW LEVEL SECURITY` with no policies, enums as VARCHAR + CHECK matching the constants module.
- Never run `prisma migrate dev`, `prisma migrate reset` or `prisma db push` on the shared database (Prisma treats the Backend tables as drift and offers a reset). Author Prisma migrations on a local or throwaway Postgres; apply to shared with `prisma migrate deploy`.
- Order on a fresh database: Prisma migrations first, then `uv run python -m scripts.migrate` in `Backend/`.
- Destructive changes (drop, rename, type change) need explicit approval first.
- Update the ERD and the API list in the same PR as the schema change.
- Mobile app code never touches the database or Supabase tables directly (RLS has no policies).
