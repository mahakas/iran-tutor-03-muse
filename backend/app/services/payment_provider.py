"""Abstract payment gateway interface and Zarinpal / Demo adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class PaymentInitResult:
    provider: str
    status: str  # "paid" (instant demo) or "redirect"
    authority: str
    payment_url: str | None = None
    ref_id: str | None = None


@dataclass(frozen=True)
class PaymentVerifyResult:
    paid: bool
    ref_id: str | None = None
    message: str | None = None


class PaymentProvider(ABC):
    """Abstract payment interface so Iran/abroad gateways stay swappable."""

    provider_name: str

    @abstractmethod
    async def create_payment(
        self,
        *,
        transaction_id: str,
        amount_toman: int,
        description: str,
        callback_url: str,
        mobile: str,
    ) -> PaymentInitResult:
        """Initiate a plan purchase and return payment URL or immediate demo completion."""

    @abstractmethod
    async def verify_payment(self, *, authority: str, amount_toman: int) -> PaymentVerifyResult:
        """Verify a previously initiated payment transaction."""


class DemoPaymentProvider(PaymentProvider):
    """Instant checkout adapter for demo/local verification without real money."""

    provider_name = "demo"

    async def create_payment(
        self,
        *,
        transaction_id: str,
        amount_toman: int,
        description: str,
        callback_url: str,
        mobile: str,
    ) -> PaymentInitResult:
        short = uuid4().hex[:10].upper()
        return PaymentInitResult(
            provider=self.provider_name,
            status="paid",
            authority=f"DEMO-{transaction_id[:8]}",
            payment_url=None,
            ref_id=f"DEMO-{short}",
        )

    async def verify_payment(self, *, authority: str, amount_toman: int) -> PaymentVerifyResult:
        return PaymentVerifyResult(paid=True, ref_id=f"VERIFIED-{authority}")


class ZarinpalPaymentProvider(PaymentProvider):
    """Zarinpal REST v4 gateway (supports IRT Toman directly)."""

    provider_name = "zarinpal"

    def __init__(self, *, merchant_id: str, sandbox: bool = False) -> None:
        if not merchant_id:
            raise RuntimeError("ZARINPAL_MERCHANT_ID is required for Zarinpal payments")
        self._merchant_id = merchant_id
        self._host = "https://sandbox.zarinpal.com" if sandbox else "https://payment.zarinpal.com"

    async def create_payment(
        self,
        *,
        transaction_id: str,
        amount_toman: int,
        description: str,
        callback_url: str,
        mobile: str,
    ) -> PaymentInitResult:
        url = f"{self._host}/pg/v4/payment/request.json"
        body = {
            "merchant_id": self._merchant_id,
            "amount": amount_toman,
            "currency": "IRT",
            "description": description,
            "callback_url": callback_url,
            "metadata": {"mobile": mobile, "order_id": transaction_id},
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") or {}
        authority = data.get("authority")
        if data.get("code") != 100 or not authority:
            raise RuntimeError(f"Zarinpal init failed: {payload.get('errors')}")
        return PaymentInitResult(
            provider=self.provider_name,
            status="redirect",
            authority=str(authority),
            payment_url=f"{self._host}/pg/StartPay/{authority}",
        )

    async def verify_payment(self, *, authority: str, amount_toman: int) -> PaymentVerifyResult:
        url = f"{self._host}/pg/v4/payment/verify.json"
        body = {
            "merchant_id": self._merchant_id,
            "amount": amount_toman,
            "authority": authority,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") or {}
        code = data.get("code")
        if code in {100, 101}:
            return PaymentVerifyResult(paid=True, ref_id=str(data.get("ref_id", "")))
        return PaymentVerifyResult(paid=False, message=str(payload.get("errors") or code))


def get_payment_provider(settings: Settings | None = None) -> PaymentProvider:
    cfg = settings or get_settings()
    if cfg.demo_mode or cfg.payment_provider == "demo":
        return DemoPaymentProvider()
    if cfg.payment_provider == "zarinpal":
        return ZarinpalPaymentProvider(
            merchant_id=cfg.zarinpal_merchant_id or "",
            sandbox=cfg.zarinpal_sandbox,
        )
    raise RuntimeError(f"Unsupported payment provider: {cfg.payment_provider}")
