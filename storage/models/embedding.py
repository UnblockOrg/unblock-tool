from __future__ import annotations

import os
from typing import TYPE_CHECKING 

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.models.base import Base

if TYPE_CHECKING:
    from storage.models.thread import Thread

# Must match retrieval.embeddings.config.EMBEDDINGS_DIMENSION for whichever model is
# configured (default voyage-4 = 1024). Changing the embedding model's
# dimension requires a new migration to alter this column.
EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDINGS_DIMENSION", 1024))


class Embedding(Base):
    """Vector embedding for a thread, used for semantic similarity search."""

    __tablename__ = "embeddings"

    __table_args__ = (
        # Approximate nearest-neighbor index; keeps similarity search fast as data grows.
        Index(
            "ix_embeddings_embedding_ivfflat",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": "100"},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id"), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)

    thread: Mapped["Thread"] = relationship(back_populates="embedding")
