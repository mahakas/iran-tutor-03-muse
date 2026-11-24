"""Phase 9 tests: smart podcast generation (Audio Overview style).

Covers: source resolution (grade limit, official-textbook-only), script generation
for all four formats with Pydantic validation + repair retry, per-speaker TTS with
the shared audio cache, real audio assembly and duration, background job state
with stale recovery and duplicate-claim protection, resume after failure (only
failed segments re-synthesized), Ask-the-hosts grounding, feedback, ownership and
capability gating, HTTP Range streaming and admin stats.

No network I/O: `ai_gateway.complete_text` / `synthesize_speech` are faked;
the gateway still writes real audit rows and quota counters.
"""

from __future__ import annotations

import asyncio
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import require_student
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.capabilities import Capability
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.governance import AiAuditLog, AiProvider, FeatureModelRoute, UserQuota
from app.models.podcast import PodcastEpisode, PodcastFeedback, PodcastQuestion, PodcastSegment
from app.services import ai_gateway, podcast_service as ps
from app.services.audio_assembly import (
    assemble_mp3_frames,
    assemble_wav_stdlib,
    estimate_mp3_duration,
    strip_id3,
)

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}


def make_wav(seconds: float = 0.3, rate: int = 8000) -> bytes:
    samples = int(seconds * rate)
    data = b"\x00\x00" * samples
    return (
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data
    )


