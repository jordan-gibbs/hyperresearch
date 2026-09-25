"""AnySearch REST provider: anonymous/keyed search, verticals, and extraction.

Set ``[web] provider = "anysearch"`` to use it for research and fetch. The
optional ANYSEARCH_API_KEY environment variable enables authenticated usage.
No SDK or extra dependency is needed; requests use the core httpx dependency.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeGuard
from urllib.parse import urlsplit

import httpx

from hyperresearch.core.config import FetchSettings, JunkGates
from hyperresearch.web.base import WebResult

_API_URL = "https://api.anysearch.com"


class AnySearchProvider:
    """Native WebProvider plus capability discovery and ordered batch search.

    ``api_key=None`` reads the environment; ``api_key=""`` explicitly selects
    anonymous access. A failed authenticated call is never retried anonymously.
    Clients are request-scoped, so sync callers and concurrent batches do not
    need to manage an open connection pool.
    """

    name = "anysearch"

    def __init__(
        self,
        api_key: str | None = None,
        settings: FetchSettings | None = None,
        transport: httpx.BaseTransport | None = None,
        *,
        fetch_content: bool = True,
        max_characters: int = 8000,
        gates: JunkGates | None = None,
    ) -> None:
        if type(max_characters) is not int or max_characters <= 0:
            raise ValueError("max_characters must be a positive integer")
        self._key = (os.environ.get("ANYSEARCH_API_KEY", "") if api_key is None else api_key).strip()
        self._timeout = (settings or FetchSettings()).page_timeout_ms / 1000
        self._transport = transport
        self._fetch_content = fetch_content
        self._max_characters = max_characters
        self._gates = gates or JunkGates()

    def search(
        self,
        query: str,
        max_results: int = 5,
        *,
        tag: str | None = None,
        params: dict[str, Any] | None = None,
        zone: str | None = None,
        language: str | None = None,
    ) -> list[WebResult]:
        """Search the web; discover tags/required params with get_sub_domains first.

        Extract page text by default, retaining the search excerpt when the
        page cannot be fetched or trips the existing content-quality gates.
        Set fetch_content=False for discovery without extra Extract requests.
        """
        payload = _search_payload(query, max_results, tag=tag, params=params, zone=zone, language=language)
        return self._search(payload)

    def _search(self, payload: dict[str, Any]) -> list[WebResult]:
        data, request_id = self._request("POST", "/v1/search", payload=payload)
        items = data.get("results")
        if not isinstance(items, list):
            raise RuntimeError("AnySearch search response is missing a results list")
        results = []
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError("AnySearch returned a malformed search result")
            if not item.get("url"):
                continue  # Unlinked answers cannot be stored as cited sources.
            result = _to_web_result(item, request_id)
            if isinstance(data.get("metadata"), dict):
                result.metadata["anysearch_metadata"] = dict(data["metadata"])
            if self._fetch_content:
                try:
                    fetched = self.fetch(result.url)
                except RuntimeError:
                    fetched = None
                if (
                    fetched is not None
                    and fetched.looks_like_junk(self._gates) is None
                    and not fetched.looks_like_login_wall(result.url, self._gates)
                ):
                    result.content = fetched.content
            results.append(result)
            if len(results) == payload["max_results"]:
                break
        return results

    def fetch(self, url: str) -> WebResult:
        """Extract a web page as Markdown. Binary formats (including PDF) are unsupported."""
        if not _is_web_url(url):
            raise ValueError("AnySearch extract requires an HTTP(S) URL without credentials")
        data, request_id = self._request("POST", "/v1/extract", payload={"url": url})
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"AnySearch returned no extracted content for {url}")
        return _to_web_result(
            {
                **data,
                "url": data.get("url") or url,
                "requested_url": url,
                "content": content[: self._max_characters],
            },
            request_id,
        )

    def get_sub_domains(self, domains: list[str]) -> list[dict[str, Any]]:
        """Discover current capability tags and required parameters for 1-5 domains."""
        if not isinstance(domains, list) or not 1 <= len(domains) <= 5:
            raise ValueError("Provide between 1 and 5 domains")
        if any(not isinstance(d, str) or not d.strip() for d in domains):
            raise ValueError("Domain names must be nonempty strings")
        data, _ = self._request(
            "GET", "/v1/sub-domains", params=tuple(("domain", d.strip()) for d in domains),
        )
        entries = data.get("domains")
        if not isinstance(entries, list) or any(not isinstance(d, dict) for d in entries):
            raise RuntimeError("AnySearch capability response is missing a domains list")
        return entries

    def batch_search(self, queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run 1-5 independent queries concurrently, retaining order and per-item errors.

        Query objects use the same arguments as search(). Invalid input is
        rejected before any requests; service failures affect only their item.
        """
        if not isinstance(queries, list) or not 1 <= len(queries) <= 5:
            raise ValueError("Provide between 1 and 5 query objects")
        payloads = []
        for query in queries:
            if not isinstance(query, dict):
                raise ValueError("Each query must be an object")
            try:
                payloads.append(_search_payload(**query))
            except TypeError as exc:
                raise ValueError(f"Invalid AnySearch query fields: {exc}") from exc

        def run(payload: dict[str, Any]) -> dict[str, Any]:
            try:
                return {"query": payload["query"], "results": self._search(payload)}
            except RuntimeError as exc:
                return {"query": payload["query"], "results": [], "error": str(exc)}

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            return list(pool.map(run, payloads))

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: tuple[tuple[str, str], ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        headers = {"X-Anysearch-Client": "hyperresearch", "Accept": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        try:
            with httpx.Client(
                headers=headers, timeout=self._timeout, transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.request(method, _API_URL + path, json=payload, params=params)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"AnySearch {path} request timed out") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"AnySearch {path} connection failed ({type(exc).__name__})") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"AnySearch returned invalid JSON (HTTP {response.status_code})") from exc
        if not isinstance(body, dict):
            raise RuntimeError("AnySearch returned a non-object response")
        request_id = str(body.get("request_id") or "")
        if not response.is_success or body.get("code", 0) != 0:
            message = str(body.get("message") or "request failed")[:500]
            if self._key:
                message = message.replace(self._key, "[redacted]")
            detail = f"; request_id: {request_id}" if request_id else ""
            raise RuntimeError(f"AnySearch: {message} (HTTP {response.status_code}{detail})")
        data = body.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("AnySearch response is missing a data object")
        return data, request_id


