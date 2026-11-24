"""Standalone podcast worker — poll the DB and process queued episodes.

Run alongside (or instead of) the API process so long podcast jobs survive API
restarts and never block an HTTP request:

    python -m scripts.podcast_worker            # from backend/
    python backend/scripts/podcast_worker.py    # direct

Claiming is atomic (queued → generating_script), so running several workers or
an API process with its fast-path task is safe — every episode is processed once.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=os.environ.get("PODCAST_WORKER_LOGLEVEL", "INFO"))
logger = logging.getLogger("podcast.worker")

POLL_SECONDS = float(os.environ.get("PODCAST_WORKER_POLL_SECONDS", "5"))
CONCURRENCY = int(os.environ.get("PODCAST_WORKER_CONCURRENCY", "2"))


async def _claim_one() -> int | None:
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.models.podcast import PodcastEpisode

    async with async_session_factory() as session:
        row = await session.scalar(
            select(PodcastEpisode.id)
            .where(PodcastEpisode.status == "queued")
            .order_by(PodcastEpisode.created_at.asc())
            .limit(1)
        )
        return int(row) if row is not None else None


async def main() -> None:
    from app.db.session import close_llm_clients
    from app.services.podcast_service import process_episode

    logger.info("podcast worker started (poll=%ss concurrency=%s)", POLL_SECONDS, CONCURRENCY)
    active: set[asyncio.Task] = set()
    try:
        while True:
            while len(active) < CONCURRENCY:
                episode_id = await _claim_one()
                if episode_id is None:
                    break
                logger.info("claimed episode=%s", episode_id)
                task = asyncio.get_running_loop().create_task(process_episode(episode_id))
                active.add(task)
                task.add_done_callback(active.discard)
            if active:
                done, _ = await asyncio.wait(active, timeout=POLL_SECONDS)
                for task in done:
                    if task.exception():
                        logger.error("episode job crashed", exc_info=task.exception())
            else:
                await asyncio.sleep(POLL_SECONDS)
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        logger.info("podcast worker stopped")
    finally:
        for task in list(active):
            task.cancel()
        await close_llm_clients()


if __name__ == "__main__":
    asyncio.run(main())
