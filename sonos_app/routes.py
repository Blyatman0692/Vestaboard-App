import os
import base64
import secrets
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
import httpx
from urllib.parse import urlencode
from fastapi.responses import JSONResponse
from sonos_app.sonos_client import SonosToken, SonosClient

app = FastAPI()

SONOS_CLIENT_ID = os.environ["SONOS_CLIENT_ID"]
SONOS_CLIENT_SECRET = os.environ["SONOS_CLIENT_SECRET"]
SONOS_CONTROL_BASE = "https://api.ws.sonos.com/control/api/v1"
PENDING_STATES: set[str] = set()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/oauth/start")
def oauth_start():
    state = secrets.token_urlsafe(24)
    PENDING_STATES.add(state)

    # IMPORTANT: redirect_uri must exactly match what you register in Sonos portal
    redirect_uri = os.environ["SONOS_REDIRECT_URI"]

    params = {
        "client_id": SONOS_CLIENT_ID,
        "response_type": "code",
        "state": state,
        "scope": "playback-control-all",
        "redirect_uri": redirect_uri,
    }

    auth_url = "https://api.sonos.com/login/v3/oauth?" + urlencode(params)

    print("SONOS AUTH URL:", auth_url)
    return RedirectResponse(auth_url)

@app.get("/oauth/callback")
async def oauth_callback(code: str | None = None, state: str | None = None):
    if not code or not state:
        raise HTTPException(400, "Missing code or state")

    if state not in PENDING_STATES:
        raise HTTPException(400, "Invalid state")

    PENDING_STATES.remove(state)

    redirect_uri = os.environ["SONOS_REDIRECT_URI"]

    basic = base64.b64encode(f"{SONOS_CLIENT_ID}:{SONOS_CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.sonos.com/login/v3/oauth/access",
            headers=headers,
            data=data,
        )

    if resp.status_code != 200:
        raise HTTPException(500, f"Token exchange failed: {resp.status_code} {resp.text}")

    tokens = resp.json()

    # For milestone 1: print tokens to Railway logs and return success
    print("SONOS TOKENS:", tokens)

    return PlainTextResponse("Success! You can close this tab.")

@app.get("/sonos/households")
async def sonos_households():
    client = SonosClient(SonosToken(os.getenv("SONOS_ACCESS_TOKEN")))
    data = await client.get_households()
    return data
