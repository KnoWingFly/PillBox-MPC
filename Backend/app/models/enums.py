"""String enums mirroring the CHECK constraints in migrations/*.sql."""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    PEMANTAU = "PEMANTAU"


EDITOR_ROLES = frozenset({Role.OWNER, Role.ADMIN})
ALL_ROLES = frozenset(Role)


class Gender(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class ChimeVolume(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Connectivity(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class RowType(StrEnum):
    A = "A"
    B = "B"


class MealRelation(StrEnum):
    BEFORE_MEAL = "BEFORE_MEAL"
    AFTER_MEAL = "AFTER_MEAL"


class DayPeriod(StrEnum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"
    NIGHT = "NIGHT"


class DoseStatus(StrEnum):
    TAKEN = "TAKEN"
    MISSED = "MISSED"
    PENDING = "PENDING"


class JournalStatus(StrEnum):
    """API List representation, derived from DoseStatus + delay_minutes."""

    PENDING = "PENDING"
    TAKEN_ON_TIME = "TAKEN_ON_TIME"
    TAKEN_LATE = "TAKEN_LATE"
    MISSED = "MISSED"


class LogSource(StrEnum):
    AUTO_SENSOR = "AUTO_SENSOR"
    MANUAL_CAREGIVER_CONFIRMATION = "MANUAL_CAREGIVER_CONFIRMATION"
    SYSTEM_RULES_ENGINE = "SYSTEM_RULES_ENGINE"


class NotificationType(StrEnum):
    DOSE_LATE = "DOSE_LATE"
    DOSE_MISSED = "DOSE_MISSED"
    DOSE_TAKEN = "DOSE_TAKEN"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_ONLINE = "DEVICE_ONLINE"
    LOW_BATTERY = "LOW_BATTERY"
    UNSCHEDULED_OPEN = "UNSCHEDULED_OPEN"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class DeviceEventType(StrEnum):
    # API List event types (emulator emits these)
    POPUP_ACTIVATED = "POPUP_ACTIVATED"
    COMPARTMENT_OPENED = "COMPARTMENT_OPENED"
    COMPARTMENT_CLOSED = "COMPARTMENT_CLOSED"
    ALARM_TIMEOUT = "ALARM_TIMEOUT"
    UNSCHEDULED_OPEN = "UNSCHEDULED_OPEN"
    REFILL_MAINTENANCE = "REFILL_MAINTENANCE"
    # Backend additions (see docs/DEVICE_CONTRACT.md)
    ALARM_STARTED = "ALARM_STARTED"
    ALARM_STOPPED = "ALARM_STOPPED"
    BATTERY_STATUS = "BATTERY_STATUS"
    NETWORK_RECOVERED = "NETWORK_RECOVERED"


# telemetry_logs.event_type values written by the server itself.
EVENT_SCHEDULE_DUE = "SCHEDULE_DUE"
EVENT_RULES_ENGINE_MISSED = "RULES_ENGINE_MISSED"
EVENT_MANUAL_CONFIRMATION = "MANUAL_CONFIRMATION"
