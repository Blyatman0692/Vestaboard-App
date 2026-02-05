import os
import base64
import secrets
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
import httpx
from urllib.parse import urlencode
from fastapi.responses import JSONResponse
from sonos_app.sonos_client import SonosToken, SonosClient
from sonos_app.sonos_oauth_client import SonosOAuthClient

app = FastAPI()

SONOS_CLIENT_ID = os.environ["SONOS_CLIENT_ID"]
SONOS_CLIENT_SECRET = os.environ["SONOS_CLIENT_SECRET"]
SONOS_REDIRECT_URI = os.environ["SONOS_REDIRECT_URI"]
PENDING_STATES: set[str] = set()

# global oauth client to store state
oauth_client = SonosOAuthClient(
    SONOS_CLIENT_ID,
    SONOS_CLIENT_SECRET,
    SONOS_REDIRECT_URI
)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/oauth/start")
def oauth_start():
    return RedirectResponse(oauth_client.get_oauth_url())


@app.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    tokens = await oauth_client.oauth_callback(code, state)

    return PlainTextResponse("Authorization success. Close this tab.")

@app.get("/sonos/households")
async def sonos_households():
    client = SonosClient(SonosToken(os.getenv("SONOS_ACCESS_TOKEN")))
    data = await client.get_households()
    return data
