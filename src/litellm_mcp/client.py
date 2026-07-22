from __future__ import annotations

from json import JSONDecodeError
from typing import Any

import httpx

from .config import get_settings

_DEFAULT_TIMEOUT = 30.0


class APIError(Exception):
    def __init__(self, status: int, method: str, path: str, body: Any) -> None:
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"{method} {path} -> {status}: {body}")


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
