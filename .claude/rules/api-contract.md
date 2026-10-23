---
paths:
  - "Backend/app/api/**/*.py"
  - "Backend/app/schemas/**/*.py"
  - "Mobile/src/app/api/**/*.ts"
  - "Mobile/src/server/**/*.ts"
  - "Mobile/src/lib/api/**/*.ts"
  - "Mobile/lib/**/*.ts"
---

# API contract

The API list (spreadsheet) is the contract. Notation: `existing_object_id` is sent by the client, `unique_id_from_db` is server-generated and appears only in responses.

- Base URLs: Mobile auth server = Expo dev server + `/api` (section A: `/auth/*`, `/setting*`); FastAPI `http://localhost:8000/api/v1` (sections B-G); WebSocket `ws://localhost:8000/ws/app` and `/ws/device/{device_code}`. Read them from config (`Mobile/src/config.ts`, `Backend/app/core/config.py`, `SmartDevice/smart_pillbox/config.py`), never inline.
- JSON is snake_case. Datetimes are ISO 8601, dates `YYYY-MM-DD`, times `HH:mm`.
- Do not add, rename or drop fields, enum values or error codes without updating the API list first and telling the team.
- Access levels per endpoint (Public, Caregiver, related caregiver, OWNER/ADMIN, OWNER, Device, Factory) are part of the contract. Unrelated caller: 404. Under-privileged: 403.
- Lists use `page`, `limit`, `total`. Max `limit` comes from settings.
- Error body (both servers): `{"error": {"code", "message", "details"?}}` with the HTTP status from the API list (for example `409 DEVICE_ALREADY_PAIRED`). Keep `UNAUTHORIZED` for invalid or expired caregiver tokens: the app refreshes only on that code.
- Config-changing endpoints bump `config_version` and notify the device after commit.
- Device protocol details: `docs/DEVICE_CONTRACT.md`.
