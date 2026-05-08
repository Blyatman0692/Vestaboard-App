from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
import asyncio
import base64
import hashlib

from app import build_sonos_container
from sonos_app.sonos_client import SonosClient, SonosReauthorizationRequired
from sonos_app.sonos_oauth_client import SonosAuthError
from sonos_app.playback_metadata import parse_playback_metadata
from sonos_app.subscription_renewer import PlaybackMetadataSubscriptionRenewer

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
subscription_renewer = PlaybackMetadataSubscriptionRenewer(db_client, oauth_client)
subscription_renewer_task: asyncio.Task | None = None


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


@app.on_event("startup")
async def start_subscription_renewer():
    global subscription_renewer_task

    if subscription_renewer_task and not subscription_renewer_task.done():
        return

    subscription_renewer_task = asyncio.create_task(
        subscription_renewer.run_forever()
    )


@app.on_event("shutdown")
async def stop_subscription_renewer():
    global subscription_renewer_task

    if not subscription_renewer_task:
        return

    subscription_renewer_task.cancel()
    try:
        await subscription_renewer_task
    except asyncio.CancelledError:
        pass
    finally:
        subscription_renewer_task = None


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

    subscription = db_client.save_playback_metadata_subscription(group_id)

    return JSONResponse(
        {
            "ok": True,
            "group_id": group_id,
            "subscribed": ["playbackMetadata"],
            "subscription": subscription,
        }
    )


@app.get("/sonos/subscriptions")
def sonos_subscriptions():
    return JSONResponse(
        {
            "ok": True,
            "subscriptions": db_client.list_playback_metadata_subscriptions(),
        }
    )


@app.post("/sonos/subscriptions/renew")
async def renew_sonos_subscriptions(request: Request):
    result = await subscription_renewer.renew_due()

    if result.get("reauthorization_required"):
        payload = reauthorization_payload(
            request,
            result.get("detail", "Sonos reauthorization is required."),
        )
        payload.update(result)
        return JSONResponse(status_code=401, content=payload)

    return JSONResponse(
        status_code=200 if result["ok"] else 502,
        content=result,
    )