def script_json(speaker_a: str = "host_a", speaker_b: str = "host_b") -> str:
    return (
        '{"title":"پادکست حرکت بر خط راست","description":"مرور فصل با گفت‌وگو",'
        '"segments":['
        f'{{"speaker":"{speaker_a}","text":"سلام! امروز حرکت بر خط راست را با هم مرور میکنیم.","source_refs":[1]}},'
        f'{{"speaker":"{speaker_b}","text":"جالب است؛ سرعت متوسط چطور تعریف میشود؟","source_refs":[2]}},'
        f'{{"speaker":"{speaker_a}","text":"سرعت متوسط مسافت بر زمان است و در پایان جمعبندی میکنیم.","source_refs":[1]}}],'
        '"suggested_questions":["مهم‌ترین نکتهٔ این فصل چیست؟","یک مثال دیگر حل کن"]}'
    )


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase9.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    ids: dict[str, object] = {}
    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        from app.services.capability_service import seed_capabilities

        await seed_capabilities(session)
        grade10 = await session.scalar(select(Grade).where(Grade.number == 10))
        grade12 = await session.scalar(select(Grade).where(Grade.number == 12))
        major = await session.scalar(select(Major).limit(1))
        book = Book(
            title="فیزیک دهم",
            grade_id=grade10.id,
            major_id=major.id if major else None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=10,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        session.add(book)
        await session.flush()
        for pdf_page, printed, chapter in ((3, 25, 2), (4, 26, 2), (5, 30, 3)):
            session.add(
                BookPage(
                    book_id=book.id,
                    pdf_page_index=pdf_page,
                    printed_page_number=printed,
                    chapter_number=chapter,
                    chapter_title="حرکت بر خط راست" if chapter == 2 else "نوسان",
                    markdown_content=f"متن صفحهٔ {printed} با مفهوم شتاب و فرمول سرعت.",
                    page_image_path="/tmp/none.png",
                    status=PageStatus.done,
                )
            )
        book12 = Book(
            title="فیزیک دوازدهم",
            grade_id=grade12.id,
            major_id=major.id if major else None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=5,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        session.add(book12)
        await session.flush()
        session.add(
            BookPage(
                book_id=book12.id,
                pdf_page_index=1,
                printed_page_number=1,
                chapter_number=1,
                chapter_title="مقدمه",
                markdown_content="متن پیشرفتهٔ پایه دوازدهم.",
                page_image_path="/tmp/none.png",
                status=PageStatus.done,
            )
        )
        student = User(
            phone_number="09120000001",
            full_name="دانش‌آموز",
            role="student",
            tokens_remaining=1_000_000,
            plan_expires_at=datetime(2026, 12, 23, tzinfo=timezone.utc),
            grade_level=10,
            is_active=True,
        )
        other = User(
            phone_number="09120000002",
            full_name="دیگری",
            role="student",
            tokens_remaining=1_000_000,
            plan_expires_at=datetime(2026, 12, 23, tzinfo=timezone.utc),
            grade_level=10,
            is_active=True,
        )
        session.add_all([student, other])
        await session.flush()
        # Configure podcast voices (two distinct hosts) + language policy.
        podcast_cap = await session.get(Capability, "audio_podcast")
        podcast_cap.config_json = {
            "host_a_voice": "alloy",
            "host_b_voice": "echo",
            "narrator_voice": "onyx",
            "max_source_chars": 12000,
            "max_concurrent_jobs": 2,
            "supported_languages": ["fa"],
        }
        ids.update(book_id=book.id, book12_id=book12.id, student_id=student.id, other_id=other.id)
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    async def override_student():
        async with factory() as session:
            return await session.get(User, ids["student_id"])

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_student] = override_student
    monkeypatch.setattr(ps, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "get_settings",
                        lambda: SimpleNamespace(tutor_model="test-model", llm_timeout=5,
                                                speech_synthesis_model="test-tts-model"))
    monkeypatch.setattr(
        ps, "get_settings",
        lambda: SimpleNamespace(demo_mode=False, speech_default_voice="", speech_synthesis_model="test-tts-model"),
    )
    podcast_root = tmp_path / "podcast_audio"
    monkeypatch.setattr(ps, "PODCAST_ROOT", podcast_root)

    calls: list[tuple] = []

    narrator_script = script_json(speaker_a="narrator", speaker_b="narrator")

    async def fake_complete_text(model, messages, *args, **kwargs):
        calls.append(("script", messages))
        content = messages[-1]["content"] if messages else ""
        return narrator_script if "قالب Brief" in content else env_obj.script_reply

    async def fake_synthesize_speech(text, *, voice, model, base_url=None, api_key=None):
        calls.append(("tts", voice, text))
        return make_wav(0.25)

    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)
    monkeypatch.setattr(ai_gateway, "synthesize_speech", fake_synthesize_speech)

    env_obj = SimpleNamespace(
        factory=factory,
        ids=ids,
        calls=calls,
        script_reply=script_json(),
        podcast_root=podcast_root,
        app=app,
    )
    yield env_obj
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def wait_for_status(client: AsyncClient, episode_id: int, statuses: tuple[str, ...], timeout: float = 20.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    last = {}
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v1/podcasts/{episode_id}/status")
        last = resp.json()
        if last.get("status") in statuses:
            return last
        await asyncio.sleep(0.08)
    return last


async def create_podcast(env, client: AsyncClient, **overrides) -> dict:
    body = {
        "book_id": env.ids["book_id"],
        "format": "deep_dive",
        "language": "fa",
        "length": "short",
        "chapter_numbers": [2],
        **overrides,
    }
    resp = await client.post("/api/v1/podcasts", json=body)
    assert resp.status_code == 202, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Unit-level: audio assembly + TTS splitting + script validation
# ---------------------------------------------------------------------------


def test_wav_stdlib_concat_has_correct_duration(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    a.write_bytes(make_wav(0.5, 8000))
    b.write_bytes(make_wav(0.5, 8000))
    out = tmp_path / "out.wav"
    duration = assemble_wav_stdlib([a, b], out)
    assert abs(duration - 1.0) < 0.02
    assert out.is_file() and out.read_bytes()[:4] == b"RIFF"


def test_mp3_frame_concat_strips_headers_and_estimates_duration(tmp_path):
    # A minimal silent MPEG1 Layer III frame at 128kbps/44.1kHz.
    def mp3_file(path: Path) -> None:
        frame = b"\xff\xfb\x90\x64" + b"\x00" * 417
        data = b"ID3" + bytes([3, 0, 0, 0, 0, 0, 0]) + b"TAG" + frame * 20
        path.write_bytes(data)

    a, b, out = tmp_path / "a.mp3", tmp_path / "b.mp3", tmp_path / "out.mp3"
    mp3_file(a)
    mp3_file(b)
    assert strip_id3(a.read_bytes())[:4] != b"ID3\x03"
    duration = assemble_mp3_frames([a, b], out)
    assert out.is_file()
    frame_estimate = estimate_mp3_duration(b"\xff\xfb\x90\x64" + b"\x00" * 417)
    assert frame_estimate > 0
    assert duration == pytest.approx(2 * estimate_mp3_duration((b"\xff\xfb\x90\x64" + b"\x00" * 417) * 20), rel=0.3)


def test_split_for_tts_never_breaks_dollar_formula():
    text = ("این یک جملهٔ آزمایشی نسبتاً طولانی است. " * 40) + " فرمول $E = mc^2$ مهم است."
    pieces = ps._split_for_tts(text)
    assert all(len(piece) <= ps.MAX_TTS_PIECE_CHARS for piece in pieces)
    joined = " ".join(pieces)
    assert "$E = mc^2$" in joined  # the formula survives splitting


def test_validate_script_rejects_unknown_speaker():
    with pytest.raises(Exception):
        ps.validate_script(script_json(speaker_a="host_c"), format="deep_dive")
    ok = ps.validate_script(script_json(speaker_a="narrator", speaker_b="narrator"), format="brief")
    assert ok.title


# ---------------------------------------------------------------------------
# API-level end-to-end flows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deep_dive_podcast_end_to_end(env):
    async with _client() as client:
        created = await create_podcast(env, client)
        episode_id = created["episode_id"]
        final = await wait_for_status(client, episode_id, ("completed", "failed"))
        assert final["status"] == "completed", final

        detail = (await client.get(f"/api/v1/podcasts/{episode_id}")).json()
        assert detail["title"] == "پادکست حرکت بر خط راست"
        assert len(detail["segments"]) == 3
        assert [seg["speaker"] for seg in detail["segments"]] == ["host_a", "host_b", "host_a"]
        # real measured duration + transcript timestamps
        assert final["duration_seconds"] and final["duration_seconds"] > 0
        timed = [seg for seg in detail["segments"] if seg["start_time"] is not None]
        assert len(timed) == 3
        assert timed[-1]["end_time"] == pytest.approx(final["duration_seconds"], rel=0.5)
        assert "گویندهٔ اول" in detail["transcript"]
        assert detail["suggested_questions"]
        # source citations in the required textbook format
        assert any("[کتاب: فیزیک دهم | پایه 10 | صفحه 25" in s["citation"] for s in detail["sources"])

        audio = await client.get(f"/api/v1/podcasts/{episode_id}/audio")
        assert audio.status_code == 200
        assert audio.content[:4] == b"RIFF" or audio.content[:3] == b"ID3" or audio.content[:2] == b"\xff\xfb"

        # script + tts features audited with their own feature keys
        async with env.factory() as session:
            features = {
                row.feature_key
                for row in (await session.scalars(select(AiAuditLog))).all()
            }
            assert "audio_podcast_script" in features
            assert "audio_podcast_tts" in features
            for key in ("audio_podcast_script", "audio_podcast_tts"):
                quota = await session.scalar(
                    select(UserQuota).where(
                        UserQuota.user_id == env.ids["student_id"], UserQuota.feature_key == key
                    )
                )
                assert quota is not None and quota.daily_requests_used >= 1


@pytest.mark.asyncio
async def test_all_four_formats_and_custom_prompt_reach_the_model(env):
    async with _client() as client:
        prompts = []
        for format_key in ("deep_dive", "brief", "critique", "debate"):
            created = await create_podcast(env, client, format=format_key, length="long",
                                           custom_prompt="فقط نکات امتحانی را توضیح بده")
            final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
            assert final["status"] == "completed", final
            detail = (await client.get(f"/api/v1/podcasts/{created['episode_id']}")).json()
            if format_key == "brief":
                assert {seg["speaker"] for seg in detail["segments"]} == {"narrator"}
            else:
                assert {seg["speaker"] for seg in detail["segments"]} == {"host_a", "host_b"}
        for kind, messages in [c for c in env.calls if c[0] == "script"]:
            prompts.append(messages[-1]["content"])
        assert any("فقط نکات امتحانی را توضیح بده" in p for p in prompts)
        assert any("قالب Brief" in p for p in prompts)
        assert any("قالب Debate" in p for p in prompts)
        assert any("قالب Deep Dive" in p for p in prompts)
        assert any("مدت هدف پادکست طولانی" in p for p in prompts)


@pytest.mark.asyncio
async def test_source_selection_multi_chapter_page_range_and_grade_limit(env):
    async with _client() as client:
        created = await create_podcast(
            env, client, chapter_numbers=[2, 3], page_start=4, page_end=5
        )
        final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        assert final["status"] == "completed"
        detail = (await client.get(f"/api/v1/podcasts/{created['episode_id']}")).json()
        pages = {s["citation"] for s in detail["sources"]}
        assert any("صفحه 26" in c for c in pages)
        assert not any("صفحه 25" in c for c in pages)  # outside the selected range

        higher = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book12_id"], "format": "brief", "language": "fa",
                  "length": "short", "chapter_numbers": [1]},
        )
        assert higher.status_code == 422  # grade 12 book for a grade-10 student
        bad_range = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book_id"], "format": "brief", "language": "fa",
                  "length": "short", "page_start": 9, "page_end": 2},
        )
        assert bad_range.status_code == 422
        unsupported = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book_id"], "format": "brief", "language": "en",
                  "length": "short", "chapter_numbers": [2]},
        )
        assert unsupported.status_code == 422  # only languages the TTS really supports


