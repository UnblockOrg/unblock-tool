# Dev 3 — AI/Retrieval: embeddings, DB-backed hybrid search,
# merge/rank, and citation-backed responses for bot/.

from retrieval.embeddings import EmbeddingService
from retrieval.models import (
	EmbeddedThreadChunk,
	EmbeddingResult,
	MergedSearchResult,
	SearchHit,
	StoredThreadEmbedding,
	ThreadChunk,
)
from retrieval.search import (
	RetrievalSearchService,
	index_missing_thread_embeddings,
	keyword_search_db,
	reciprocal_rank_fusion,
	vector_search_db,
)
from retrieval.synthesis import GeminiSynthesisService

__all__ = [
	"EmbeddedThreadChunk",
	"EmbeddingResult",
	"EmbeddingService",
	"GeminiSynthesisService",
	"MergedSearchResult",
	"RetrievalSearchService",
	"SearchHit",
	"StoredThreadEmbedding",
	"ThreadChunk",
	"index_missing_thread_embeddings",
	"keyword_search_db",
	"reciprocal_rank_fusion",
	"vector_search_db",
]
