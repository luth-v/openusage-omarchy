"""OpenUsage for Omarchy: plan Quotas and Spend for coding Providers.

Stdlib only. No third-party Python dependencies: installs are a git clone.
"""

PLUGIN_ID = "luth-v.openusage-omarchy"
APP_DIR = "openusage-omarchy"
STATE_SCHEMA = "openusage-omarchy.state.v1"
LAYOUT_SCHEMA = "openusage-omarchy.layout.v1"
CATALOG_SCHEMA = "openusage-omarchy.catalog.v1"
LIMITS_SCHEMA = "openusage.limits.v1"
REFRESH_INTERVAL_S = 300
PROVIDER_DEADLINE_S = 120
SPEND_DEADLINE_S = 120
HTTP_TIMEOUT_S = 30
API_HOST = "127.0.0.1"
API_PORT = 6736
