from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass
class PlaybackMetadata:
    group_id: Optional[str]
    provider: Optional[str]
    provider_service_id: Optional[str]
    playlist_name: Optional[str]
    playlist_type: Optional[str]
    playlist_object_id: Optional[str]
    track_name: Optional[str]
    artist_name: Optional[str]
    album_name: Optional[str]
    track_object_id: Optional[str]
    duration_ms: Optional[int]
    image_url: Optional[str]
    next_track_name: Optional[str]
    next_artist_name: Optional[str]
    raw_namespace: Optional[str]
    raw_type: Optional[str]


def _lower_keys(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(k).lower(): v for k, v in headers.items()}


def _get(d: Any, *path: str) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _first_image_url(obj: Any) -> Optional[str]:
    """
    Given a dict that may contain `imageUrl` or `images: [{url: ...}]`, return the best URL.
    """
    if isinstance(obj, Mapping):
        # Prefer imageUrl if present
        url = obj.get("imageUrl")
        if isinstance(url, str) and url.strip():
            return url

        images = obj.get("images")
        if isinstance(images, list):
            for img in images:
                if isinstance(img, Mapping):
                    u = img.get("url")
                    if isinstance(u, str) and u.strip():
                        return u
    return None


def parse_playback_metadata(headers: Mapping[str, str], body: Mapping[str, Any]) -> PlaybackMetadata | None:
    """
    Parse a Sonos `playbackMetadata` event payload into a normalized PlaybackMetadata object.

    Extracts:
      - provider/service (Spotify/Apple Music/etc.)
      - playlist/container name + type + objectId
      - current track: name, artist, album, objectId, duration, image
      - next track: name, artist
      - group_id from Sonos event headers (target-value)
    """
    h = _lower_keys(headers)

    raw_namespace = h.get("x-sonos-namespace")
    raw_type = h.get("x-sonos-type")

    target_type = (h.get("x-sonos-target-type") or "").lower()
    group_id = h.get("x-sonos-target-value") if target_type in {"groupid", "group_id", "group"} else None

    # Container (often playlist)
    container_name = _get(body, "container", "name")
    container_type = _get(body, "container", "type")
    provider = _get(body, "container", "service", "name")
    provider_service_id = _get(body, "container", "service", "id")
    playlist_object_id = _get(body, "container", "id", "objectId")

    # Current track
    track_name = _get(body, "currentItem", "track", "name")
    artist_name = _get(body, "currentItem", "track", "artist", "name")
    album_name = _get(body, "currentItem", "track", "album", "name")
    track_object_id = _get(body, "currentItem", "track", "id", "objectId")
    duration_ms = _get(body, "currentItem", "track", "durationMillis")

    # Next track
    next_track_name = _get(body, "nextItem", "track", "name")
    next_artist_name = _get(body, "nextItem", "track", "artist", "name")

    # Choose best image url: track -> container -> fallbacks in images
    track = _get(body, "currentItem", "track")
    container = _get(body, "container")
    image_url = _first_image_url(track) or _first_image_url(container)

    if not isinstance(track_name, str) or not track_name.strip():
        return None

    # Normalize duration to int if possible
    duration_int: Optional[int]
    if isinstance(duration_ms, int):
        duration_int = duration_ms
    elif isinstance(duration_ms, str) and duration_ms.isdigit():
        duration_int = int(duration_ms)
    else:
        duration_int = None

    return PlaybackMetadata(
        group_id=group_id,
        provider=provider if isinstance(provider, str) else None,
        provider_service_id=provider_service_id if isinstance(provider_service_id, str) else None,
        playlist_name=container_name if isinstance(container_name, str) else None,
        playlist_type=container_type if isinstance(container_type, str) else None,
        playlist_object_id=playlist_object_id if isinstance(playlist_object_id, str) else None,
        track_name=track_name.strip(),
        artist_name=artist_name if isinstance(artist_name, str) else None,
        album_name=album_name if isinstance(album_name, str) else None,
        track_object_id=track_object_id if isinstance(track_object_id, str) else None,
        duration_ms=duration_int,
        image_url=image_url,
        next_track_name=next_track_name if isinstance(next_track_name, str) else None,
        next_artist_name=next_artist_name if isinstance(next_artist_name, str) else None,
        raw_namespace=raw_namespace,
        raw_type=raw_type,
    )