"""
CryptoBot (@CryptoBot) payment integration.
API: https://pay.crypt.bot/api
Auth: Crypto-Pay-API-Token header
Docs: https://help.crypt.bot/crypto-pay-api

Asset is fixed to USDT (operator's choice — no asset-selection screen in our bot).
The RUB amount to credit is locked in at invoice-creation time
(amount_rub_locked, stored on the invoice row) and never recomputed from a live
exchange rate when the invoice is later marked paid — see invoice_reconciler.py.

A processing-fee surcharge is added on top of the amount actually credited: the payer
covers CRYPTOBOT_FEE_PERCENT, but the RUB amount locked in (what gets credited once
paid) is always the pre-fee amount they asked for.

CryptoBot rejects invoices below its own minimum — empirically confirmed against the
live API: 0.01 USDT is rejected (AMOUNT_TOO_SMALL), 0.011 and above succeed. MIN_TOPUP_USDT
below is set with headroom above that observed edge rather than resting exactly on it.
"""
import json
import logging
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Optional

import aiohttp

logger = logging.getLogger("boosty.cryptobot")

BASE_URL = "https://pay.crypt.bot/api"
CRYPTOBOT_FEE_PERCENT = Decimal("3")
ASSET = "USDT"
MIN_TOPUP_USDT = Decimal("0.05")
INVOICE_EXPIRES_MINUTES = 10


class CryptoBotError(Exception):
    pass


def _headers(token: str) -> dict:
    return {"Crypto-Pay-API-Token": token, "Content-Type": "application/json"}


async def _read_json(resp: aiohttp.ClientResponse) -> dict:
    """CryptoBot can return a non-JSON body during an outage/rate-limit (e.g. an HTML
    error page) — parse defensively instead of letting resp.json() raise a raw
    JSONDecodeError, mirroring the same fix applied to icheatbot.py's client."""
    raw_text = await resp.text()
    try:
        return json.loads(raw_text) if raw_text else {}
    except json.JSONDecodeError as e:
        raise CryptoBotError(f"non-JSON response from CryptoBot: {raw_text[:200]!r}") from e


def amount_with_fee(amount_rub: Decimal) -> Decimal:
    return (amount_rub * (Decimal(1) + CRYPTOBOT_FEE_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def get_exchange_rate(token: str, asset: str = ASSET, target: str = "RUB") -> Decimal:
    """Returns how many `target` units one `asset` unit is worth."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/getExchangeRates",
            headers=_headers(token),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await _read_json(resp)
    if not data.get("ok"):
        raise CryptoBotError(f"getExchangeRates failed: {data}")
    for rate in data["result"]:
        if rate.get("source") == asset and rate.get("target") == target and rate.get("is_valid"):
            return Decimal(str(rate["rate"]))
    raise CryptoBotError(f"no exchange rate found for {asset}->{target}")


async def get_min_topup_rub(token: str) -> Decimal:
    """CryptoBot's real minimum invoice size, converted to RUB at the current rate —
    this is what should actually gate top-up amounts, not an arbitrary business
    minimum. Falls back to a small hardcoded RUB floor if the rate call fails, so a
    transient API hiccup can't block top-ups entirely."""
    try:
        rate = await get_exchange_rate(token)
        return (MIN_TOPUP_USDT * rate).quantize(Decimal("0.01"), rounding=ROUND_UP)
    except (CryptoBotError, aiohttp.ClientError) as e:
        logger.warning("could not fetch exchange rate for min top-up, using fallback: %s", e)
        return Decimal("5.00")


async def create_invoice(
    token: str,
    amount_rub: Decimal,
    description: str = "Пополнение баланса",
    payload: str = "",
    expires_in: int = INVOICE_EXPIRES_MINUTES * 60,
) -> Optional[dict]:
    """Creates a USDT-denominated CryptoBot invoice worth amount_rub plus the
    processing fee, converted at the current exchange rate. The RUB amount itself (not
    the crypto amount) is what the caller should lock into
    cryptobot_invoices.amount_rub_locked."""
    if not token:
        logger.warning("CryptoBot token not configured")
        return None

    try:
        rate = await get_exchange_rate(token)
        total_rub = amount_with_fee(amount_rub)
        crypto_amount = (total_rub / rate).quantize(Decimal("0.01"), rounding=ROUND_UP)

        body = {
            "asset": ASSET,
            "amount": str(crypto_amount),
            "description": description,
            "payload": payload,
            "expires_in": expires_in,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/createInvoice",
                json=body,
                headers=_headers(token),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await _read_json(resp)
        if not (data.get("ok") and data.get("result")):
            logger.error("CryptoBot createInvoice error: %s", data)
            return None
        result = data["result"]
        pay_url = result.get("bot_invoice_url") or result.get("mini_app_invoice_url") or result.get("pay_url")
        if not pay_url:
            logger.error("CryptoBot response has no invoice URL: %s", result)
            return None
        return {
            "invoice_id": result["invoice_id"],
            "pay_url": pay_url,
            "asset": ASSET,
            "amount_crypto": crypto_amount,
        }
    except (CryptoBotError, aiohttp.ClientError) as e:
        logger.error("CryptoBot createInvoice exception: %s", e)
        return None


async def get_invoices(token: str, invoice_ids: list[int]) -> list[dict]:
    """Batched status check — used by invoice_reconciler.py's periodic sweep instead of
    per-request polling."""
    if not token or not invoice_ids:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/getInvoices",
                json={"invoice_ids": ",".join(str(i) for i in invoice_ids)},
                headers=_headers(token),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await _read_json(resp)
        result = data.get("result")
        if isinstance(result, dict):
            return result.get("items", [])
        if isinstance(result, list):
            return result
        return []
    except (CryptoBotError, aiohttp.ClientError) as e:
        logger.error("CryptoBot getInvoices exception: %s", e)
        return []
