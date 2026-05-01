import json
import urllib.error
import urllib.request
from typing import Any

from ._errors import OrbisAuthAPIError, OrbisAuthNetworkError

USER_AGENT = "OrbisAuth/1.0 (Rig2; Blender)"


def _decode_error_body(status: int, body: bytes, fallback_message: str = "Unknown error") -> OrbisAuthAPIError:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return OrbisAuthAPIError(status, "UNKNOWN", body.decode("utf-8", errors="replace"))

    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        error_code = error_obj.get("code", "UNKNOWN")
        error_message = error_obj.get("message", fallback_message)
    elif isinstance(error_obj, str):
        error_code = "UNKNOWN"
        error_message = error_obj
    else:
        error_code = "UNKNOWN"
        error_message = payload.get("message") or payload.get("detail") or fallback_message
    return OrbisAuthAPIError(status, error_code, error_message)


def _api_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Make an HTTP request to the OrbisAuth server and return parsed JSON.

    On 2xx returns the parsed JSON body as a dict.
    On non-2xx parses the error body and raises OrbisAuthAPIError.
    On network failure raises OrbisAuthNetworkError.
    """
    req_headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if headers:
        req_headers.update(headers)

    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    http_request = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as e:
        body = e.read()
        status = e.code
    except urllib.error.URLError as e:
        raise OrbisAuthNetworkError(str(e.reason)) from e
    except OSError as e:
        raise OrbisAuthNetworkError(str(e)) from e

    try:
        payload: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise _decode_error_body(status, body)

    if 200 <= status < 300:
        return payload
    raise _decode_error_body(status, body)


def _stream_request(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[Any, int | None]:
    """Make a streaming HTTP GET and return (response, content_length)."""
    req_headers: dict[str, str] = {
        "User-Agent": USER_AGENT,
    }
    if headers:
        req_headers.update(headers)

    http_request = urllib.request.Request(url, headers=req_headers, method="GET")

    try:
        response = urllib.request.urlopen(http_request, timeout=timeout)
        content_length = response.headers.get("Content-Length")
        length: int | None = int(content_length) if content_length else None
        return response, length
    except urllib.error.HTTPError as e:
        body = e.read()
        raise _decode_error_body(e.code, body, fallback_message=str(e))
    except urllib.error.URLError as e:
        raise OrbisAuthNetworkError(str(e.reason)) from e
    except OSError as e:
        raise OrbisAuthNetworkError(str(e)) from e