def _search_payload(
    query: str,
    max_results: int = 5,
    *,
    tag: str | None = None,
    params: dict[str, Any] | None = None,
    zone: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must be a nonempty string")
    if type(max_results) is not int or not 1 <= max_results <= 10:
        raise ValueError("max_results must be an integer between 1 and 10")
    payload: dict[str, Any] = {"query": query.strip(), "max_results": max_results}
    if tag is not None:
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError("tag must be a nonempty capability from sub-domains")
        payload["tag"] = tag.strip()
    if params is not None:
        if not isinstance(params, dict) or not tag:
            raise ValueError("params must be an object and require a capability tag")
        payload["params"] = params
    if zone is not None:
        if zone not in ("cn", "intl"):
            raise ValueError("zone must be cn or intl")
        payload["zone"] = zone
    if language is not None:
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language must be a nonempty string")
        payload["language"] = language.strip()
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Search parameters must contain only finite JSON values") from exc
    return payload


def _is_web_url(value: Any) -> TypeGuard[str]:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme in ("https", "http") and parsed.hostname
            and parsed.username is None and parsed.password is None
        )
    except ValueError:
        return False


def _to_web_result(item: dict[str, Any], request_id: str) -> WebResult:
    url = item.get("url")
    title = item.get("title") or ""
    content = item.get("content") or item.get("snippet") or ""
    if not _is_web_url(url) or not isinstance(title, str) or not isinstance(content, str):
        raise RuntimeError("AnySearch returned a malformed URL, title, or content")
    metadata = {key: value for key, value in item.items() if key not in {"url", "title", "content", "snippet"}}
    if request_id:
        metadata["anysearch_request_id"] = request_id
    return WebResult(url=url, title=title, content=content, metadata=metadata)
