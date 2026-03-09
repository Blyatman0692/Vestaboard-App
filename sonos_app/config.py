import os

SONOS_CLIENT_ID = os.environ["SONOS_CLIENT_ID"]
SONOS_CLIENT_SECRET = os.environ["SONOS_CLIENT_SECRET"]
SONOS_REDIRECT_URI = os.environ["SONOS_REDIRECT_URI"]
DB_URL = os.environ["DATABASE_URL"]

SONOS_OAUTH_BASE_URL = "https://api.sonos.com/login/v3/oauth?"
SONOS_CONTROL_BASE_URL = "https://api.ws.sonos.com/control/api/v1"
SONOS_OAUTH_TOKEN_URL = "https://api.sonos.com/login/v3/oauth/access"
