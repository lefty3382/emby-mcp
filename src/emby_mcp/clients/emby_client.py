"""Async Emby REST API client."""

import aiohttp

from ..config import AppConfig


class EmbyClient:
    """Async HTTP client for the Emby REST API."""

    def __init__(self, config: AppConfig) -> None:
        self._base_url = config.emby_base_url
        self._api_key = config.emby_api_key
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        """Initialize the HTTP session."""
        self._session = aiohttp.ClientSession(
            base_url=self._base_url,
            headers={
                "X-Emby-Token": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def disconnect(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """GET request to the Emby API."""
        if not self._session:
            raise RuntimeError("Client not connected — call connect() first")
        async with self._session.get(endpoint, params=params) as resp:
            resp.raise_for_status()
            if resp.content_length == 0:
                return {}
            return await resp.json()

    async def post(
        self,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict | list:
        """POST request to the Emby API."""
        if not self._session:
            raise RuntimeError("Client not connected — call connect() first")
        async with self._session.post(endpoint, json=data, params=params) as resp:
            resp.raise_for_status()
            text = await resp.text()
            if not text:
                return {}
            return await resp.json()

    async def delete(self, endpoint: str, params: dict | None = None) -> dict:
        """DELETE request to the Emby API."""
        if not self._session:
            raise RuntimeError("Client not connected — call connect() first")
        async with self._session.delete(endpoint, params=params) as resp:
            resp.raise_for_status()
            text = await resp.text()
            if not text:
                return {}
            return await resp.json()
