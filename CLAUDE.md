# PillCare — Smart Pillbox for Elderly (CE739L, UMN)

Caregiver mobile app + cloud backend + emulated smart pillbox. The elderly person never touches a screen; every alert goes to caregivers.

## Monorepo
| Folder | Role | Stack | Guide |
|---|---|---|---|
| `Mobile/` | PillCare caregiver app + auth server (Expo API routes) | Expo SDK 57, TypeScript, Expo Router, NativeWind, Prisma, Supabase Auth (Google only), pnpm | `Mobile/CLAUDE.md` |
| `Backend/` | REST + WebSocket API, rules engine | Python 3.11+, FastAPI, uv, SQLAlchemy async + asyncpg, Supabase Postgres | `Backend/CLAUDE.md` |
| `SmartDevice/` | Smart Pillbox emulator (no real hardware) | Python 3.11+, PySide6, SQLite, pip + venv (`requirements.txt`) | `SmartDevice/CLAUDE.md` |

Each folder has its own guide. Read it before editing that folder.

## Source-of-truth documents (read on demand)
- `docs/ai/domain.md`: roles, 8-slot matrix, dose lifecycle, device protocol, time rules.
- `docs/ai/architecture.md`: which service owns which table, auth flow, known conflicts and fixes.
- `docs/DEVICE_CONTRACT.md`: the device <-> Backend wire contract (heartbeat, config, telemetry event types, WebSocket commands).
- `Backend/README.md`: route overview, setup, migration and test commands. `Mobile/BACKEND_HANDOFF.md`: backend work the app already expects.
- API list (spreadsheet) is the REST/WebSocket contract; ERD (dbdiagram) is the schema. Links are in `docs/ai/README.md`.
If code and these disagree, stop and ask. Do not silently pick one.

## Non-negotiables
1. **No hard-coded values.** URLs, ports, timeouts, intervals, limits, thresholds, colors, spacing, user-facing strings, error codes, role and status names live in env/config, constants/enums, design tokens or a strings module. A literal that appears twice is a bug. Allowed: 0, 1, array indexes, test fixtures.
2. **Components and reuse.** Build small reusable units (RN components, PySide6 widgets, FastAPI dependencies and services). Search for an existing one before writing a new one. Screens and routers only compose.
3. **Optimized by default.** No N+1 queries, paginate lists, use the indexes that exist, memoized list rows, no heavy work during render or on the GUI thread, async I/O in the backend.
4. **Contract first.** Endpoint paths, fields, enums, error codes and roles come from the API list. Do not invent fields or codes; propose a contract change instead.
5. **Secrets.** Never in code, never in `EXPO_PUBLIC_*`, never read `.env` files.
6. **Verify, don't recall.** For library APIs and versions, check the installed version and current docs. Say plainly what you did not run; never claim tests pass unless you ran them.

## Conventions
- English identifiers and comments. Mobile UI copy is Indonesian in `Mobile/src/constants/strings.ts` (no i18n library or EN locale yet). Backend notification text is localized ID/EN by the recipient's `interface_language`. JSON is snake_case on the wire.
- Conventional Commits with a scope: `type(scope): summary`. Summary is imperative, lowercase, no trailing period, about 72 characters max.
  - Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`.
  - Scope is the area modified, one per commit, and the most specific one wins (`db` beats `backend`):
    `mobile`, `backend`, `pillbox` (`SmartDevice/` emulator), `db` (migrations, Prisma schema, ERD), `api` (contract, API list), `auth`, `agents` (CLAUDE.md, AGENTS.md, `.claude/`, `.agents/`, `docs/ai/`), `deps`.
  - Examples: `docs(agents): add commit scopes`, `fix(db): correct partial index on telemetry_logs`, `feat(mobile): add schedule control screen`, `feat(pillbox): flush outbox after reconnect`.
  - A change that spans several areas is split into one commit per scope. A breaking change adds `!` after the scope, e.g. `feat(api)!: rename config_version field`.
- Tests: pytest in Backend (`uv run pytest`, needs a disposable `TEST_DATABASE_URL`) and SmartDevice (`.venv/bin/pytest`). Mobile has no test runner yet. Read the package scripts before assuming a command exists.
- Do not mass-reformat or move files unless asked. Match the layout that already exists.

## Core domain in short
- Roles per elderly: OWNER (exactly one), ADMIN, PEMANTAU (read-only).
- Device: 8 slots, A1-A4 before meal and B1-B4 after meal, times MORNING / AFTERNOON / EVENING / NIGHT. Only one chamber active at a time.
- Dose status: PENDING -> TAKEN | MISSED. The API shows TAKEN_ON_TIME / TAKEN_LATE derived from `delay_minutes`. The rules engine marks MISSED after `window_end` + tolerance and notifies caregivers.
- The device is offline-first and idempotent: events are keyed by `event_id`, config is pulled by `config_version`.
- Two device secrets, not one: the device key (`X-Device-Key`, generated at provisioning, stored as SHA-256) authenticates the device; the 4-digit PIN (scrypt) lets caregivers pair/join. The ERD column `master_password_hash` is unused.
- Account tables (`users`, `auth_identities`, `refresh_tokens`, `password_reset_otps`, `push_tokens`) belong to Prisma in `Mobile/`. Every other table belongs to Backend SQL migrations.
- Timestamps are `timestamptz`; dose times are shown in the device's timezone.

## Working agreements
- For changes touching more than one file, state a short plan first, then implement.
- Ask only when blocked by a contract ambiguity. Otherwise pick the simplest option that follows the docs and say which you picked.
- Reusable procedures (slash commands / skills): `/new-endpoint`, `/new-screen`, `/new-migration`, `/audit-hardcoded`, `/sim-scenario`. Their steps live in `docs/ai/procedures/`.
- Existing code predates some of these rules (inline Indonesian strings and hex colors in a few Mobile components, constants in SmartDevice `config.py`). Follow the rules in new code and fix debt only in code you touch; do not mass-refactor.
