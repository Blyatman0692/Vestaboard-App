from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
import base64
import hashlib

from app import build_container
from sonos_app.sonos_client import SonosClient
from sonos_app.playback_metadata import parse_playback_metadata
from sonos_app.config import SONOS_CLIENT_ID, SONOS_CLIENT_SECRET

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()


container = build_container()
oauth_client = container.sonos_oauth_client
db_client = container.sonos_data_store
event_processor = container.sonos_event_processor

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/oauth/start")
def oauth_start():
    return RedirectResponse(oauth_client.get_oauth_url())


@app.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    logger.info(
        "[OAUTH CALLBACK] Received state=%s",
        state,
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

def verify_sonos_event_signature(
    seq_id: str,
    namespace: str,
    typ: str,
    target_type: str,
    target_value: str,
    client_id: str,
    client_secret: str,
    signature: str
) -> bool:
    sha = hashlib.sha256()

    for value in [
        seq_id,
        namespace,
        typ,
        target_type,
        target_value,
        client_id,
        client_secret,
    ]:
        sha.update(value.encode("utf-8"))

    return signature == base64.urlsafe_b64encode(sha.digest()).decode("utf-8").rstrip("=")

@app.post("/sonos/events")
async def sonos_events(request: Request):
    headers = request.headers
    seq_id = headers.get("X-Sonos-Event-Seq-Id")
    namespace = headers.get("X-Sonos-Namespace")
    event_type = headers.get("X-Sonos-Type")
    target_type = headers.get("X-Sonos-Target-Type")
    target_value = headers.get("X-Sonos-Target-Value")
    signature = headers.get("X-Sonos-Event-Signature")

    if not verify_sonos_event_signature(seq_id, namespace, event_type, target_type, target_value, SONOS_CLIENT_ID, SONOS_CLIENT_SECRET, signature):
        raise HTTPException(status_code=401, detail="Invalid Sonos signature")

    body = await request.json()
    metadata = parse_playback_metadata(request.headers, body)
    event_processor.process_metadata(metadata)
    print(metadata)

    return JSONResponse({"ok": True})

@app.post("/sonos/subscribe/{group_id}")
async def subscribe_group(group_id: str):
    tokens = db_client.load_tokens()
    if not tokens:
        raise HTTPException(status_code=400, detail="No tokens found. Run /oauth/start first.")

    client = SonosClient(tokens, db_client, oauth_client)

    await client.subscribe_playback_metadata(group_id)

    return JSONResponse(
        {
            "ok": True,
            "group_id": group_id,
            "subscribed": ["playbackMetadata"],
        }
    )
