"""Constants for Trade Republic Insights."""

DOMAIN = "traderepublic_insights"

CONF_FOLDER = "folder"
CONF_USE_PYTR = "use_pytr"
CONF_PHONE = "phone"
CONF_PIN = "pin"
CONF_CODE = "code"
CONF_SCAN_MINUTES = "scan_minutes"
CONF_TIMELINE_HOURS = "timeline_hours"

DEFAULT_FOLDER = "trade_republic"
DEFAULT_SCAN_MINUTES = 30
DEFAULT_TIMELINE_HOURS = 6

# Pinned: the integration calls into pytr internals (login process, Timeline,
# Portfolio). Test before raising the pin.
PYTR_REQUIREMENT = "pytr==0.4.10"

PRICES_FILE = "prices.csv"
BONDS_FILE = "bonds.csv"
PYTR_DIR = ".pytr"
