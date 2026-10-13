"""Custom exceptions for retrieval and embedding code."""


class RetrievalError(Exception):
    """Base class for retrieval-related errors."""


class ConfigError(RetrievalError):
    """Raised when required configuration is missing or invalid."""


class ChunkTooLongError(RetrievalError):
    """Raised when a chunk exceeds MAX_CHUNK_TOKENS."""


class EmbeddingAPIError(RetrievalError):
    """Raised when the embeddings provider API call fails after all retries."""


class SynthesisAPIError(RetrievalError):
    """Raised when the Gemini synthesis API call fails or returns an unexpected shape."""