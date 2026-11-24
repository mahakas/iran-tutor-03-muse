"""Step 3 diagnostic: verify real LLM, Vision, Embeddings, DB, and Qdrant connectivity.

Every AI call goes through the Central AI Gateway (`app.services.ai_gateway`), the same
choke point production traffic uses, so this script also exercises routing + auditing.

Run from `backend/` after setting real provider credentials (`DEMO_MODE=false`):
    .venv/bin/python scripts/verify_ai_stack.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.llm_client import close_llm_clients  # noqa: E402
from app.services.ai_gateway import (  # noqa: E402
    CallContext,
    complete_json_via_gateway,
    complete_text_via_gateway,
    embed_via_gateway,
    vision_json_via_gateway,
)
from app.db.session import async_session_factory, engine  # noqa: E402
from app.services.retrieval_service import close_qdrant, ensure_collection  # noqa: E402
from scripts.test_llm import make_test_png  # noqa: E402


async def _check_database() -> bool:
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        print("[OK] Database connection succeeded")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Database connection: {type(exc).__name__}: {str(exc)[:250]}")
        return False


async def _check_vector_backend(backend: str) -> bool:
    try:
        await ensure_collection()
        print(f"[OK] Vector backend ({backend}) verified")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Vector backend ({backend}): {type(exc).__name__}: {str(exc)[:250]}")
        return False


async def _check_tutor_llm(model: str) -> bool:
    started = time.perf_counter()
    try:
        result = await complete_text_via_gateway(
            ctx=CallContext(feature_key="chat", textbook_strict=False),
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "تو معلم فیزیک هستی. به فارسی پاسخ کوتاه بده و فرمول را با $...$ بنویس.",
                },
                {
                    "role": "user",
                    "content": "فرمول سرعت متوسط را با یک مثال یک‌خطی به فارسی بنویس.",
                },
            ],
        )
        reply = result.content
        elapsed = time.perf_counter() - started
        has_persian = any("\u0600" <= ch <= "\u06ff" for ch in reply)
        has_katex = "$" in reply or "\\(" in reply or "\\[" in reply
        print(
            f"[OK] Tutor LLM ({model}) in {elapsed:.2f}s | persian={has_persian} | latex={has_katex}"
        )
        print(f"     sample: {reply[:180].replace(chr(10), ' ')}")
        return has_persian
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Tutor LLM ({model}): {type(exc).__name__}: {str(exc)[:250]}")
        return False


async def _check_json_llm(model: str) -> bool:
    started = time.perf_counter()
    try:
        result = await complete_json_via_gateway(
            ctx=CallContext(feature_key="quiz", textbook_strict=False),
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": 'Return JSON {"questions":[{"prompt":str,"choices":{"A":str,"B":str,"C":str,"D":str},"correct_option":"A","explanation":str,"source_index":0}]}',
                },
                {
                    "role": "user",
                    "content": "یک سؤال کوتاه دربارهٔ سرعت متوسط ($v_{av}=\\Delta x/\\Delta t$) بساز.",
                },
            ],
        )
        parsed = result.content
        elapsed = time.perf_counter() - started
        ok = isinstance(parsed.get("questions"), list) and len(parsed["questions"]) >= 1
        print(f"[{'OK' if ok else 'FAIL'}] Exam JSON ({model}) in {elapsed:.2f}s")
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Exam JSON ({model}): {type(exc).__name__}: {str(exc)[:250]}")
        return False


async def _check_vision(model: str, image_path: Path | None) -> bool:
    started = time.perf_counter()
    png = image_path.read_bytes() if image_path else make_test_png()
    try:
        result = await vision_json_via_gateway(
            ctx=CallContext(feature_key="vision_ocr", textbook_strict=False),
            model=model,
            system_prompt="You are a Persian textbook OCR engine. Return ONLY JSON with keys 'text' and 'formula'.",
            user_text="Read the Persian text and formula in this image.",
            image_bytes=png,
            image_mime_type="image/png",
        )
        parsed = result.content
        elapsed = time.perf_counter() - started
        usage = {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out}
        print(f"[OK] Vision ({model}) in {elapsed:.2f}s | usage={usage} | keys={list(parsed)}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Vision ({model}): {type(exc).__name__}: {str(exc)[:250]}")
        return False


async def _check_embeddings(model: str, expected_dim: int) -> bool:
    started = time.perf_counter()
    try:
        result = await embed_via_gateway(
            ctx=CallContext(feature_key="embedding", textbook_strict=False),
            texts=["شیب نمودار مکان زمان سرعت متوسط است."],
            model=model,
        )
        vectors = result.content
        elapsed = time.perf_counter() - started
        dim_ok = len(vectors) == 1 and len(vectors[0]) == expected_dim
        print(
            f"[{'OK' if dim_ok else 'FAIL'}] Embeddings ({model}) in {elapsed:.2f}s | dim={len(vectors[0]) if vectors else 0}"
        )
        return dim_ok
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Embeddings ({model}): {type(exc).__name__}: {str(exc)[:250]}")
        return False


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real AI provider stack (non-demo).")
    parser.add_argument("--image", type=Path, default=None, help="Optional PNG path for Vision OCR check")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ValidationError as exc:
        missing = ", ".join(str(item["loc"][0]).upper() for item in exc.errors())
        print(f"CONFIG ERROR: missing env vars in backend/.env: {missing}")
        return 2

    if settings.demo_mode:
        print(
            "ABORT: DEMO_MODE=true is active in backend/.env. Set DEMO_MODE=false and real API credentials to test live models."
        )
        return 2

    if not settings.tutor_model:
        print("CONFIG ERROR: TUTOR_MODEL must be set when DEMO_MODE=false")
        return 2

    try:
        checks = [
            await _check_database(),
            await _check_vector_backend(settings.vector_backend),
            await _check_tutor_llm(settings.tutor_model),
            await _check_json_llm(settings.tutor_model),
            await _check_vision(settings.vision_model_primary, args.image),
            await _check_embeddings(settings.embedding_model, settings.embedding_dimension),
        ]
    finally:
        await close_qdrant()
        await close_llm_clients()
        await engine.dispose()

    passed = sum(bool(item) for item in checks)
    print(f"\nSummary: {passed}/{len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(main()))
