from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from bot.slack_app import format_search_response, handle_unblock_command
from shared.models import Citation, SearchResponse


class SlackCommandTest(IsolatedAsyncioTestCase):
    async def test_empty_query_responds_with_usage(self):
        ack = AsyncMock()
        respond = AsyncMock()

        await handle_unblock_command(ack, {"text": "  "}, respond)

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        self.assertIn("Add a question", respond.await_args.args[0])

    async def test_query_returns_answer_and_citation(self):
        ack = AsyncMock()
        respond = AsyncMock()
        result = SearchResponse(
            answer="Re-authenticate the session.",
            citations=[
                Citation(
                    thread_id="thread-1",
                    permalink="https://slack.example/thread-1",
                    snippet="Session re-authentication fixed this.",
                )
            ],
        )

        with patch("bot.slack_app.run_in_threadpool", return_value=result):
            await handle_unblock_command(
                ack,
                {"text": "why does login fail?"},
                respond,
            )

        ack.assert_awaited_once()
        respond.assert_awaited_once_with(
            "Re-authenticate the session.\n\nSources:\n- "
            "<https://slack.example/thread-1|thread-1>",
            response_type="ephemeral",
        )

    def test_response_without_citations_contains_only_answer(self):
        response = SearchResponse(answer="No strong match was found.", citations=[])

        self.assertEqual(format_search_response(response), "No strong match was found.")