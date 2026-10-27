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
        response_blocks = respond.await_args.kwargs["blocks"]
        self.assertEqual(response_blocks[0]["type"], "header")
        self.assertEqual(response_blocks[0]["text"]["text"], "Unblock response")
        self.assertEqual(response_blocks[1]["text"]["text"], "Re-authenticate the session.")
        self.assertIn("*Sources*", response_blocks[-1]["text"]["text"])
        self.assertIn("|Thread 1>", response_blocks[-1]["text"]["text"])
        self.assertEqual(respond.await_args.kwargs["response_type"], "ephemeral")

    def test_response_without_citations_contains_only_answer(self):
        response = SearchResponse(answer="No strong match was found.", citations=[])

        formatted = format_search_response(response)

        self.assertEqual(formatted["text"], "No strong match was found.")
        self.assertEqual(len(formatted["blocks"]), 2)

    def test_generated_sources_are_replaced_by_canonical_citations(self):
        response = SearchResponse(
            answer=(
                "The payload field names do not match.\n\n"
                "Sources:\n- [1791782341](https://example.test/old-source)"
            ),
            citations=[
                Citation(
                    thread_id="thread-1",
                    permalink="https://slack.example/thread-1",
                    snippet="The backend expected a different field name.",
                )
            ],
        )

        formatted = format_search_response(response)
        answer_block = formatted["blocks"][1]["text"]["text"]
        sources_block = formatted["blocks"][-1]["text"]["text"]

        self.assertNotIn("old-source", answer_block)
        self.assertEqual(sources_block.count("*Sources*"), 1)
        self.assertIn("<https://slack.example/thread-1|Thread 1>", sources_block)

    def test_markdown_headings_are_rendered_as_slack_bold_labels(self):
        response = SearchResponse(
            answer="### Possible causes\n- **Asset upload:** field mismatch.",
            citations=[],
        )

        formatted = format_search_response(response)

        self.assertEqual(
            formatted["blocks"][1]["text"]["text"],
            "*Possible causes*\n- *Asset upload:* field mismatch.",
        )