import asyncio
import hashlib
import hmac
from typing import Any, Optional

import requests

from app.core.config import settings

PAYSTACK_API_BASE = "https://api.paystack.co"


def _require_secret_key() -> str:
    secret_key = settings.paystack_secret_key.strip()
    if not secret_key:
        raise ValueError("Paystack secret key is not configured.")
    return secret_key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_require_secret_key()}",
        "Content-Type": "application/json",
    }


def _post_initialize(payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{PAYSTACK_API_BASE}/transaction/initialize",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("status"):
        raise ValueError(data.get("message") or "Unable to initialize Paystack transaction.")
    return data["data"]


def _get_verify(reference: str) -> dict[str, Any]:
    response = requests.get(
        f"{PAYSTACK_API_BASE}/transaction/verify/{reference}",
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("status"):
        raise ValueError(data.get("message") or "Unable to verify Paystack transaction.")
    return data["data"]


async def initialize_paystack_transaction(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_post_initialize, payload)


async def verify_paystack_transaction(reference: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_verify, reference)


def verify_paystack_signature(raw_body: bytes, signature: Optional[str]) -> bool:
    if not signature:
        return False
    secret_key = _require_secret_key()
    computed = hmac.new(secret_key.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)
