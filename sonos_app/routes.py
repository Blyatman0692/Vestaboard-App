from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
import base64
import hashlib

from app import build_sonos_container
from sonos_app.sonos_client import SonosClient, SonosReauthorizationRequired
from sonos_app.sonos_oauth_client import SonosAuthError
from sonos_app.playback_metadata import parse_playback_metadata

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()


container = build_sonos_container()
oauth_client = container.sonos_oauth_client
db_client = container.postgres_data_store
event_processor = container.sonos_event_processor
sonos_config = container.config


def reauthorization_payload(request: Request, detail: str) -> dict[str, str | bool]:
    return {
        "ok": False,
        "error": "sonos_reauthorization_required",
        "detail": detail,
        "reauthorize_url": str(request.url_for("oauth_start")),
        "reauthorize_path": "/oauth/start",
    }


def reauthorization_response(request: Request, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=reauthorization_payload(request, detail),
    )


def load_tokens_or_reauthorize():
    tokens = db_client.load_tokens()
    if not tokens or not tokens.refresh_token:
        raise SonosReauthorizationRequired(
            "No usable Sonos authorization was found. Start OAuth again."
        )
    return tokens


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
    try:
        tokens = await oauth_client.oauth_callback(code, state)
    except SonosAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db_client.save_tokens(tokens)

    return PlainTextResponse("Authorization successful. Close this tab.")


@app.get("/sonos/auth/status")
def sonos_auth_status(request: Request):
    tokens = db_client.load_tokens()
    authorized = bool(tokens and tokens.access_token and tokens.refresh_token)

    response = {
        "ok": True,
        "authorized": authorized,
        "reauthorization_required": not authorized,
        "reauthorize_url": str(request.url_for("oauth_start")),
        "reauthorize_path": "/oauth/start",
    }

    if tokens:
        response.update(
            {
                "scope": tokens.scope,
                "expires_in": tokens.expires_in,
                "updated_at": tokens.updated_at,
                "refresh_token_available": bool(tokens.refresh_token),
            }
        )

    return JSONResponse(response)


@app.get("/sonos/households")
async def sonos_households(request: Request):
    try:
        tokens = load_tokens_or_reauthorize()
    except SonosReauthorizationRequired as exc:
        return reauthorization_response(request, str(exc))

    client = SonosClient(tokens, db_client, oauth_client)

    try:
        return await client.get_households()
    except SonosReauthorizationRequired as exc:
        return reauthorization_response(request, str(exc))

@app.get("/sonos/groups")
async def sonos_groups(request: Request):
    try:
        tokens = load_tokens_or_reauthorize()
    except SonosReauthorizationRequired as exc:
        return reauthorization_response(request, str(exc))

    client = SonosClient(tokens, db_client, oauth_client)

    try:
        households = await client.get_households()
        household_id = households["households"][0]["id"]

        return await client.get_groups(household_id)
    except SonosReauthorizationRequired as exc:
        return reauthorization_response(request, str(exc))

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

    if not verify_sonos_event_signature(
        seq_id,
        namespace,
        event_type,
        target_type,
        target_value,
        sonos_config.client_id,
        sonos_config.client_secret,
        signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid Sonos signature")

    body = await request.json()
    metadata = parse_playback_metadata(request.headers, body)
    event_processor.process_metadata(metadata)
    print(metadata)

    return JSONResponse({"ok": True})

@app.post("/sonos/subscribe/{group_id}")
async def subscribe_group(group_id: str, request: Request):
    try:
        tokens = load_tokens_or_reauthorize()
    except SonosReauthorizationRequired as exc:
        return reauthorization_response(request, str(exc))

    client = SonosClient(tokens, db_client, oauth_client)

    try:
        await client.subscribe_playback_metadata(group_id)
    except SonosReauthorizationRequired as exc:
        return reauthorization_response(request, str(exc))

    return JSONResponse(
        {
            "ok": True,
            "group_id": group_id,
            "subscribed": ["playbackMetadata"],
        }
    )
