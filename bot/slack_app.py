"""Slack slash-command integration using Socket Mode."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from starlette.concurrency import run_in_threadpool

from ingestion.config import get_settings
from retrieval.search import RetrievalSearchService
from shared.models import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)


def format_search_response(response: SearchResponse) -> dict[str, Any]:
    answer = _to_slack_mrkdwn(_remove_generated_sources(response.answer))
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Unblock response"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": answer}},
    ]
    fallback_text = answer
    if response.citations:
        sources = "\n".join(
            f"- <{citation.permalink}|Thread {index}>"
            for index, citation in enumerate(response.citations, start=1)
        )
        blocks.extend(
            [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Sources*\n{sources}"},
                },
            ]
        )
        fallback_text = f"{answer}\n\nSources:\n{sources}"
    return {"text": fallback_text, "blocks": blocks}


def _remove_generated_sources(answer: str) -> str:
    lines = answer.splitlines()
    for index, line in enumerate(lines):
        heading = line.strip().strip("#*_ ").rstrip(":").strip().casefold()
        if heading in {"source", "sources", "references", "citations"}:
            return "\n".join(lines[:index]).rstrip()
    return answer.strip()


def _to_slack_mrkdwn(answer: str) -> str:
    lines = []
    for line in answer.splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            line = f"*{heading.group(1)}*"
        line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
        lines.append(line)
    return "\n".join(lines).strip()


async def handle_unblock_command(
    ack: Callable[[], Awaitable[None]],
    command: dict[str, Any],
    respond: Callable[..., Awaitable[Any]],
) -> None:
    await ack()
    query = command.get("text", "").strip()
    if not query:
        await respond(
            "Add a question after `/unblock`, for example `/unblock why does login fail?`",
            response_type="ephemeral",
        )
        return

    try:
        response = await run_in_threadpool(
            RetrievalSearchService().search,
            SearchRequest(query=query),
        )
    except Exception:
        logger.exception("Slack /unblock retrieval failed")
        await respond(
            "Unblock could not search Slack right now. Please try again shortly.",
            response_type="ephemeral",
        )
        return

    await respond(**format_search_response(response), response_type="ephemeral")


async def run_slack_bot() -> None:
    settings = get_settings()
    slack_app = AsyncApp(token=settings.slack_bot_token)
    slack_app.command("/unblock")(handle_unblock_command)

    handler = AsyncSocketModeHandler(slack_app, settings.slack_app_token)
    try:
        await handler.start_async()
    finally:
        await handler.close_async()