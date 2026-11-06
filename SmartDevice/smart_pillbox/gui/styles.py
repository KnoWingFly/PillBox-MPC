"""Design tokens & color constants for Clean Dark-Slate Medical IoT."""

# Base Theme (Clean Dark-Slate)
WINDOW_BG = "#0F172A"       # Dark Slate 900
CHASSIS_BG = "#1E293B"      # Dark Slate 800
CHASSIS_BORDER = "#334155"  # Dark Slate 700

# LCD Display (Ultra Dark OLED)
LCD_BG = "#030712"          # Ultra Dark Gray / Black
LCD_BORDER = "#1F2937"      # Subtle border
LCD_TEXT = "#E2E8F0"        # Monospaced Slate 200
LCD_MUTED = "#94A3B8"       # Slate 400
LCD_CYAN = "#06B6D4"        # Medical Cyan

# Chamber States
ACTIVE_CYAN = "#06B6D4"     # Glowing Cyan for active intake slot
IDLE_SLOT_BG = "#1E293B"    # Clean dark slot background
IDLE_SLOT_BORDER = "#334155"# Thin slate border
TAKEN_COLOR = "#10B981"     # Emerald
MISSED_COLOR = "#EF4444"    # Red
IDLE_COLOR = "#475569"      # Muted slate

BACKGROUND = "#0F172A"
TEXT_LIGHT = "#F8FAFC"
TEXT_MUTED = "#94A3B8"
TEXT_DARK = "#475569"

# Dose LED while a chamber is popped up (breathing): yellow before meal, blue after meal.
LED_BEFORE_MEAL = "#FACC15"   # Yellow 400
LED_AFTER_MEAL = "#3B82F6"    # Blue 500

# LCD alerts and sound badge
LCD_ALERT = "#F87171"         # Red 400: stock empty
LCD_REFILL_BORDER = IDLE_COLOR
SOUND_BADGE_BG = "#FBBF24"    # Amber 400
SOUND_BADGE_TEXT = WINDOW_BG

# Lab workbench and status bar
BUTTON_BG = CHASSIS_BORDER
BUTTON_HOVER_BG = IDLE_COLOR
BUTTON_TEXT = TEXT_LIGHT
STATUS_BAR_TEXT = "#888888"
WIFI_ONLINE_BG = "#065F46"    # Emerald 800
WIFI_OFFLINE_BG = "#7F1D1D"   # Red 900
REFILL_ACTIVE_BG = "#0E7490"  # Cyan 700
STATUS_OK = "#6EE7B7"         # Emerald 300: paired
STATUS_WARN = "#FCD34D"       # Amber 300: waiting for pairing / outbox not empty
STATUS_ERROR = "#FCA5A5"      # Red 300: not registered, key rejected, server unreachable
