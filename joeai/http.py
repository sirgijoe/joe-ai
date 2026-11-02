"""Tiny JSON-over-HTTP helper (stdlib only, keeps the packaged app small)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    pass


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise HttpError(f"HTTP {e.code} from {url}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise HttpError(f"can't reach {url}: {e}") from e
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise HttpError(f"bad JSON from {url}: {body[:200]}") from e


def request_bytes(url: str, timeout: float = 60) -> bytes:
    """GET raw bytes (images/videos from ComfyUI's /view)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise HttpError(f"HTTP {e.code} from {url}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise HttpError(f"can't reach {url}: {e}") from e
