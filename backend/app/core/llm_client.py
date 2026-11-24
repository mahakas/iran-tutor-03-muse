"""The single LLM client wrapper.

Every LLM call in the project must go through this module so that the provider
and the models stay swappable through `.env` alone.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    UnprocessableEntityError,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_client: AsyncOpenAI | None = None
_embedding_client: AsyncOpenAI | None = None
_audio_client: AsyncOpenAI | None = None
_route_clients: dict[tuple[str, str], AsyncOpenAI] = {}
_semaphore: asyncio.Semaphore | None = None
# Models whose provider rejected `response_format=json_object`.
_json_mode_unsupported: set[str] = set()


@dataclass
class UsageAccumulator:
    """Thread/async-safe token usage collector for a single student API request."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(
        self,
        usage: dict[str, int | None] | None = None,
        *,
        fallback_prompt: int = 0,
        fallback_completion: int = 0,
    ) -> None:
        prompt = int((usage or {}).get("prompt_tokens") or 0)
        completion = int((usage or {}).get("completion_tokens") or 0)
        total = int((usage or {}).get("total_tokens") or 0)
        if prompt == 0 and completion == 0 and total == 0:
            prompt = max(0, fallback_prompt)
            completion = max(0, fallback_completion)
            total = prompt + completion
        elif total == 0:
            total = prompt + completion
        elif prompt == 0 and completion == 0:
            prompt = total
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total


_current_usage: ContextVar[UsageAccumulator | None] = ContextVar("llm_usage", default=None)


@contextmanager
def track_token_usage() -> Iterator[UsageAccumulator]:
    """Collect token usage across all LLM/vision/audio calls within this block."""
    accumulator = UsageAccumulator()
    token = _current_usage.set(accumulator)
    try:
        yield accumulator
    finally:
        _current_usage.reset(token)


def record_token_usage(
    usage: dict[str, int | None] | None = None,
    *,
    fallback_prompt: int = 0,
    fallback_completion: int = 0,
) -> None:
    acc = _current_usage.get()
    if acc is not None:
        acc.add(usage, fallback_prompt=fallback_prompt, fallback_completion=fallback_completion)


class InvalidJSONError(ValueError):
    """The model answered, but no JSON object could be extracted."""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,  # retries are handled here, in one place
        )
    return _client


def _get_route_client(base_url: str, api_key: str | None) -> AsyncOpenAI:
    """Client pinned to an admin-selected provider; never inherit another env key."""
    normalized_base = base_url.strip().rstrip("/")
    if not normalized_base:
        raise ValueError("provider base_url must not be empty")
    cache_key = (normalized_base, api_key or "")
    client = _route_clients.get(cache_key)
    if client is None:
        client = AsyncOpenAI(
            base_url=normalized_base,
            api_key=api_key or "no-auth",
            timeout=get_settings().llm_timeout,
            max_retries=0,
        )
        _route_clients[cache_key] = client
    return client


def _get_chat_client(base_url: str | None = None, api_key: str | None = None) -> AsyncOpenAI:
    return _get_route_client(base_url, api_key) if base_url else _get_client()


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().max_concurrency)
    return _semaphore


def _log(level: int, event: str, **fields: Any) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, ensure_ascii=False))


