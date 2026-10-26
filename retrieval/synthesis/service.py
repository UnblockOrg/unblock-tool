"""Turns ranked candidate threads into a cited, developer-facing answer via Gemini."""

import logging
import time

import httpx

from retrieval.exceptions import SynthesisAPIError
from retrieval.models import MergedSearchResult
from retrieval.synthesis import config

logger = logging.getLogger("retrieval.synthesis")

NO_MATCH_ANSWER = "No strong match was found in the indexed Slack threads."
_MAX_TRANSIENT_RETRIES = 2
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

_SYSTEM_INSTRUCTIONS = (
    "You are Unblock, an assistant that helps engineers resolve issues using "
    "resolved Slack threads. Answer only using the candidate threads below -- "
    "never invent information that is not in them. Explicitly cite which "
    "thread(s) you drew from by permalink. If none of the candidate threads "
    "look like a good match for the query, say so plainly instead of guessing."
)


class GeminiSynthesisService:
    """Calls the Gemini `generateContent` API to synthesize the final answer."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or config.GEMINI_API_KEY
        if not self.api_key:
            config.validate_synthesis_config()
        self.model = model or config.GEMINI_MODEL
        self.base_url = base_url or config.GEMINI_API_BASE_URL
        self.timeout = timeout if timeout is not None else config.GEMINI_TIMEOUT_SECONDS

    def synthesize(self, query: str, results: list[MergedSearchResult]) -> str:
        """Summarize the resolution from the top candidate threads, citing permalinks."""
        if not results:
            return NO_MATCH_ANSWER

        prompt = _build_prompt(query, results)
        url = f"{self.base_url}/models/{self.model}:generateContent"

        for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
            try:
                response = httpx.post(
                    url,
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPError as exc:
                status_code = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                retryable = status_code is None or status_code in _RETRYABLE_STATUS_CODES
                if not retryable:
                    logger.exception("Gemini synthesis request failed")
                    raise SynthesisAPIError("Gemini synthesis request failed") from exc

                if attempt < _MAX_TRANSIENT_RETRIES:
                    delay = 2**attempt
                    logger.warning(
                        "Transient Gemini synthesis failure; retrying in %d seconds "
                        "(attempt %d/%d, status=%s)",
                        delay,
                        attempt + 1,
                        _MAX_TRANSIENT_RETRIES,
                        status_code,
                    )
                    time.sleep(delay)
                    continue

                logger.warning(
                    "Gemini synthesis unavailable after retries (status=%s); "
                    "returning the top retrieved Slack thread",
                    status_code,
                )
                return _fallback_answer(results)

        return _extract_text(payload)


def _build_prompt(query: str, results: list[MergedSearchResult]) -> str:
    threads = []
    for index, result in enumerate(results, start=1):
        chunk = result.document.chunk
        permalink = chunk.permalink or "no permalink available"
        threads.append(
            f"Thread {index} (id={result.document.id}, permalink={permalink}):\n{chunk.text}"
        )
    candidates = "\n\n".join(threads)
    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Developer query: {query}\n\n"
        f"Candidate threads:\n{candidates}"
    )


def _fallback_answer(results: list[MergedSearchResult]) -> str:
    chunk = results[0].document.chunk
    return (
        "Gemini is temporarily unavailable. Here is the top matching indexed "
        f"Slack thread:\n\n{chunk.text}"
    )


def _extract_text(payload: dict) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SynthesisAPIError("Unexpected Gemini response shape") from exc
    return text or NO_MATCH_ANSWER
