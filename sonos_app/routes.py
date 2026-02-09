import os
import base64
import secrets
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
import httpx
from urllib.parse import urlencode
from fastapi.responses import JSONResponse
from watchfiles import awatch

from sonos_app.config import SONOS_CLIENT_ID, SONOS_CLIENT_SECRET, DB_URL, \
    SONOS_REDIRECT_URI
from sonos_app.data_store import PostgresDataStore
from sonos_app.sonos_client import SonosToken, SonosClient
from sonos_app.sonos_oauth_client import SonosOAuthClient

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()


PENDING_STATES: set[str] = set()

# global oauth client to store state
oauth_client = SonosOAuthClient(
    SONOS_CLIENT_ID,
    SONOS_CLIENT_SECRET,
    SONOS_REDIRECT_URI
)

db_client = PostgresDataStore(
    DB_URL,
    SONOS_CLIENT_ID
)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/oauth/start")
def oauth_start():
    return RedirectResponse(oauth_client.get_oauth_url())


@app.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    logger.info(
        "[OAUTH CALLBACK] Received state=%s | pending_states=%s",
        state,
        list(oauth_client.pending_states),
    )
    tokens = await oauth_client.oauth_callback(code, state)

    db_client.save_tokens(tokens)

    return PlainTextResponse("Authorization successful. Close this tab.")

@app.get("/sonos/households")
async def sonos_households():
    tokens = db_client.load_tokens()

    client = SonosClient(tokens, db_client, oauth_client)

    return await client.get_households()

@app.get("/sonos/groups")
async def sonos_groups():
    tokens = db_client.load_tokens()
    client = SonosClient(tokens, db_client, oauth_client)

    households = await client.get_households()
    household_id = households["households"][0]["id"]

    return await client.get_groups(household_id)