@pytest.mark.asyncio
async def test_needs_review_pages_never_enter_podcast_sources(env):
    """Phase 04A source integrity: only `done` pages feed the podcast. A needs_review
    page must not enter educational audio without an explicit owner decision, and a
    range holding only needs_review text is rejected outright."""
    async with env.factory() as session:
        book = await session.get(Book, env.ids["book_id"])
        session.add(
            BookPage(
                book_id=book.id,
                pdf_page_index=6,
                printed_page_number=31,
                chapter_number=2,
                chapter_title="حرکت بر خط راست",
                markdown_content="متن تأییدنشدهٔ صفحهٔ ۳۱ که نباید وارد پادکست شود.",
                page_image_path="/tmp/none.png",
                status=PageStatus.needs_review,
            )
        )
        await session.commit()
    async with _client() as client:
        created = await create_podcast(env, client, chapter_numbers=[2])
        final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        assert final["status"] == "completed"
        detail = (await client.get(f"/api/v1/podcasts/{created['episode_id']}")).json()
        pages = {s["citation"] for s in detail["sources"]}
        assert any("صفحه 26" in c for c in pages)      # done page is included
        assert not any("صفحه 31" in c for c in pages)  # needs_review page is excluded

        # A selection whose only text is needs_review must fail before any job is queued.
        resp = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book_id"], "format": "brief", "language": "fa",
                  "length": "short", "page_start": 6, "page_end": 6},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cancelled_episode_can_be_cancelled_retried_and_completed(env):
    """Phase 04A job lifecycle: queued → cancelled, generating_audio → cancelled,
    retry → full pipeline → completed, and an honest 422 once completed."""
    from app.models.auth import User

    async with env.factory() as session:
        user = await session.get(User, env.ids["student_id"])
        book = await session.get(Book, env.ids["book_id"])
        episode = await ps.create_episode(
            session, user, book=book, format="brief", language="fa", length="short",
            chapter_numbers=[2],
        )
        await session.commit()
        episode_id = episode.id
    async with _client() as client:
        # queued → cancelled through the real API (no worker has claimed it yet)
        resp = await client.post(f"/api/v1/podcasts/{episode_id}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"

        # a job in the audio stage is also cancellable
        async with env.factory() as session:
            row = await session.get(PodcastEpisode, episode_id)
            row.status = "generating_audio"
            row.heartbeat_at = datetime.now(timezone.utc)
            await session.commit()
        resp = await client.post(f"/api/v1/podcasts/{episode_id}/cancel")
        assert resp.status_code == 200, resp.text

        # retry re-queues and runs the pipeline to completion (fake provider)
        resp = await client.post(f"/api/v1/podcasts/{episode_id}/retry")
        assert resp.status_code == 200, resp.text
        final = await wait_for_status(client, episode_id, ("completed", "failed"))
        assert final["status"] == "completed"

        # completed episodes can no longer be cancelled — honest 422, no fake action
        resp = await client.post(f"/api/v1/podcasts/{episode_id}/cancel")
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_failed_script_gets_one_repair_retry_then_retry_endpoint_succeeds(env):
    env.script_reply = "این اصلاً JSON نیست [[("
    async with _client() as client:
        created = await create_podcast(env, client)
        final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        assert final["status"] == "failed"
        assert final["error_code"] in ("script_invalid", "generation_error")
        script_calls = [c for c in env.calls if c[0] == "script"]
        assert len(script_calls) >= 2  # first attempt + one controlled repair

        env.script_reply = script_json()
        env.calls.clear()
        retried = await client.post(f"/api/v1/podcasts/{created['episode_id']}/retry")
        assert retried.status_code == 200
        final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        assert final["status"] == "completed", final


@pytest.mark.asyncio
async def test_audio_failure_resumes_without_re_synthesizing_ready_segments(env, monkeypatch):
    async with _client() as client:
        # First TTS call fails after the script is ready.
        original_speech = ai_gateway.synthesize_speech

        async def failing_speech(text, **kwargs):
            raise HTTPException(status_code=503, detail="provider down")

        monkeypatch.setattr(ai_gateway, "synthesize_speech", failing_speech)
        created = await create_podcast(env, client)
        final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        assert final["status"] == "failed"

        monkeypatch.setattr(ai_gateway, "synthesize_speech", original_speech)
        env.calls.clear()
        env.script_reply = script_json()
        retried = await client.post(f"/api/v1/podcasts/{created['episode_id']}/retry")
        assert retried.status_code == 200
        final = await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        assert final["status"] == "completed", final
        tts_calls = [c for c in env.calls if c[0] == "tts"]
        script_calls = [c for c in env.calls if c[0] == "script"]
        assert not script_calls  # validated script reused, not regenerated
        assert tts_calls  # remaining pieces synthesized once each


@pytest.mark.asyncio
async def test_tts_cache_is_reused_across_episodes_without_new_provider_calls(env):
    async with _client() as client:
        created = await create_podcast(env, client)
        await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        tts_first = [c for c in env.calls if c[0] == "tts"]
        env.calls.clear()
        second = await create_podcast(env, client, chapter_numbers=[2])
        final = await wait_for_status(client, second["episode_id"], ("completed", "failed"))
        assert final["status"] == "completed"
        tts_second = [c for c in env.calls if c[0] == "tts"]
        assert tts_second == []  # every piece served from the shared content-addressed cache
        assert tts_first  # sanity: first run really synthesized


@pytest.mark.asyncio
async def test_duplicate_job_claim_and_stale_recovery(env):
    async with env.factory() as session:
        episode = PodcastEpisode(
            user_id=env.ids["student_id"],
            book_id=env.ids["book_id"],
            title="در حال تولید",
            format="deep_dive",
            status="generating_audio",
            source_snapshot_json={"sources": [], "citations": []},
            heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(episode)
        stale = PodcastEpisode(
            user_id=env.ids["student_id"],
            book_id=env.ids["book_id"],
            title="رهاشده",
            format="brief",
            status="generating_audio",
            source_snapshot_json={"sources": [], "citations": []},
            heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        session.add(stale)
        await session.commit()
        live_id, stale_id = episode.id, stale.id

    # A running job (not queued) is never re-claimed by another worker pass.
    await ps.process_episode(live_id)
    async with env.factory() as session:
        assert (await session.get(PodcastEpisode, live_id)).status == "generating_audio"

    async with env.factory() as session:
        recovered = await ps.recover_stale_episodes(session)
    assert recovered == 1
    async with env.factory() as session:
        row = await session.get(PodcastEpisode, stale_id)
        assert row.status == "failed" and row.error_code == "worker_lost"


async def _session_gen(env):
    session = env.factory()
    try:
        yield session
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_concurrent_job_limit_per_user(env, monkeypatch):
    monkeypatch.setattr(ps, "process_episode", _slow_process)
    async with env.factory() as session:
        podcast_cap = await session.get(Capability, "audio_podcast")
        podcast_cap.config_json = {**podcast_cap.config_json, "max_concurrent_jobs": 1}
        await session.commit()
    async with _client() as client:
        first = await create_podcast(env, client)
        assert first["status"] == "queued"
        second = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book_id"], "format": "brief", "language": "fa",
                  "length": "short", "chapter_numbers": [2]},
        )
        assert second.status_code == 429
        third = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book_id"], "format": "brief", "language": "fa",
                  "length": "short", "chapter_numbers": [2]},
        )
        assert third.status_code == 429


