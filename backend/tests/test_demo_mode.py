"""Offline demo mode is deterministic and must never contact an LLM provider."""

from types import SimpleNamespace

import pytest

from app.core import llm_client


@pytest.mark.asyncio
async def test_demo_text_completion_is_local_and_explicit(monkeypatch):
    monkeypatch.setattr(llm_client, "get_settings", lambda: SimpleNamespace(demo_mode=True))

    result = await llm_client.complete_text(
        "fake-model",
        [{"role": "user", "content": "شیب نمودار مکان زمان"}],
    )

    assert "حالت نمایشی" in result
    assert "سرعت" in result


@pytest.mark.asyncio
async def test_demo_exam_json_obeys_requested_count(monkeypatch):
    monkeypatch.setattr(llm_client, "get_settings", lambda: SimpleNamespace(demo_mode=True))

    result = await llm_client.complete_json(
        "fake-model",
        [{"role": "system", "content": "دقیقاً 3 سؤال تولید کن"}],
    )

    assert len(result["questions"]) == 3
    assert {question["correct_option"] for question in result["questions"]} == {"A"}


@pytest.mark.asyncio
async def test_demo_transcription_is_labelled_as_synthetic(monkeypatch):
    monkeypatch.setattr(llm_client, "get_settings", lambda: SimpleNamespace(demo_mode=True))

    transcript = await llm_client.transcribe_audio(
        b"audio", filename="sample.webm", content_type="audio/webm"
    )

    assert "رونوشت نمونه" in transcript
    with pytest.raises(ValueError, match="empty"):
        await llm_client.transcribe_audio(b"", filename="empty.webm", content_type="audio/webm")


@pytest.mark.asyncio
async def test_demo_embeddings_are_deterministic_and_do_not_need_a_provider(monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: SimpleNamespace(demo_mode=True, embedding_dimension=32, embedding_model="demo"),
    )

    first = await llm_client.embed_texts(["متن نمونه"])
    second = await llm_client.embed_texts(["متن نمونه"])

    assert first == second
    assert len(first[0]) == 32
    assert sum(value * value for value in first[0]) == pytest.approx(1.0)
