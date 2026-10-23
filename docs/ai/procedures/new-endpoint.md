# Procedure: implement an API endpoint

Input: the endpoint (method + path) or its functionality name from the API list.

1. Find the row in the API list. If you cannot see it, ask for the row text; do not guess fields.
2. Decide the owner: section A (`/auth/*`, `/setting*`) = Mobile auth server (`Mobile/src/app/api/**/*+api.ts` + `Mobile/src/server/`, Prisma). Everything else = Backend (FastAPI: `app/api/routes/` + `app/schemas/` + `app/services/`).
3. Write the request/response schemas exactly as in the API list (snake_case, enums, nullable fields). Error codes become constants.
4. Authorization: pick the dependency from the row's "Akses" column (Public, Caregiver, related caregiver, OWNER/ADMIN, OWNER, Device, Factory). Related-caregiver checks go through `user_elderly_roles`.
5. Implement the service (Backend queries live in `app/services/`; there is no repository layer). Rules: one transaction per request; config-affecting writes bump `config_version`; WebSocket pushes and notifications happen after commit; lists are paginated; no N+1.
6. If a table or column is missing, run the new-migration procedure first. Never change a table owned by the other service.
7. If the Mobile app calls it: add a typed client function (Backend calls in `Mobile/lib/`, auth server calls in `Mobile/src/lib/api/`), wire it into the existing hook or context, and add an Indonesian message for each new error code in `Mobile/src/lib/api/error-message.ts`.
8. Tests: Backend endpoints get pytest tests in `Backend/tests/` (success path, each documented error code, role matrix); run `uv run pytest` only against a disposable `TEST_DATABASE_URL`. The Mobile auth server has no test runner; say so.
9. Self-check: no hard-coded values, no invented fields, contract matches the API list. List anything you could not verify.
