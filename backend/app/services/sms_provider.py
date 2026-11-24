"""Abstract SMS OTP provider interface and Iranian gateway adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import logging

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmsDeliveryResult:
    provider: str
    delivered: bool
    message_id: str | None = None


class SmsProvider(ABC):
    """Abstract SMS delivery interface so hosting/providers stay swappable."""

    provider_name: str

    @abstractmethod
    async def send_otp(self, *, phone_number: str, code: str) -> SmsDeliveryResult:
        """Send a one-time verification code to an Iranian mobile number."""


class DemoSmsProvider(SmsProvider):
    """Local/demo provider that logs delivery without calling an external gateway."""

    provider_name = "demo"

    async def send_otp(self, *, phone_number: str, code: str) -> SmsDeliveryResult:
        masked = f"{phone_number[:4]}***{phone_number[-4:]}"
        logger.info(
            json.dumps(
                {"event": "sms.otp.demo", "phone": masked, "demo_mode": get_settings().demo_mode},
                ensure_ascii=False,
            )
        )
        return SmsDeliveryResult(provider=self.provider_name, delivered=True, message_id="demo")


class KavenegarSmsProvider(SmsProvider):
    """Kavenegar OTP adapter using verify/lookup or plain send."""

    provider_name = "kavenegar"

    def __init__(self, *, api_key: str, template: str | None = None, sender: str | None = None) -> None:
        if not api_key:
            raise RuntimeError("SMS_API_KEY is required for Kavenegar")
        self._api_key = api_key
        self._template = template
        self._sender = sender

    async def send_otp(self, *, phone_number: str, code: str) -> SmsDeliveryResult:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if self._template:
                url = f"https://api.kavenegar.com/v1/{self._api_key}/verify/lookup.json"
                data = {"receptor": phone_number, "token": code, "template": self._template}
            else:
                url = f"https://api.kavenegar.com/v1/{self._api_key}/sms/send.json"
                data = {
                    "receptor": phone_number,
                    "message": f"کد ورود شما به درسیار: {code}",
                }
                if self._sender:
                    data["sender"] = self._sender
            response = await client.post(url, data=data)
            response.raise_for_status()
            payload = response.json()
        return SmsDeliveryResult(
            provider=self.provider_name,
            delivered=True,
            message_id=str(payload.get("entries", [{}])[0].get("messageid", "")) or None,
        )


class SmsIrSmsProvider(SmsProvider):
    """SMS.ir v1 verify adapter."""

    provider_name = "sms_ir"

    def __init__(self, *, api_key: str, template_id: str) -> None:
        if not api_key or not template_id:
            raise RuntimeError("SMS_API_KEY and SMS_TEMPLATE are required for SMS.ir")
        self._api_key = api_key
        self._template_id = int(template_id)

    async def send_otp(self, *, phone_number: str, code: str) -> SmsDeliveryResult:
        url = "https://api.sms.ir/v1/send/verify"
        headers = {"x-api-key": self._api_key, "Content-Type": "application/json"}
        body = {
            "mobile": phone_number,
            "templateId": self._template_id,
            "parameters": [{"name": "CODE", "value": code}],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != 1:
            raise RuntimeError(f"SMS.ir rejected OTP delivery: {payload.get('message')}")
        return SmsDeliveryResult(
            provider=self.provider_name,
            delivered=True,
            message_id=str((payload.get("data") or {}).get("messageId", "")) or None,
        )


class WebhookSmsProvider(SmsProvider):
    """Generic HTTP webhook adapter for split Iran/abroad SMS relay services."""

    provider_name = "webhook"

    def __init__(self, *, webhook_url: str, api_key: str | None = None) -> None:
        if not webhook_url:
            raise RuntimeError("SMS_WEBHOOK_URL is required for webhook SMS provider")
        self._webhook_url = webhook_url
        self._api_key = api_key

    async def send_otp(self, *, phone_number: str, code: str) -> SmsDeliveryResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "phone_number": phone_number,
            "code": code,
            "message": f"کد تایید درسیار: {code}",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self._webhook_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json() if response.content else {}
        return SmsDeliveryResult(
            provider=self.provider_name,
            delivered=True,
            message_id=str(data.get("message_id", "")) or None,
        )


def get_sms_provider(settings: Settings | None = None) -> SmsProvider:
    cfg = settings or get_settings()
    if cfg.demo_mode or cfg.sms_provider == "demo":
        return DemoSmsProvider()
    if cfg.sms_provider == "kavenegar":
        return KavenegarSmsProvider(
            api_key=cfg.sms_api_key or "",
            template=cfg.sms_template,
            sender=cfg.sms_sender,
        )
    if cfg.sms_provider == "sms_ir":
        return SmsIrSmsProvider(
            api_key=cfg.sms_api_key or "",
            template_id=cfg.sms_template or "",
        )
    if cfg.sms_provider == "webhook":
        return WebhookSmsProvider(
            webhook_url=cfg.sms_webhook_url or "",
            api_key=cfg.sms_api_key,
        )
    raise RuntimeError(f"Unsupported SMS provider: {cfg.sms_provider}")
