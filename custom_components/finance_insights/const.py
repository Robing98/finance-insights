"""Constants for Finance Insights."""

DOMAIN = "finance_insights"
LEGACY_DOMAIN = "traderepublic_insights"

CONF_ACCOUNT_TYPE = "account_type"
CONF_DEMO = "demo"
TYPE_TRADE_REPUBLIC = "trade_republic"
TYPE_BANK = "bank"
TYPE_OVERVIEW = "overview"
TYPE_UTILITY = "utility"

# Energy and water costs
CONF_UTILITY = "utility"
CONF_STATISTIC = "statistic"
CONF_KWH_PER_M3 = "kwh_per_m3"
SUBENTRY_CONTRACT = "contract"
CONF_SUPPLIER = "supplier"
CONF_START = "start"
CONF_END = "end"
CONF_UNIT_PRICE = "unit_price"
CONF_BASE_PRICE = "base_price"
CONF_ADVANCE = "advance"
CONF_BONUS = "bonus"
CONF_NOTICE_WEEKS = "notice_weeks"

CONF_NAME = "name"
# People: the HA user an account belongs to, users it is shared with, and overview members.
CONF_OWNER = "owner"
CONF_SHARED = "shared_with"
CONF_MEMBERS = "members"
DEFAULT_TR_TITLE = "Trade Republic"
DEFAULT_OVERVIEW_TITLE = "Finance overview"
SERVICE_BUILD_DASHBOARD = "build_dashboard"
SERVICE_BACKFILL_HISTORY = "backfill_history"
ATTR_DASHBOARD = "dashboard"
ATTR_RESET = "reset"
ATTR_LANGUAGE = "language"
ATTR_THEME = "theme"
THEME_NAME = "Finance Insights"
THEME_FILE = "finance_insights.yaml"
FRONTEND_URL = "/finance_insights_static"
DASHBOARD_STORE_KEY = "finance_insights.dashboard"
CONF_FOLDER = "folder"
CONF_SCAN_MINUTES = "scan_minutes"

# Trade Republic
CONF_USE_PYTR = "use_pytr"
CONF_PHONE = "phone"
CONF_PIN = "pin"
CONF_PIN_CONFIRM = "pin_confirm"
# Keep the PIN in memory only and ask for it again after a restart.
CONF_ASK_PIN = "ask_pin"
CONF_CODE = "code"
CONF_TIMELINE_HOURS = "timeline_hours"
DEFAULT_TR_FOLDER = "trade_republic"
DEFAULT_TIMELINE_HOURS = 6
# Exact versions, including the packages pip would otherwise pick on its own. A pinned version
# cannot be moved to other code, so a new release of any of these reaches you only when this list
# changes. Packages Home Assistant already ships are left out: its own constraints decide those.
# Regenerate with scripts/pins.py after changing a version, and read what changed before shipping it.
PYTR_REQUIREMENTS = (
    "coloredlogs==15.0.1",
    "curl_cffi==0.16.3",
    "humanfriendly==10.0",
    "pathvalidate==3.3.1",
    "requests-futures==1.1.0",
    "shtab==1.12.1",
    "websockets==17.1",
    "pytr==0.4.10",
)
PRICES_FILE = "prices.csv"
BONDS_FILE = "bonds.csv"
PYTR_DIR = ".pytr"
# Dividend data
CONF_DIVIDEND_PROVIDER = "dividend_provider"
CONF_DIVIDEND_API_KEY = "dividend_api_key"
CONF_YAHOO_FALLBACK = "yahoo_fallback"
CONF_BENCHMARKS = "benchmarks"
# Both send the ISINs of your holdings to a service outside your network, so they are off
# until you switch them on.
DEFAULT_MARKET_ONLINE = False
CONF_WATCHLIST = "include_watchlist"
CONF_MARKET_HOURS = "market_refresh_hours"
DIVIDEND_PROVIDERS = ["none", "eodhd", "alphavantage", "finnhub"]
DEFAULT_MARKET_HOURS = 24

# Tax estimates per Trade Republic account (the owner's tax situation)
CONF_TAX_ALLOWANCE = "tax_allowance"
CONF_TAX_OTHER_INCOME = "tax_other_income"
CONF_TAX_JOINT = "tax_joint"
CONF_TAX_CHURCH = "tax_church"
TAX_CHURCH_RATES = ["0", "8", "9"]

# Bank (Sparkasse and other FinTS banks)
CONF_USE_FINTS = "use_fints"
CONF_BLZ = "blz"
CONF_BANK_SEARCH = "bank_search"
CONF_LOGIN = "login"
CONF_SERVER = "server"
CONF_PRODUCT_ID = "product_id"
CONF_TAN = "tan"
CONF_IBAN = "iban"
CONF_FINTS_HOURS = "fints_hours"
CONF_TRANSFER_KEYWORDS = "transfer_keywords"
CONF_OFFSET_RULES = "offset_rules"
# Business account: net, VAT, and profit from the bookings of a self-employed person.
CONF_BUSINESS = "business"
CONF_SMALL_BUSINESS = "small_business"
CONF_VAT_DEFAULT = "vat_default"
CONF_TAX_RESERVE = "tax_reserve"
DEFAULT_TAX_RESERVE = 30
# "none" leaves a booking unassigned instead of guessing its rate.
VAT_RATES = ["none", "19", "7", "0"]
DEFAULT_BANK_FOLDER = "sparkasse"
DEFAULT_BANK_NAME = "Sparkasse"
DEFAULT_FINTS_HOURS = 6
FINTS_REQUIREMENTS = (
    "bleach==6.4.0",
    "elementpath==5.1.4",
    "enum-tools==0.12.0",
    "lxml==6.0.4",
    "mt-940==5.1.1",
    "sepaxml==2.7.0",
    "text-unidecode==1.3",
    "webencodings==0.6.1",
    "xmlschema==4.3.2",
    "fints==5.0.0",
)
BALANCE_FILE = "balance.csv"
RULES_FILE = "categories.csv"
FINTS_STATE_DIR = "finance_insights_fints"

DEFAULT_SCAN_MINUTES = 30
SIGNAL_ACCOUNTS_UPDATED = f"{DOMAIN}_accounts_updated"
