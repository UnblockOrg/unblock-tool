"""Background scheduler for periodic Slack ingestion."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable

from dotenv import load_dotenv

SCHEDULE_INTERVAL_SECONDS = 60
IngestChannel = Callable[[str], Awaitable[dict[str, int]]]

logger = logging.getLogger(__name__)
load_dotenv()


def configured_channel_ids(raw_channel_ids: str) -> list[str]:
    """Parse and validate the JSON channel ID array from environment configuration."""
    try:
        channel_ids = json.loads(raw_channel_ids)
    except ValueError as exc:
        raise ValueError("SLACK_CHANNEL_IDS must be a JSON array") from exc

    if not isinstance(channel_ids, list) or not all(
        isinstance(channel_id, str) and channel_id for channel_id in channel_ids
    ):
        raise ValueError("SLACK_CHANNEL_IDS must be a non-empty JSON array of strings")
    return channel_ids


async def run_ingestion_loop(
    ingest_channel: IngestChannel,
    interval_seconds: int = SCHEDULE_INTERVAL_SECONDS,
) -> None:
    """Run ingestion for every configured channel at a fixed interval."""
    while True:
        await asyncio.sleep(interval_seconds)

        try:
            channel_ids = configured_channel_ids(
                os.environ.get("SLACK_CHANNEL_IDS", "[]")
            )
        except ValueError:
            logger.exception("Scheduled ingestion configuration is invalid")
            continue

        for channel_id in channel_ids:
            try:
                counts = await ingest_channel(channel_id)
                logger.info(
                    "Scheduled ingestion completed channel=%s threads=%d messages=%d",
                    channel_id,
                    counts["threads_saved"],
                    counts["messages_saved"],
                )
            except Exception:
                logger.exception("Scheduled ingestion failed channel=%s", channel_id)
