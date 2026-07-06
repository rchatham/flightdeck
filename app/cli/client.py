"""Thin synchronous httpx wrapper used by CLI commands to talk to the FlightDeck API."""
from __future__ import annotations

import sys

import httpx
from rich.console import Console

from app.config import get_settings

err_console = Console(stderr=True, style="red")


class APIClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or get_settings().api_base_url).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self._client.get(path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self._client.post(path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self._client.put(path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self._client.delete(path, **kwargs)

    def close(self) -> None:
        self._client.close()


def fail(message: str, exit_code: int = 1) -> None:
    err_console.print(f"[bold red]error:[/bold red] {message}")
    sys.exit(exit_code)


def safe_json(resp: httpx.Response) -> dict:
    """Parse a response as JSON or fail with the body text."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        fail(f"{e.response.status_code} {e.response.reason_phrase}: {e.response.text}")
    try:
        return resp.json()
    except ValueError:
        fail(f"non-JSON response from API: {resp.text[:200]}")
        return {}  # unreachable
