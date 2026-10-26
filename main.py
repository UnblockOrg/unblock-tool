import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from hmac import compare_digest
from time import perf_counter

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from bot.slack_app import run_slack_bot
from ingestion.clients.slack_client import SlackClient
from ingestion.config import get_settings
from ingestion.exceptions import SlackClientError
from ingestion.scheduler import run_ingestion_loop
from ingestion.services.deduplicator import ThreadDeduplicator
from ingestion.services.ingestion_service import IngestionService
from ingestion.services.noise_filter import NoiseFilter
from ingestion.services.pagination import SlackPaginator
from ingestion.services.thread_grouper import ThreadGrouper
from ingestion.storage.checkpoint import CheckpointStore
from retrieval.exceptions import RetrievalError
from retrieval.search import RetrievalSearchService, index_missing_thread_embeddings
from shared.logging_config import configure_logging
from shared.models import SearchRequest, SearchResponse
from storage.db import SessionLocal, get_db
from storage.models.message import Message
from storage.models.thread import Thread
from storage.thread_repository import persist_threads

configure_logging()
logger = logging.getLogger(__name__)

async def _ingest_channel(channel_id: str) -> dict[str, int]:
    settings = get_settings()
    slack_client = SlackClient(
        token=settings.slack_bot_token,
        max_retries=settings.slack_max_retries,
        initial_backoff_seconds=settings.slack_initial_backoff_seconds,
    )
    service = IngestionService(
        slack_client=slack_client,
        paginator=SlackPaginator(
            slack_client=slack_client,
            page_size=settings.slack_page_size,
        ),
        thread_grouper=ThreadGrouper(),
        noise_filter=NoiseFilter(),
        deduplicator=ThreadDeduplicator(),
        checkpoint_store=CheckpointStore(file_path=settings.checkpoint_file),
    )

    channel_name = await slack_client.get_channel_name(channel_id)
    threads = await service.ingest_channel(channel_id)
    counts = await run_in_threadpool(
        persist_threads,
        threads,
        channel_name or channel_id,
    )
    counts["embeddings_indexed"] = await run_in_threadpool(index_missing_embeddings)
    service.commit_checkpoint(channel_id)
    return counts


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduled_task = asyncio.create_task(
        run_ingestion_loop(
            ingest_channel=_ingest_channel,
        )
    )
    slack_bot_task = asyncio.create_task(run_slack_bot())
    try:
        yield
    finally:
        scheduled_task.cancel()
        slack_bot_task.cancel()
        await asyncio.gather(scheduled_task, slack_bot_task, return_exceptions=True)


app = FastAPI(
    title="Unblock Ingestion API",
    version="1.0.0",
    lifespan=lifespan,
)


class IngestionResponse(BaseModel):
    channel_id: str
    threads_saved: int
    messages_saved: int
    embeddings_indexed: int


class StoredMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    author: str | None
    text: str
    posted_at: datetime
    permalink: str | None


class StoredThreadResponse(BaseModel):
    id: str
    channel_id: str
    created_at: datetime
    messages: list[StoredMessageResponse]


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected_key = os.environ.get("INGESTION_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="INGESTION_API_KEY is not configured",
        )
    if x_api_key is None or not compare_digest(x_api_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def index_missing_embeddings() -> int:
    session = SessionLocal()
    try:
        return index_missing_thread_embeddings(session)
    finally:
        session.close()


def search_unblock(request: SearchRequest) -> SearchResponse:
    return RetrievalSearchService().search(request)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok"}


@app.post(
    "/api/v1/ingestion/channels/{channel_id}",
    response_model=IngestionResponse,
    dependencies=[Depends(require_api_key)],
)
async def ingest_channel(channel_id: str) -> IngestionResponse:
    try:
        started_at = perf_counter()
        counts = await _ingest_channel(channel_id)
    except ValidationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Configure SLACK_BOT_TOKEN before starting ingestion",
        ) from exc
    except SlackClientError as exc:
        logger.exception("Slack ingestion failed for channel %s", channel_id)
        raise HTTPException(status_code=502, detail="Slack ingestion failed") from exc
    except (SQLAlchemyError, OSError, RetrievalError) as exc:
        logger.exception("Ingestion storage/indexing failed for channel %s", channel_id)
        raise HTTPException(
            status_code=503,
            detail="Ingestion storage/indexing failed",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected ingestion failure for channel %s", channel_id)
        raise HTTPException(status_code=500, detail="Ingestion failed") from exc

    logger.info(
        "API ingestion completed channel=%s threads=%d messages=%d embeddings=%d duration_seconds=%.3f",
        channel_id,
        counts["threads_saved"],
        counts["messages_saved"],
        counts["embeddings_indexed"],
        perf_counter() - started_at,
    )
    return IngestionResponse(
        channel_id=channel_id,
        **counts,
    )


@app.post(
    "/api/v1/unblock",
    dependencies=[Depends(require_api_key)],
    responses={
        422: {"description": "Query must not be empty"},
        503: {"description": "Unblock retrieval failed"},
    },
)
async def unblock(request: SearchRequest) -> SearchResponse:
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Query must not be empty")

    try:
        return await run_in_threadpool(search_unblock, request)
    except (SQLAlchemyError, RetrievalError) as exc:
        logger.exception("Unblock retrieval failed")
        raise HTTPException(status_code=503, detail="Unblock retrieval failed") from exc


@app.get(
    "/api/v1/threads",
    response_model=list[StoredThreadResponse],
    dependencies=[Depends(require_api_key)],
)
def list_threads(
    channel_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[StoredThreadResponse]:
    query = select(Thread).options(selectinload(Thread.messages))
    if channel_id is not None:
        query = query.where(Thread.channel_id == channel_id)

    threads = db.scalars(
        query.order_by(Thread.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return [_thread_response(thread) for thread in threads]


@app.get(
    "/api/v1/threads/{thread_id}",
    response_model=StoredThreadResponse,
    dependencies=[Depends(require_api_key)],
)
def get_thread(
    thread_id: str,
    db: Session = Depends(get_db),
) -> StoredThreadResponse:
    thread = db.scalar(
        select(Thread)
        .where(Thread.id == thread_id)
        .options(selectinload(Thread.messages))
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return _thread_response(thread)


def _thread_response(thread: Thread) -> StoredThreadResponse:
    return StoredThreadResponse(
        id=thread.id,
        channel_id=thread.channel_id,
        created_at=thread.created_at,
        messages=[
            StoredMessageResponse.model_validate(message)
            for message in sorted(thread.messages, key=lambda item: item.posted_at)
        ],
    )
