from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from json import JSONDecodeError
from json import loads as _json_loads
from typing import Any

import httpx

from .config import get_settings

_DEFAULT_TIMEOUT = 30.0
# Non-SSE 2xx payload preview length carried in the raised APIError body.
_SSE_NON_STREAM_PREVIEW = 2_000


class APIError(Exception):
    def __init__(self, status: int, method: str, path: str, body: Any) -> None:
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"{method} {path} -> {status}: {body}")


def _iter_sse_events(response: httpx.Response, path: str) -> Iterator[dict[str, Any]]:
    """Yield one parsed dict per SSE `data:` line until `data: [DONE]`.

    `data: [DONE]` ends iteration cleanly. A non-JSON `data:` payload raises
    (malformed SSE is an upstream bug to surface, not skip). Reaching
    end-of-stream without `[DONE]` raises (an incomplete stream is a failed
    call, not a short answer) - a consumer that breaks early abandons this
    generator before that final check, so no false failure fires on that path.
    """
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            return
        try:
            parsed: dict[str, Any] = _json_loads(data)
        except JSONDecodeError:
            raise APIError(response.status_code, "POST", path, data) from None
        yield parsed
    raise APIError(response.status_code, "POST", path, "SSE stream ended without [DONE]")


class LiteLLMClient:
    """Thin httpx wrapper for the LiteLLM proxy management API.

    Bearer auth from `LITELLM_API_KEY`, `timeout=30.0` with a per-call
    override. `APIError(status, method, path, body)` on 4xx/5xx with the
    upstream body intact; 204/empty response bodies map to `None`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        s = get_settings()
        base = (base_url or s.litellm_url).rstrip("/")
        key = api_key or s.litellm_api_key
        if not base:
            raise ValueError("LITELLM_URL is required")
        if not key:
            raise ValueError("LITELLM_API_KEY is required")
        self._http = httpx.Client(
            base_url=base,
            headers={"Authorization": f"Bearer {key}"},
            timeout=_DEFAULT_TIMEOUT,
            transport=transport,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        # Per-call bearer override (e.g. key_health probes the given key);
        # a request-level Authorization header overrides the client default
        # for this call only.
        headers = {"Authorization": f"Bearer {auth}"} if auth is not None else None
        kwargs: dict[str, Any] = {"params": params, "json": json, "headers": headers}
        # Only forward an explicit timeout: httpx reads None as "no timeout",
        # not "use the client default".
        if timeout is not None:
            kwargs["timeout"] = timeout
        r = self._http.request(method, path, **kwargs)
        if r.status_code >= 400:
            try:
                body: Any = r.json()
            except JSONDecodeError:
                # Non-JSON error body (proxy HTML, gateway text) surfaces verbatim;
                # the decode failure is not the cause of the API error.
                raise APIError(r.status_code, method, path, r.text) from None
            raise APIError(r.status_code, method, path, body)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    @contextmanager
    def post_sse(
        self,
        path: str,
        *,
        json: Any = None,
        timeout: float | None = None,
    ) -> Iterator[Iterator[dict[str, Any]]]:
        """Stream an SSE POST, yielding one parsed dict per `data:` line.

        Used as `with client.post_sse(...) as events:`. Built on
        `httpx.Client.stream`, so leaving the with-block ALWAYS closes the HTTP
        response - completion, cap-break, and exception paths all release the
        stream with no consumer-side close etiquette. Same bearer auth and
        per-call timeout as `_request`. Non-2xx raises `APIError(status, method,
        path, body)` with the body read in full before raising; a 2xx response
        whose Content-Type is not `text/event-stream` raises with the first
        2000 chars of the payload (upstream documents "always streamed", so
        plain JSON on success is a contract change to surface). `data: [DONE]`
        ends iteration cleanly; a non-JSON `data:` payload or exhaustion without
        `[DONE]` raises.
        """
        kwargs: dict[str, Any] = {"json": json}
        if timeout is not None:
            kwargs["timeout"] = timeout
        with self._http.stream("POST", path, **kwargs) as r:
            if r.status_code >= 400:
                r.read()
                try:
                    body: Any = r.json()
                except JSONDecodeError:
                    raise APIError(r.status_code, "POST", path, r.text) from None
                raise APIError(r.status_code, "POST", path, body)
            content_type = r.headers.get("content-type", "")
            if "text/event-stream" not in content_type.lower():
                r.read()
                raise APIError(
                    r.status_code, "POST", path, r.text[:_SSE_NON_STREAM_PREVIEW]
                )
            yield _iter_sse_events(r, path)

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        auth: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request("GET", path, params=params, auth=auth, timeout=timeout)

    # dup-ok: typed per-verb wrapper; logic lives in _request, the repeated signature is the API contract
    def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        auth: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request("POST", path, params=params, json=json, auth=auth, timeout=timeout)

    # dup-ok: typed per-verb wrapper; logic lives in _request, the repeated signature is the API contract
    def put(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        auth: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request("PUT", path, params=params, json=json, auth=auth, timeout=timeout)

    # dup-ok: typed per-verb wrapper; logic lives in _request, the repeated signature is the API contract
    def patch(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        auth: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request("PATCH", path, params=params, json=json, auth=auth, timeout=timeout)

    def delete(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        auth: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        # delete() carries a json body: several LiteLLM delete endpoints
        # (organization delete, org member delete) take a required body.
        return self._request("DELETE", path, params=params, json=json, auth=auth, timeout=timeout)