def _outermost_object(text: str) -> str | None:
    """Return the first balanced `{...}` block, ignoring braces inside strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    end = text.rfind("}")
    return text[start : end + 1] if end > start else None


def extract_json(text: str | None) -> dict[str, Any]:
    """Parse a JSON object out of a model reply.

    Tries, in order: the raw text, the content of a ``` / ```json fence, and the
    outermost brace-delimited block.
    """
    if not text or not text.strip():
        raise InvalidJSONError("empty model response")

    stripped = text.strip()
    candidates = [stripped]
    candidates.extend(match.strip() for match in _FENCE_RE.findall(stripped))
    block = _outermost_object(stripped)
    if block is not None:
        candidates.append(block)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise InvalidJSONError(f"no JSON object found in response: {stripped[:200]!r}")


def _usage_dict(usage: Any) -> dict[str, int | None]:
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, (APITimeoutError, APIConnectionError, InvalidJSONError)):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code == 429 or error.status_code >= 500
    return False


async def _complete(
    model: str,
    messages: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str | None, dict[str, int | None]]:
    """One JSON completion call against the selected provider."""
    client = _get_chat_client(base_url, api_key)
    cache_key = f"{base_url or 'env'}::{model}"
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
    if cache_key not in _json_mode_unsupported:
        try:
            response = await client.chat.completions.create(**request)
            return response.choices[0].message.content, _usage_dict(response.usage)
        except (BadRequestError, UnprocessableEntityError) as error:
            _json_mode_unsupported.add(cache_key)
            _log(
                logging.WARNING,
                "llm.json_mode_rejected",
                model=model,
                provider=base_url or "env",
                status=error.status_code,
                error=str(error)[:300],
            )
    request.pop("response_format", None)
    response = await client.chat.completions.create(**request)
    return response.choices[0].message.content, _usage_dict(response.usage)


def _demo_questions(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Deterministic exam fixtures used only by the explicitly enabled demo mode."""
    system_text = "\n".join(message.get("content", "") for message in messages)
    match = re.search(r"دقیقاً\s+(\d+)\s+سؤال", system_text)
    count = min(20, max(3, int(match.group(1)))) if match else 5
    questions = []
    for index in range(count):
        questions.append(
            {
                "prompt": f"[نمونهٔ نمایشی] کدام گزینه با محتوای صفحه‌های نمونه سازگار است؟ (سؤال {index + 1})",
                "choices": {
                    "A": "پاسخی که مستقیماً از منبع نمونه پشتیبانی می‌شود",
                    "B": "گزینهٔ نادرست نمونهٔ یک",
                    "C": "گزینهٔ نادرست نمونهٔ دو",
                    "D": "گزینهٔ نادرست نمونهٔ سه",
                },
                "correct_option": "A",
                "explanation": "در حالت نمایشی، کلید قطعی این سؤال ساختگی گزینهٔ A است؛ این داده محتوای آموزشی واقعی نیست.",
                "source_index": 0,
            }
        )
    return {"questions": questions}


