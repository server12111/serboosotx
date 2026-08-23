"""
icheatbot.com SMM reseller API client.
API: https://icheatbot.com/api/v2
Auth: `key` field in the POST body.
Docs describe standard "SMM Panel API v2" semantics (services/add/status/balance/refill/cancel).
The exact bulk-status parameter name is unconfirmed until tested against a real key —
status_bulk() is the primary path; if the upstream doesn't support it, callers should
fall back to sequential per-order status() calls (see order_poller.py).
"""
import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

import aiohttp

logger = logging.getLogger("boosty.icheatbot")


class IcheatbotError(Exception):
    pass


class IcheatbotClient:
    def __init__(self, api_key: str, base_url: str):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def _call(self, action: str, **params: Any) -> Any:
        body = {"key": self._api_key, "action": action, **params}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._base_url, data=body, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    raw_text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise IcheatbotError(f"network error calling {action}: {e}") from e

        try:
            data = json.loads(raw_text) if raw_text else None
        except json.JSONDecodeError as e:
            # Real-world confirmed case: `cancel` on some services returns a non-JSON
            # (often empty) body instead of an error object — surface it as a clean
            # IcheatbotError instead of letting a raw JSONDecodeError crash the caller.
            raise IcheatbotError(
                f"upstream returned non-JSON response for {action}: {raw_text[:200]!r}"
            ) from e

        if isinstance(data, dict) and "error" in data:
            raise IcheatbotError(str(data["error"]))
        return data

    async def services(self) -> list[dict[str, Any]]:
        data = await self._call("services")
        if not isinstance(data, list):
            raise IcheatbotError(f"unexpected services response: {data!r}")
        return data

    async def add(
        self,
        service_id: str,
        link: str,
        quantity: int,
        runs: int | None = None,
        interval: int | None = None,
    ) -> str:
        params: dict[str, Any] = {"service": service_id, "link": link, "quantity": quantity}
        if runs is not None:
            params["runs"] = runs
        if interval is not None:
            params["interval"] = interval
        data = await self._call("add", **params)
        order_id = data.get("order") if isinstance(data, dict) else None
        if order_id is None:
            raise IcheatbotError(f"add response missing order id: {data!r}")
        return str(order_id)

    async def status(self, external_order_id: str) -> dict[str, Any]:
        return await self._call("status", order=external_order_id)

    async def status_bulk(self, external_order_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Returns {external_order_id: status_dict}. Raises IcheatbotError if the upstream
        doesn't support bulk status so callers can fall back to sequential calls."""
        data = await self._call("status", orders=",".join(external_order_ids))
        if not isinstance(data, dict):
            raise IcheatbotError("bulk status not supported by upstream (unexpected shape)")
        return data

    async def status_sequential(
        self, external_order_ids: list[str], concurrency: int = 10
    ) -> dict[str, dict[str, Any]]:
        semaphore = asyncio.Semaphore(concurrency)
        results: dict[str, dict[str, Any]] = {}

        async def fetch(order_id: str) -> None:
            async with semaphore:
                try:
                    results[order_id] = await self.status(order_id)
                except IcheatbotError as e:
                    logger.warning("status() failed for order %s: %s", order_id, e)

        await asyncio.gather(*(fetch(oid) for oid in external_order_ids))
        return results

    async def balance(self) -> tuple[Decimal, str]:
        data = await self._call("balance")
        return Decimal(str(data["balance"])), data.get("currency", "RUB")

    async def refill(self, external_order_id: str) -> str | None:
        data = await self._call("refill", order=external_order_id)
        return str(data.get("refill")) if isinstance(data, dict) and data.get("refill") else None

    async def cancel(self, external_order_id: str) -> bool:
        data = await self._call("cancel", order=external_order_id)
        return bool(data)
