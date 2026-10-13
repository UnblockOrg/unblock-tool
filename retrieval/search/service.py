"""Production retrieval service over the real Unblock database."""

from sqlalchemy.orm import Session

from retrieval.embeddings import EmbeddingService
from retrieval.models import MergedSearchResult
from retrieval.search.database import keyword_search_db, vector_search_db
from retrieval.search.ranking import reciprocal_rank_fusion
from retrieval.synthesis import GeminiSynthesisService
from shared.models import Citation, SearchRequest, SearchResponse
from storage.db import SessionLocal


MIN_VECTOR_RELEVANCE_SCORE = 0.30


class RetrievalSearchService:
    """Search real ingested Slack data and return the shared bot response shape."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        synthesis_service: GeminiSynthesisService | None = None,
        session_factory=SessionLocal,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.synthesis_service = synthesis_service or GeminiSynthesisService()
        self.session_factory = session_factory

    def search(self, request: SearchRequest, limit: int = 5) -> SearchResponse:
        with self.session_factory() as session:
            results = self.search_session(session, request.query, limit=limit)

        return SearchResponse(
            answer=self._build_answer(request.query, results),
            citations=_build_citations(results),
        )

    def search_session(
        self,
        session: Session,
        query: str,
        limit: int = 5,
    ) -> list[MergedSearchResult]:
        query_embedding = self.embedding_service.embed_query(query)
        keyword_hits = keyword_search_db(session, query, limit=limit * 2)
        vector_hits = vector_search_db(session, query_embedding.vector, limit=limit * 2)
        results = reciprocal_rank_fusion(keyword_hits, vector_hits, limit=limit * 2)
        relevant_results = [
            result
            for result in results
            if result.keyword_rank is not None
            or result.vector_score >= MIN_VECTOR_RELEVANCE_SCORE
        ]
        return relevant_results[:limit]

    def _build_answer(self, query: str, results: list[MergedSearchResult]) -> str:
        return self.synthesis_service.synthesize(query, results)


def _build_citations(results: list[MergedSearchResult]) -> list[Citation]:
    citations: list[Citation] = []
    for result in results:
        chunk = result.document.chunk
        if not chunk.permalink:
            continue
        citations.append(
            Citation(
                thread_id=result.document.id,
                permalink=chunk.permalink,
                snippet=chunk.text[:300],
            )
        )
    return citations