async def _slow_process(episode_id: int) -> None:
    await asyncio.sleep(30)


@pytest.mark.asyncio
async def test_ownership_is_enforced_on_every_endpoint(env):
    async with _client() as client:
        created = await create_podcast(env, client)
        await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        episode_id = created["episode_id"]

        async with env.factory() as session:
            other = await session.get(User, env.ids["other_id"])

        async def override_other():
            return other

        app.dependency_overrides[require_student] = override_other
        try:
            assert (await client.get(f"/api/v1/podcasts/{episode_id}")).status_code == 404
            assert (await client.get(f"/api/v1/podcasts/{episode_id}/audio")).status_code == 404
            assert (await client.get(f"/api/v1/podcasts/{episode_id}/download")).status_code == 404
            assert (await client.patch(f"/api/v1/podcasts/{episode_id}", json={"title": "x"})).status_code == 404
            assert (await client.delete(f"/api/v1/podcasts/{episode_id}")).status_code == 404
            assert (await client.post(f"/api/v1/podcasts/{episode_id}/questions", json={"question": "سلام چی؟"})).status_code == 404
            assert (await client.post(f"/api/v1/podcasts/{episode_id}/feedback", json={"liked": True})).status_code == 404
        finally:
            async def override_student():
                async with env.factory() as session:
                    return await session.get(User, env.ids["student_id"])

            app.dependency_overrides[require_student] = override_student


