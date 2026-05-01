import os

from .registry import FEATURE_FACE_CAP, FEATURE_MIFRAMES, FEATURE_R2BB

# Orbisauth license server URL.
# Override with the RIG2_LICENSE_SERVER_URL environment variable.
DEFAULT_SERVER_URL = os.environ.get(
    "RIG2_LICENSE_SERVER_URL",
    "https://orbisauth.mozi1924.com",
)

# Product identifier registered in Orbisauth.
PRODUCT_NAME = "rig2"

# Session file stored alongside this module.
SESSION_FILENAME = "rig2_license_session.json"
FEATURE_STATUS_FILENAME = "rig2_feature_status.json"

# Heartbeat interval in seconds (used by Blender timer).
HEARTBEAT_INTERVAL_SECONDS = 300

# Refresh token skew in seconds (refresh early to avoid expiry gaps).
REFRESH_SKEW_SECONDS = 120

# HTTP timeout in seconds for license server requests.
HTTP_TIMEOUT_SECONDS = 15.0
