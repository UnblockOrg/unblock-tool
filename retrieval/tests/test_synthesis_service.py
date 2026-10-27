import unittest
from unittest.mock import patch

import httpx

from retrieval.exceptions import SynthesisAPIError
from retrieval.models import MergedSearchResult, StoredThreadEmbedding, ThreadChunk
from retrieval.synthesis.service import GeminiSynthesisService


def _result() -> MergedSearchResult:
    return MergedSearchResult(
        document=StoredThreadEmbedding(
            id="thread-1",
            chunk=ThreadChunk(
                text="Re-authenticating the SSO session fixed the login failure.",
                channel="engineering-help",
                permalink="https://slack.example/thread-1",
            ),
            vector=[0.1, 0.2],
        ),
        score=1.0,
    )


def _response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://example.test/generateContent"),
    )


class GeminiSynthesisServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = GeminiSynthesisService(api_key="test-key")
        self.results = [_result()]

    def test_retries_transient_503_then_returns_generated_answer(self):
        generated = _response(
            200,
            {"candidates": [{"content": {"parts": [{"text": "Try SSO again."}]}}]},
        )
        with (
            patch(
                "retrieval.synthesis.service.httpx.post",
                side_effect=[_response(503), generated],
            ) as post,
            patch("retrieval.synthesis.service.time.sleep") as sleep,
        ):
            answer = self.service.synthesize("login fails", self.results)

        self.assertEqual(answer, "Try SSO again.")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1)
        prompt = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("present them as separate alternatives", prompt)
        self.assertIn("do not combine them", prompt)
        self.assertIn("do not include URLs", prompt)
        self.assertIn("How to distinguish them", prompt)
        self.assertIn("one separate bullet per context", prompt)

    def test_returns_top_thread_after_transient_failures_are_exhausted(self):
        with (
            patch(
                "retrieval.synthesis.service.httpx.post",
                side_effect=[_response(503), _response(503), _response(503)],
            ) as post,
            patch("retrieval.synthesis.service.time.sleep"),
        ):
            answer = self.service.synthesize("login fails", self.results)

        self.assertIn("Gemini is temporarily unavailable", answer)
        self.assertIn("Re-authenticating the SSO session", answer)
        self.assertEqual(post.call_count, 3)

    def test_does_not_retry_non_transient_client_errors(self):
        with patch(
            "retrieval.synthesis.service.httpx.post",
            return_value=_response(400),
        ) as post:
            with self.assertRaises(SynthesisAPIError):
                self.service.synthesize("login fails", self.results)

        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()