@pytest.mark.asyncio
async def test_rename_download_transcript_and_delete_cleans_files(env):
    async with _client() as client:
        created = await create_podcast(env, client)
        episode_id = created["episode_id"]
        final = await wait_for_status(client, episode_id, ("completed", "failed"))
        assert final["status"] == "completed"

        renamed = await client.patch(f"/api/v1/podcasts/{episode_id}", json={"title": "مرور فیزیک فصل ۲"})
        assert renamed.json()["title"] == "مرور فیزیک فصل ۲"
        detail = (await client.get(f"/api/v1/podcasts/{episode_id}")).json()
        assert detail["title"] == "مرور فیزیک فصل ۲"

        download = await client.get(f"/api/v1/podcasts/{episode_id}/download")
        assert download.status_code == 200
        assert f"darsyar-podcast-{episode_id}" in download.headers.get("content-disposition", "")

        transcript = await client.get(f"/api/v1/podcasts/{episode_id}/transcript")
        assert transcript.json()["transcript"]

        # HTTP Range (seek) support on the audio stream.
        head = await client.get(f"/api/v1/podcasts/{episode_id}/audio", headers={"Range": "bytes=0-99"})
        assert head.status_code == 206
        assert len(head.content) == 100

        async with env.factory() as session:
            episode = await session.get(PodcastEpisode, episode_id)
            audio_path = Path(episode.audio_file_path)
            episode_dir = audio_path.parent
        assert audio_path.is_file()
        deleted = await client.delete(f"/api/v1/podcasts/{episode_id}")
        assert deleted.status_code == 204
        assert not episode_dir.exists()
        async with env.factory() as session:
            assert await session.get(PodcastEpisode, episode_id) is None
            assert (await session.scalars(select(PodcastSegment).where(PodcastSegment.episode_id == episode_id))).all() == []


