"""Smoke test: send a tiny Persian + formula image to both vision models (via the gateway).

Run from `backend/`:  .venv\\Scripts\\python scripts\\test_llm.py
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont, features  # noqa: E402
from pydantic import ValidationError  # noqa: E402

PERSIAN_TEXT = "سلام"
# Pre-shaped, visually ordered "سلام" for Pillow builds without RAQM shaping.
PERSIAN_TEXT_PRESHAPED = "\uFEE1\uFEFC\uFEB3"
FORMULA = "F = ma"
FONT_CANDIDATES = ("tahoma.ttf", "arial.ttf", "DejaVuSans.ttf")

SYSTEM_PROMPT = (
    "You are an OCR engine. Reply with a single JSON object and nothing else."
)
USER_TEXT = (
    "Read the image. Return JSON with exactly these keys: "
    '"persian_text" (the Persian text you see) and "formula" (the formula you see).'
)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise RuntimeError(f"no usable TrueType font found among {FONT_CANDIDATES}")


def make_test_png() -> bytes:
    """Render "سلام" and "F = ma" on a white canvas and return PNG bytes."""
    image = Image.new("RGB", (480, 240), "white")
    draw = ImageDraw.Draw(image)
    font = _load_font(64)

    if features.check("raqm"):
        draw.text(
            (240, 70),
            PERSIAN_TEXT,
            font=font,
            fill="black",
            anchor="mm",
            direction="rtl",
            language="fa",
        )
    else:
        draw.text((240, 70), PERSIAN_TEXT_PRESHAPED, font=font, fill="black", anchor="mm")
    draw.text((240, 170), FORMULA, font=font, fill="black", anchor="mm")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def run_model(label: str, model: str, png: bytes) -> bool:
    # Always exercise the Central AI Gateway, never a provider SDK directly.
    from app.services.ai_gateway import CallContext, vision_json_via_gateway

    print(f"\n=== {label}: {model} ===")
    started = time.perf_counter()
    try:
        result = await vision_json_via_gateway(
            ctx=CallContext(feature_key="vision_ocr", textbook_strict=False),
            system_prompt=SYSTEM_PROMPT,
            user_text=USER_TEXT,
            image_bytes=png,
            image_mime_type="image/png",
            model=model,
        )
        parsed = result.content
        usage = {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out}
    except Exception as error:  # noqa: BLE001 - report any failure per model
        latency = time.perf_counter() - started
        print(f"result  : FAILURE ({type(error).__name__}: {str(error)[:300]})")
        print(f"latency : {latency:.2f}s")
        return False

    latency = time.perf_counter() - started
    flat = json.dumps(parsed, ensure_ascii=False)
    print("result  : SUCCESS")
    print(f"latency : {latency:.2f}s")
    print(f"model   : {result.model_name} | audit_id: {result.audit_id}")
    print(f"usage   : {usage}")
    print(f"parsed  : {flat}")
    print(f"saw persian text '{PERSIAN_TEXT}': {PERSIAN_TEXT in flat}")
    print(f"saw formula '{FORMULA}': {FORMULA.replace(' ', '') in flat.replace(' ', '')}")
    return True


async def main() -> int:
    from app.core.config import get_settings

    try:
        settings = get_settings()
    except ValidationError as error:
        missing = ", ".join(str(item["loc"][0]).upper() for item in error.errors())
        print(f"CONFIG ERROR: set these in backend/.env: {missing}")
        return 2

    png = make_test_png()
    print(f"test image: {len(png)} bytes, raqm shaping: {features.check('raqm')}")

    results = [
        await run_model("VISION_MODEL_A", settings.vision_model_a, png),
        await run_model("VISION_MODEL_B", settings.vision_model_b, png),
    ]
    print(f"\nsummary: {sum(results)}/{len(results)} models succeeded")
    return 0 if all(results) else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(asyncio.run(main()))
