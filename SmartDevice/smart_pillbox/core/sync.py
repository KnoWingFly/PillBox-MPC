"""Telemetry sync: drains unsynced `events` rows and POSTs them to the
backend. The backend isn't built yet, so this deliberately swallows
connection errors and just leaves rows queued — that IS the offline-first
behaviour the proposal asks for, not a bug to fix later.

Swap BACKEND_TELEMETRY_URL in config.py once the FastAPI endpoint exists;
no other change should be needed here.
"""

from __future__ import annotations

import logging

import requests

from smart_pillbox import config
from smart_pillbox.db.database import Database

logger = logging.getLogger(__name__)


def flush_pending_events(db: Database) -> int:
    """Attempts to send unsynced events to the backend. Returns how many
    were successfully synced (0 if the backend is unreachable)."""
    pending = db.get_unsynced_events()
    if not pending:
        return 0

    payload = {
        "device_id": "sim-01",
        "events": [
            {
                "compartment_id": row["compartment_id"],
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"],
            }
            for row in pending
        ],
    }

    try:
        response = requests.post(
            config.BACKEND_TELEMETRY_URL,
            json=payload,
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.info("Backend unreachable, buffering %d event(s) locally: %s", len(pending), exc)
        return 0

    ids = [row["id"] for row in pending]
    db.mark_synced(ids)
    logger.info("Synced %d event(s) to backend.", len(ids))
    return len(ids)