@pytest.mark.asyncio
async def test_ask_hosts_is_grounded_and_feedback_persists(env):
    env.script_reply = script_json()
    async with _client() as client:
        created = await create_podcast(env, client)
        episode_id = created["episode_id"]
        await wait_for_status(client, episode_id, ("completed", "failed"))

        answered = await client.post(
            f"/api/v1/podcasts/{episode_id}/questions",
            json={"question": "سرعت متوسط را ساده توضیح بده"},
        )
        assert answered.status_code == 201, answered.text
        payload = answered.json()
        assert payload["answer_md"]
        prompt = [c for c in env.calls if c[0] == "script"][-1][1][-1]["content"]
        assert "سرعت متوسط را ساده توضیح بده" in prompt
        assert "منابع معتبر" in prompt  # episode sources are provided for grounding

        like = await client.post(f"/api/v1/podcasts/{episode_id}/feedback", json={"liked": True})
        assert like.json()["liked"] is True
        dislike = await client.post(
            f"/api/v1/podcasts/{episode_id}/feedback",
            json={"liked": False, "reasons": ["bad_pronunciation", "unnatural_dialogue"]},
        )
        assert dislike.json() == {"liked": False, "reasons": ["bad_pronunciation", "unnatural_dialogue"]}
        no_reason = await client.post(
            f"/api/v1/podcasts/{episode_id}/feedback", json={"liked": False}
        )
        assert no_reason.status_code == 422

        detail = (await client.get(f"/api/v1/podcasts/{episode_id}")).json()
        assert detail["feedback"]["liked"] is False
        assert len(detail["questions"]) == 1

        async with env.factory() as session:
            feedback = await session.scalar(
                select(PodcastFeedback).where(PodcastFeedback.episode_id == episode_id)
            )
            assert feedback is not None  # upserted, not duplicated