async def complete_json(
    model: str,
    messages: list[dict[str, str]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Request structured JSON through the shared LLM wrapper with retries."""
    if get_settings().demo_mode:
        demo = _demo_questions(messages)
        count = len(demo.get("questions", []))
        record_token_usage(fallback_prompt=220, fallback_completion=max(160, count * 160))
        return demo
    for attempt in range(MAX_RETRIES + 1):
        try:
            json_messages = list(messages)
            guard = {"role": "system", "content": "Return only one valid JSON object."}
            json_messages.insert(1 if json_messages and json_messages[0]["role"] == "system" else 0, guard)
            async with _get_semaphore():
                content, _usage = await _complete(model, json_messages, base_url=base_url, api_key=api_key, max_tokens=max_tokens)
            parsed = extract_json(content)
            prompt_est = max(50, sum(len(str(m.get("content", ""))) for m in json_messages) // 4)
            completion_est = max(50, len(content or "") // 4)
            record_token_usage(_usage, fallback_prompt=prompt_est, fallback_completion=completion_est)
            return parsed
        except Exception as error:  # noqa: BLE001 - classified below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.complete_json.failed",
                    model=model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.complete_json.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def _get_embedding_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        settings = get_settings()
        _embedding_client = AsyncOpenAI(
            base_url=settings.embedding_base_url or settings.llm_base_url,
            api_key=settings.embedding_api_key or settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,
        )
    return _embedding_client


async def embed_texts(
    texts: list[str],
    model: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> list[list[float]]:
    """Create vectors through the configured OpenAI-compatible embedding API."""
    if not texts:
        return []
    settings = get_settings()
    embedding_model = model or settings.embedding_model
    if settings.demo_mode:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * settings.embedding_dimension
            for token in re.findall(r"[\w۰-۹]+", text.casefold()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % settings.embedding_dimension
                vector[index] += 1.0 if digest[4] & 1 else -1.0
            magnitude = sum(value * value for value in vector) ** 0.5
            vectors.append([value / magnitude for value in vector] if magnitude else vector)
        return vectors
    client = _get_route_client(base_url, api_key) if base_url else _get_embedding_client()

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with _get_semaphore():
                response = await client.embeddings.create(model=embedding_model, input=texts)
            vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
            if len(vectors) != len(texts):
                raise ValueError("embedding response count does not match input count")
            for vector in vectors:
                if len(vector) != settings.embedding_dimension:
                    raise ValueError(
                        f"embedding dimension mismatch: expected {settings.embedding_dimension}, "
                        f"received {len(vector)}"
                    )
            return vectors
        except Exception as error:  # noqa: BLE001 - classified below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.embed_texts.failed",
                    model=embedding_model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.embed_texts.retry",
                model=embedding_model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


async def complete_text(
    model: str,
    messages: list[dict[str, str]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """Create a plain-text chat completion through the shared provider client."""
    if get_settings().demo_mode:
        prompt = messages[-1].get("content", "") if messages else ""
        if "شیب" in prompt and "نمودار" in prompt:
            reply = (
                "**حالت نمایشی:** شیب نمودار مکان ـ زمان، سرعت را نشان می‌دهد. "
                "برای محاسبه، تغییر مکان را بر تغییر زمان تقسیم می‌کنیم. "
                "این پاسخ ثابتِ نمونه است و خروجی مدل هوش مصنوعی واقعی نیست."
            )
        elif "شتاب" in prompt:
            reply = (
                "**حالت نمایشی:** شتاب متوسط برابر تغییر سرعت تقسیم بر بازهٔ زمانی است. "
                "این پاسخ ثابتِ نمونه است و خروجی مدل هوش مصنوعی واقعی نیست."
            )
        elif "طراحی" in prompt or "سؤال" in prompt:
            reply = (
                "**حالت نمایشی:** درخواست به بک‌اند رسیده و پاسخ‌گویی مدل غیرفعال است. "
                "برای پاسخ آموزشی واقعی، از تنظیمات provider استفاده کنید."
            )
        else:
            reply = (
                "**حالت نمایشی:** درخواست به بک‌اند رسیده و صفحات نمونهٔ کتاب بازیابی شدند. "
                "این خروجی ثابت است؛ برای استفادهٔ آموزشی واقعی باید مدل زبانی را پیکربندی کنید."
            )
        prompt_est = max(80, sum(len(str(m.get("content", ""))) for m in messages) // 4)
        completion_est = max(60, len(reply) // 4)
        record_token_usage(fallback_prompt=prompt_est, fallback_completion=completion_est)
        return reply
    client = _get_chat_client(base_url, api_key)
    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        try:
            async with _get_semaphore():
                request: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if max_tokens is not None:
                    request["max_tokens"] = max_tokens
                response = await client.chat.completions.create(**request)
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise InvalidJSONError("empty model response")
            usage = _usage_dict(response.usage)
            prompt_est = max(50, sum(len(str(m.get("content", ""))) for m in messages) // 4)
            completion_est = max(20, len(content.strip()) // 4)
            record_token_usage(usage, fallback_prompt=prompt_est, fallback_completion=completion_est)
            _log(
                logging.INFO,
                "llm.complete_text.ok",
                model=model,
                latency_s=round(time.perf_counter() - started, 2),
                **usage,
            )
            return content.strip()
        except Exception as error:  # noqa: BLE001 - classified below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.complete_text.failed",
                    model=model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.complete_text.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


async def stream_text(
    model: str,
    messages: list[dict[str, Any]],
    on_chunk: Callable[[str], Awaitable[None]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """Stream a plain-text chat completion while preserving the shared client policy.

    Retries are permitted only before the first visible chunk. Retrying after a
    partial response would duplicate text in clients that are already rendering it.
    """
    if get_settings().demo_mode:
        content = await complete_text(model, messages)
        for start in range(0, len(content), 40):
            await on_chunk(content[start : start + 40])
        return content

    client = _get_chat_client(base_url, api_key)
    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        emitted = False
        stream = None
        try:
            parts: list[str] = []
            async with _get_semaphore():
                request: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                }
                if max_tokens is not None:
                    request["max_tokens"] = max_tokens
                stream = await client.chat.completions.create(**request)
                async for event in stream:
                    choices = getattr(event, "choices", None) or []
                    for choice in choices:
                        delta = getattr(getattr(choice, "delta", None), "content", None)
                        if not isinstance(delta, str) or not delta:
                            continue
                        parts.append(delta)
                        emitted = True
                        await on_chunk(delta)

            content = "".join(parts).strip()
            if not content:
                raise InvalidJSONError("empty model response")
            prompt_est = max(50, sum(len(str(m.get("content", ""))) for m in messages) // 4)
            completion_est = max(20, len(content) // 4)
            record_token_usage(fallback_prompt=prompt_est, fallback_completion=completion_est)
            _log(
                logging.INFO,
                "llm.stream_text.ok",
                model=model,
                latency_s=round(time.perf_counter() - started, 2),
                chunks=len(parts),
            )
            return content
        except Exception as error:  # noqa: BLE001 - classified below
            if emitted or not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.stream_text.failed",
                    model=model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                    emitted=emitted,
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.stream_text.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)
        finally:
            if stream is not None:
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        await close()
                    except Exception:  # noqa: BLE001 - preserve the primary result/error
                        logger.debug("llm.stream_text.close_failed", exc_info=True)

    raise RuntimeError("unreachable")  # pragma: no cover


def _get_audio_client() -> AsyncOpenAI:
    global _audio_client
    if _audio_client is None:
        settings = get_settings()
        _audio_client = AsyncOpenAI(
            base_url=settings.audio_base_url or settings.llm_base_url,
            api_key=settings.audio_api_key or settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,
        )
    return _audio_client


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str,
    content_type: str,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Transcribe Persian audio through a configurable OpenAI-compatible API."""
    settings = get_settings()
    if not audio_bytes:
        raise ValueError("audio file is empty")
    if settings.demo_mode:
        record_token_usage(fallback_prompt=140, fallback_completion=40)
        return "شیب نمودار مکان ـ زمان چه مفهومی دارد؟ [رونوشت نمونه؛ نه تشخیص واقعی صدا]"
    transcription_model = model or settings.speech_to_text_model
    if not transcription_model:
        raise RuntimeError("SPEECH_TO_TEXT_MODEL must be configured for voice questions")

    client = _get_route_client(base_url, api_key) if base_url else _get_audio_client()
    async with _get_semaphore():
        response = await client.audio.transcriptions.create(
            model=transcription_model,
            file=(filename, audio_bytes, content_type),
            language="fa",
        )
    text = getattr(response, "text", "")
    if not text or not text.strip():
        raise ValueError("audio transcription returned no text")
    record_token_usage(fallback_prompt=max(100, len(audio_bytes) // 1024 * 12), fallback_completion=max(20, len(text) // 4))
    _log(logging.INFO, "llm.transcribe_audio.ok", model=transcription_model)
    return text.strip()


_speech_clients: dict[tuple[str, str], AsyncOpenAI] = {}


def _demo_wav(seconds: float = 0.5, rate: int = 8000) -> bytes:
    """A tiny silent WAV used in demo mode (valid audio, no provider call)."""
    import struct

    samples = int(seconds * rate)
    data = b"\x00\x00" * samples
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(data)) + data


async def synthesize_speech(
    text: str,
    *,
    voice: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> bytes:
    """Text-to-speech through an OpenAI-compatible audio API (admin-routed provider).

    `base_url` / `api_key` come from the admin's resolved `audio_tts` route; when absent
    the `.env` audio client is used. Returns raw audio bytes (mp3 from providers).
    """
    settings = get_settings()
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("speech text is empty")
    if settings.demo_mode:
        record_token_usage(fallback_prompt=max(1, len(cleaned) // 4), fallback_completion=0)
        return _demo_wav()
    if not model:
        raise RuntimeError("audio_tts route has no model configured")
    if base_url:
        key = (base_url, api_key or "")
        client = _speech_clients.get(key)
        if client is None:
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key or "no-auth",
                timeout=settings.llm_timeout,
                max_retries=0,
            )
            _speech_clients[key] = client
    else:
        client = _get_audio_client()
    async with _get_semaphore():
        response = await client.audio.speech.create(
            model=model, voice=voice, input=cleaned[:4000], response_format="mp3"
        )
    audio = getattr(response, "content", b"") or b""
    if not audio:
        raise ValueError("speech provider returned no audio")
    record_token_usage(fallback_prompt=max(1, len(cleaned) // 4), fallback_completion=0)
    _log(logging.INFO, "llm.synthesize_speech.ok", model=model, bytes=len(audio))
    return audio


async def close_llm_clients() -> None:
    """Dispose provider HTTP clients and reset semaphore/capability caches."""
    global _client, _embedding_client, _audio_client, _semaphore
    clients = (_client, _embedding_client, _audio_client, *_speech_clients.values(), *_route_clients.values())
    _speech_clients.clear()
    _route_clients.clear()
    _client = None
    _embedding_client = None
    _audio_client = None
    _semaphore = None
    _json_mode_unsupported.clear()
    for client in clients:
        if client is not None:
            await client.close()


async def vision_json(
    model: str,
    system_prompt: str,
    user_text: str,
    image_png_bytes: bytes,
    image_mime_type: str = "image/png",
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, int | None]]:
    """Send one PNG plus text to a vision model and return `(parsed_dict, usage)`.

    Retries up to `MAX_RETRIES` times with exponential backoff on 429, 5xx,
    timeouts, connection errors and replies that contain no valid JSON object.
    """
    if get_settings().demo_mode:
        if "printed_page_number" in system_prompt and "markdown_content" in system_prompt:
            return (
                {
                    "printed_page_number": None,
                    "chapter_number": None,
                    "chapter_title": None,
                    "markdown_content": "حالت نمایشی: محتوای این صفحه با OCR واقعی استخراج نشده است؛ بازبینی انسانی الزامی است.",
                    "visual_elements": [],
                },
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )
        demo_usage = {"prompt_tokens": 250, "completion_tokens": 110, "total_tokens": 360}
        record_token_usage(demo_usage)
        return (
            {
                "question_text": "نمودار مکان ـ زمان چه مفهومی دارد؟ [صورت سؤال ثابت نمایشی؛ تصویر واقعاً خوانده نشده]",
                "visual_description": "تصویر در حالت نمایشی تحلیل نمی‌شود.",
                "uncertain_parts": ["تشخیص بینایی واقعی در حالت نمایشی غیرفعال است"],
            },
            demo_usage,
        )
    image_b64 = base64.b64encode(image_png_bytes).decode("ascii")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime_type};base64,{image_b64}"},
                },
            ],
        },
    ]

    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        try:
            async with _get_semaphore():
                content, usage = await _complete(model, messages, base_url=base_url, api_key=api_key, max_tokens=max_tokens)
            parsed = extract_json(content)
        except Exception as error:  # noqa: BLE001 - classified just below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.vision_json.failed",
                    model=model,
                    attempt=attempt + 1,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.vision_json.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
                error=str(error)[:300],
            )
            await asyncio.sleep(delay)
            continue

        _log(
            logging.INFO,
            "llm.vision_json.ok",
            model=model,
            attempt=attempt + 1,
            latency_s=round(time.perf_counter() - started, 2),
            json_mode=model not in _json_mode_unsupported,
            **usage,
        )
        record_token_usage(usage, fallback_prompt=250, fallback_completion=max(60, len(json.dumps(parsed)) // 4))
        return parsed, usage

    raise RuntimeError("unreachable")  # pragma: no cover
