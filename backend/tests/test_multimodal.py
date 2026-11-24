"""Image and audio processing is independently testable with mocked providers."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.tutor import _normalize_image, _provider_failure
from app.services import multimodal_service


@pytest.mark.asyncio
async def test_image_question_is_transcribed_then_routed_through_textbook_rag(monkeypatch):
    async def fake_vision_gateway(*, ctx, system_prompt, user_text, image_bytes, image_mime_type="image/png", model=None, session=None, **kwargs):
        assert model == "vision-test"
        assert image_mime_type == "image/png"
        assert ctx.feature_key == "vision_ocr"
        assert image_bytes == b"normalized-image"
        return SimpleNamespace(
            content={
                "question_text": "جسمی با سرعت اولیه ۲ حرکت می‌کند.",
                "visual_description": "نمودار مکان بر حسب زمان خطی است.",
                "uncertain_parts": ["عدد کنار محور کمی ناخواناست"],
            },
            audit_id="audit-vision",
        )

    async def fake_answer(**kwargs):
        assert kwargs["query"].startswith("جسمی با سرعت اولیه")
        assert "توصیف شکل سؤال" in kwargs["query"]
        return {"answer": "پاسخ مستند", "sources": [{"citation": "صفحه ۱۴"}]}

    monkeypatch.setattr(
        multimodal_service, "get_settings", lambda: SimpleNamespace(vision_model_primary="vision-test")
    )
    monkeypatch.setattr(multimodal_service, "vision_json_via_gateway", fake_vision_gateway)
    monkeypatch.setattr(multimodal_service, "answer_from_textbook", fake_answer)

    result = await multimodal_service.answer_image_question(
        image_bytes=b"normalized-image",
        image_mime_type="image/png",
        grade_number=12,
        major_code="math_physics",
        book_id=1,
    )

    assert result["recognized_question"].startswith("جسمی")
    assert result["uncertain_parts"] == ["عدد کنار محور کمی ناخواناست"]
    assert result["sources"][0]["citation"] == "صفحه ۱۴"


@pytest.mark.asyncio
async def test_audio_transcript_is_sent_to_textbook_rag(monkeypatch):
    async def fake_transcribe_gateway(*, ctx, audio_bytes, filename, content_type, model=None, session=None, **kwargs):
        assert audio_bytes == b"audio"
        assert filename == "question.wav"
        assert content_type == "audio/wav"
        assert ctx.feature_key == "stt"
        return SimpleNamespace(content="شتاب ثابت یعنی چه؟")

    async def fake_answer(**kwargs):
        assert kwargs["query"] == "شتاب ثابت یعنی چه؟"
        return {"answer": "توضیح کتابی", "sources": []}

    monkeypatch.setattr(
        multimodal_service, "transcribe_audio_via_gateway", fake_transcribe_gateway
    )
    monkeypatch.setattr(multimodal_service, "answer_from_textbook", fake_answer)

    result = await multimodal_service.answer_audio_question(
        audio_bytes=b"audio",
        filename="question.wav",
        content_type="audio/wav",
        grade_number=12,
        major_code="math_physics",
        book_id=1,
    )

    assert result["transcript"] == "شتاب ثابت یعنی چه؟"


def test_image_normalizer_validates_and_converts_supported_image():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 20), color="white").save(buffer, format="JPEG")

    normalized = _normalize_image(buffer.getvalue(), "image/jpeg")

    with Image.open(io.BytesIO(normalized)) as output:
        assert output.format == "PNG"
        assert output.size == (32, 20)


def test_image_normalizer_rejects_mime_mismatch():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="JPEG")
    with pytest.raises(HTTPException) as error:
        _normalize_image(buffer.getvalue(), "image/png")
    assert error.value.status_code == 415


def test_image_normalizer_rejects_unsupported_media_type():
    with pytest.raises(HTTPException) as error:
        _normalize_image(b"anything", "image/gif")
    assert error.value.status_code == 415


def test_provider_failure_reports_missing_voice_configuration_without_secrets():
    error = _provider_failure(
        RuntimeError("SPEECH_TO_TEXT_MODEL must be configured"), operation="voice tutor"
    )
    assert error.status_code == 503
    assert "not configured" in error.detail
