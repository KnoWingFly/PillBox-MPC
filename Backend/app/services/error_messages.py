"""User-facing error messages that the app shows as they are (schedule guards, late release),
localized by the caller's users.interface_language like notification text.

get_current_user records the caller's language for the request (request_language_var), so the
services raising these errors do not need the user passed down."""

from contextvars import ContextVar
from typing import Any

from app.services.notifications import DEFAULT_LANGUAGE

request_language_var: ContextVar[str | None] = ContextVar("request_language", default=None)

SLOT_DOOR_OPEN = "SLOT_DOOR_OPEN"
SLOT_RELEASED = "SLOT_RELEASED"
SLOT_RINGING = "SLOT_RINGING"
WINDOW_OVERLAP = "WINDOW_OVERLAP"
SCHEDULE_TOO_CLOSE = "SCHEDULE_TOO_CLOSE"
THIS_SLOT = "THIS_SLOT"
THIS_SCHEDULE = "THIS_SCHEDULE"
LATE_DOSE_TOO_LATE = "LATE_DOSE_TOO_LATE"
DOSE_NOT_MISSED = "DOSE_NOT_MISSED"

_MESSAGES: dict[str, dict[str, str]] = {
    SLOT_DOOR_OPEN: {
        "ID": "Pintu bilik {label} sedang terbuka di pillbox. Tutup dulu, lalu simpan lagi.",
        "EN": "Compartment {label} is open on the pillbox. Close it, then save again.",
    },
    SLOT_RELEASED: {
        "ID": "Bilik {label} sedang dibuka lagi untuk dosis yang terlewat (sampai {until}). Ubah setelah itu selesai.",
        "EN": "Compartment {label} is re-opened for a missed dose (until {until}). Change it after that.",
    },
    SLOT_RINGING: {
        "ID": "Slot {label} sedang berbunyi di pillbox (jadwal {start}, sampai {end}). "
        "Ubah setelah obatnya diambil atau waktunya lewat.",
        "EN": "Slot {label} is ringing on the pillbox (scheduled {start}, until {end}). "
        "Change it after the dose is taken or the time has passed.",
    },
    WINDOW_OVERLAP: {
        "ID": "{me} bentrok dengan slot {other} pada {at}. Pilih jam lain.",
        "EN": "{me} overlaps slot {other} at {at}. Choose another time.",
    },
    SCHEDULE_TOO_CLOSE: {
        "ID": "{me} terlalu dekat dengan slot {other}: pillbox hanya membuka satu bilik sekaligus, "
        "jadi beri jarak minimal {gap} menit (selama waktu toleransinya).",
        "EN": "{me} is too close to slot {other}: the pillbox opens one compartment at a time, "
        "so keep at least {gap} minutes apart (its tolerance).",
    },
    THIS_SLOT: {"ID": "Slot {label}", "EN": "Slot {label}"},
    THIS_SCHEDULE: {"ID": "Jadwal ini", "EN": "This schedule"},
    LATE_DOSE_TOO_LATE: {
        "ID": "Sudah lewat batas aman (pukul {cutoff}): terlalu dekat dengan jadwal berikutnya. "
        "Jangan diminum, tunggu jadwal berikutnya.",
        "EN": "Past the safe limit ({cutoff}): too close to the next dose. Do not take it; wait for the next dose.",
    },
    DOSE_NOT_MISSED: {"ID": "Dosis ini sudah tercatat diminum.", "EN": "This dose is already recorded as taken."},
}


def error_text(key: str, **params: Any) -> str:
    """The message in the current caller's language (unknown or no caller: the default one)."""
    templates = _MESSAGES[key]
    language = (request_language_var.get() or DEFAULT_LANGUAGE).upper()
    return templates.get(language, templates[DEFAULT_LANGUAGE]).format(**params)
