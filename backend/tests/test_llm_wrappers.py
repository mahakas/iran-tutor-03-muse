"""Shared LLM wrapper JSON mode can be tested without network credentials."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import llm_client


@pytest.mark.asyncio
async def test_complete_json_uses_json_mode_and_parses_object(monkeypatch):
    observed = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"questions":[]}'))],
                usage=None,
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "_semaphore", None)

    result = await llm_client.complete_json(
        "test-model",
        [
            {"role": "system", "content": "generate data"},
            {"role": "user", "content": "make a question"},
        ],
    )

    assert result == {"questions": []}
    assert observed["response_format"] == {"type": "json_object"}
    assert [message["role"] for message in observed["messages"]] == [
        "system",
        "system",
        "user",
    ]


@pytest.mark.asyncio
async def test_stream_text_emits_provider_deltas(monkeypatch):
    import asyncio

    observed = {}
    fragments = ["سلام", " ", "دنیا"]

    class FakeStream:
        async def __aiter__(self):
            for fragment in fragments:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content=fragment))
                    ]
                )

    class FakeCompletions:
        async def create(self, **kwargs):
            observed.update(kwargs)
            return FakeStream()

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm_client, "get_settings", lambda: SimpleNamespace(demo_mode=False))
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "_get_semaphore", lambda: asyncio.Semaphore(1))

    received = []

    async def on_chunk(text):
        received.append(text)

    result = await llm_client.stream_text(
        "stream-model",
        [{"role": "user", "content": "سلام"}],
        on_chunk,
    )

    assert result == "سلام دنیا"
    assert received == fragments
    assert observed["stream"] is True
    assert observed["model"] == "stream-model"