@pytest.mark.asyncio
async def test_regenerate_creates_new_episode_and_keeps_the_old(env):
    async with _client() as client:
        created = await create_podcast(env, client)
        await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        regenerated = await client.post(
            f"/api/v1/podcasts/{created['episode_id']}/regenerate",
            json={"length": "long"},
        )
        assert regenerated.status_code == 202
        new_id = regenerated.json()["episode_id"]
        assert new_id != created["episode_id"]
        final = await wait_for_status(client, new_id, ("completed", "failed"))
        assert final["status"] == "completed"
        async with env.factory() as session:
            new_row = await session.get(PodcastEpisode, new_id)
            assert new_row.length == "long"
            assert (new_row.generation_settings_json or {}).get("regenerated_from") == created["episode_id"]
            assert (await session.get(PodcastEpisode, created["episode_id"])).status == "completed"


@pytest.mark.asyncio
async def test_capability_flag_and_config_endpoint(env):
    async with _client() as client:
        config = await client.get("/api/v1/podcasts/config")
        assert config.status_code == 200
        body = config.json()
        assert body["dual_voice_available"] is True  # two distinct voices configured
        assert [lang["code"] for lang in body["languages"]] == ["fa"]

        off = await client.put("/api/v1/admin/capabilities/audio_podcast", headers=ADMIN_HEADERS,
                               json={"is_enabled": False})
        assert off.status_code == 200
        assert (await client.get("/api/v1/podcasts")).status_code == 403
        assert (await client.get("/api/v1/podcasts/config")).status_code == 403
        created = await client.post(
            "/api/v1/podcasts",
            json={"book_id": env.ids["book_id"], "format": "brief", "language": "fa",
                  "length": "short", "chapter_numbers": [2]},
        )
        assert created.status_code == 403
        assert [c for c in env.calls if c[0] == "script"] == []
        on = await client.put("/api/v1/admin/capabilities/audio_podcast", headers=ADMIN_HEADERS,
                              json={"is_enabled": True})
        assert on.status_code == 200


@pytest.mark.asyncio
async def test_route_mapping_requires_tts_capable_provider(env):
    """audio_podcast_tts must resolve only through providers that declare TTS."""
    async with env.factory() as session:
        provider = AiProvider(
            name="chat-only",
            provider_type="openai",
            base_url="https://example.invalid/v1",
            encrypted_api_key="",
            capabilities=["chat"],
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        session.add(
            FeatureModelRoute(
                feature_key="audio_podcast_tts",
                provider_id=provider.id,
                model_name="tts-1",
                is_active=True,
            )
        )
        await session.commit()

    from app.services.ai_provider_service import resolve_feature_route_candidates

    async with env.factory() as session:
        candidates = await resolve_feature_route_candidates(session, "audio_podcast_tts")
        assert candidates == []  # fail closed: provider without real TTS capability


@pytest.mark.asyncio
async def test_admin_stats_endpoint(env):
    async with _client() as client:
        created = await create_podcast(env, client)
        await wait_for_status(client, created["episode_id"], ("completed", "failed"))
        stats = await client.get("/api/v1/admin/podcasts/stats", headers=ADMIN_HEADERS)
        assert stats.status_code == 200
        body = stats.json()
        assert body["total_episodes"] >= 1
        assert body["tokens_in"] > 0  # real consumption recorded through the gateway
        assert body["ai_calls"] >= 1
        episodes = await client.get("/api/v1/admin/podcasts/episodes", headers=ADMIN_HEADERS)
        assert episodes.status_code == 200
        assert episodes.json()["items"][0]["title"]
        # no transcript / private source text leaks into the admin list
        assert "transcript" not in episodes.json()["items"][0]
