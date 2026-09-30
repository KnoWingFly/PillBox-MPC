"""Telemetry sync: drains unsynced `events` rows and POSTs them to the
backend. The backend isn't built yet, so this deliberately swallows
connection errors and just leaves rows queued — that IS the offline-first
behaviour the proposal asks for, not a bug to fix later.

Swap BACKEND_TELEMETRY_URL in config.py once the FastAPI endpoint exists;
no other change should be needed here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
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

    batch_id = str(uuid.uuid4())
    payload = {
        "batch_id": batch_id,
        "events": [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "slot_number": row["slot_number"],
                "schedule_id": None, # Stubbed until schedule downloading is implemented
                "occurred_at": row["occurred_at"],
                "chime_count": row["chime_count"]
            }
            for row in pending
        ],
    }

    try:
        response = requests.post(
            f"{config.BACKEND_BASE_URL}/devices/sim-01/telemetry",
            json=payload,
            headers={"X-Device-Key": "dummy-key"},
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        res_json = response.json()
        
        # Check latest_config_version from telemetry response
        latest_version = res_json.get("latest_config_version")
        current_version = int(db.get_device_state("config_version") or "1")
        if latest_version and latest_version > current_version:
            pull_latest_config(db)
    except requests.RequestException as exc:
        logger.info("Backend unreachable, buffering %d event(s) locally: %s", len(pending), exc)
        return 0

    ids = [row["id"] for row in pending]
    db.mark_synced(ids)
    logger.info("Synced %d event(s) to backend.", len(ids))
    return len(ids)

def send_heartbeat(db: Database, current_time_str: str, battery_percent: int, is_online: bool) -> None:
    if not is_online:
        return
        
    config_version = db.get_device_state("config_version") or "1"
    payload = {
        "sent_at": current_time_str,
        "battery_percent": battery_percent,
        "wifi_rssi_dbm": -50,
        "rtc_time": current_time_str,
        "config_version_applied": int(config_version),
        "chambers": [
            {
                "slot_number": c.slot_number,
                "door": "OPEN" if c.door_open else "CLOSED",
                "stock_count": c.stock_count,
            }
            for c in db.get_compartments()
        ]
    }
    
    try:
        response = requests.post(
            f"{config.BACKEND_BASE_URL}/devices/sim-01/heartbeat",
            json=payload,
            headers={"X-Device-Key": "dummy-key"},
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            res_json = response.json()
            latest_version = res_json.get("latest_config_version")
            update_available = res_json.get("config_update_available", False) or res_json.get("requires_config_sync", False)
            current_version = int(config_version)
            if update_available or (latest_version and latest_version > current_version):
                pull_latest_config(db)
    except requests.RequestException:
        pass # silently fail heartbeat

def pull_latest_config(db: Database) -> None:
    try:
        current_version = int(db.get_device_state("config_version") or "1")
        response = requests.get(
            f"{config.BACKEND_BASE_URL}/devices/sim-01/config?since_version={current_version}",
            headers={"X-Device-Key": "dummy-key"},
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            config_data = response.json()
            schedules = config_data.get("schedules", [])
            new_version = config_data.get("config_version") or config_data.get("version", current_version + 1)
            
            db.update_schedules(schedules)
            db.update_device_state("config_version", str(new_version))
            logger.info("Config successfully synced to version %s.", new_version)

            # Send Config ACK to backend to close reconciliation loop
            try:
                ack_payload = {
                    "config_version": int(new_version),
                    "applied_at": config_data.get("server_time") or datetime.now().isoformat()
                }
                requests.post(
                    f"{config.BACKEND_BASE_URL}/devices/sim-01/config-ack",
                    json=ack_payload,
                    headers={"X-Device-Key": "dummy-key"},
                    timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
                )
                logger.info("Config ACK sent to backend.")
            except requests.RequestException:
                pass
        elif response.status_code == 304:
            logger.info("Config is already up to date (304 Not Modified).")
    except requests.RequestException:
        pass
