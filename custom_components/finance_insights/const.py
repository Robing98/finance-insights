"""Constants for Finance Insights."""

DOMAIN = "finance_insights"
LEGACY_DOMAIN = "traderepublic_insights"

CONF_ACCOUNT_TYPE = "account_type"
TYPE_TRADE_REPUBLIC = "trade_republic"
TYPE_BANK = "bank"
TYPE_OVERVIEW = "overview"

CONF_NAME = "name"
CONF_FOLDER = "folder"
CONF_SCAN_MINUTES = "scan_minutes"

# Trade Republic
CONF_USE_PYTR = "use_pytr"
CONF_PHONE = "phone"
CONF_PIN = "pin"
CONF_CODE = "code"
CONF_TIMELINE_HOURS = "timeline_hours"
DEFAULT_TR_FOLDER = "trade_republic"
DEFAULT_TIMELINE_HOURS = 6
PYTR_REQUIREMENT = "pytr==0.4.10"
PRICES_FILE = "prices.csv"
BONDS_FILE = "bonds.csv"
PYTR_DIR = ".pytr"

# Bank (Sparkasse and other FinTS banks)
CONF_USE_FINTS = "use_fints"
CONF_BLZ = "blz"
CONF_LOGIN = "login"
CONF_SERVER = "server"
CONF_PRODUCT_ID = "product_id"
CONF_TAN = "tan"
CONF_IBAN = "iban"
CONF_FINTS_HOURS = "fints_hours"
CONF_TRANSFER_KEYWORDS = "transfer_keywords"
CONF_OFFSET_RULES = "offset_rules"
DEFAULT_BANK_FOLDER = "sparkasse"
DEFAULT_BANK_NAME = "Sparkasse"
DEFAULT_FINTS_HOURS = 6
FINTS_REQUIREMENT = "fints==5.0.0"
BALANCE_FILE = "balance.csv"
RULES_FILE = "categories.csv"
FINTS_STATE_DIR = "finance_insights_fints"

DEFAULT_SCAN_MINUTES = 30
SIGNAL_ACCOUNTS_UPDATED = f"{DOMAIN}_accounts_updated"
