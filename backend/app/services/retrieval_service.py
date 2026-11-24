"""Qdrant-backed textbook indexing and strictly scoped page retrieval."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import Text, cast, func, select, text as sql_text

from app.core.config import get_settings
from app.services.ai_gateway import CallContext, embed_via_gateway
from app.db.session import async_session_factory
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus

logger = logging.getLogger(__name__)

_qdrant: AsyncQdrantClient | None = None

_PERSIAN_STOPWORDS = frozenset(
    {
        "از",
        "است",
        "این",
        "آن",
        "با",
        "بر",
        "برای",
        "به",
        "تا",
        "چه",
        "چرا",
        "چطور",
        "چگونه",
        "چی",
        "چیست",
        "دارد",
        "دارند",
        "در",
        "را",
        "رو",
        "شود",
        "شد",
        "می",
        "که",
        "کدام",
        "کند",
        "کنید",
        "لطفا",
        "لطفاً",
        "مفهوم",
        "مفهومی",
        "نیست",
        "ها",
        "های",
        "هست",
        "و",
        "یا",
        "یعنی",
        "یک",
    }
)


def normalize_persian_text(text: str) -> str:
    """Normalize Arabic variants and zero-width characters for consistent lexical search."""
    return (
        text.replace("ي", "ی")
        .replace("ك", "ک")
        .replace("ة", "ه")
        .replace("\u200c", " ")
        .replace("\u0640", "")
    )


def build_lexical_query(query: str) -> str:
    """Extract normalized Persian content terms joined with OR for websearch_to_tsquery."""
    normalized = normalize_persian_text(query).casefold()
    tokens = re.findall(r"[\w۰-۹]+", normalized)
    filtered = [token for token in tokens if len(token) > 1 and token not in _PERSIAN_STOPWORDS]
    chosen = filtered or [token for token in tokens if token]
    deduped = list(dict.fromkeys(chosen))
    return " OR ".join(deduped[:16]) if deduped else normalized.strip()


def page_embedding_text(markdown: str, visual_elements: Sequence[dict[str, Any]] | None) -> str:
    """Combine page text and figure descriptions into the searchable document."""
    parts = [markdown.strip()] if markdown and markdown.strip() else []
    for element in visual_elements or []:
        label = str(element.get("label") or "شکل")
        kind = str(element.get("type") or "")
        description = str(element.get("scientific_description") or "")
        visual = " — ".join(part for part in (label, kind, description) if part)
        if visual:
            parts.append(f"توضیح شکل: {visual}")
    return "\n\n".join(parts)


@dataclass(frozen=True)
class TextbookScope:
    """One permitted book-edition and grade slice, optionally limited to chapters.

    The API validates branch/field applicability before constructing a scope.
    A globally unique book_id is then the hard retrieval boundary across every
    backend; major_code remains only as legacy descriptive metadata.
    """

    book_id: int
    grade_number: int
    major_code: str | None = None
    chapter_numbers: frozenset[int] | None = None


def make_scope_filter(scopes: Sequence[TextbookScope]) -> models.Filter:
    """Qdrant filter: OR over exact book-edition and grade scopes (+ chapters)."""
    if not scopes:
        raise ValueError("at least one textbook scope is required")
    options: list[models.Filter] = []
    for scope in scopes:
        # book_id is the authoritative edition boundary. The legacy major_code
        # payload field cannot represent every branch/field in the normalized K-12 catalogue.
        must: list[models.Condition] = [
            models.FieldCondition(key="grade_number", match=models.MatchValue(value=scope.grade_number)),
            models.FieldCondition(key="book_id", match=models.MatchValue(value=scope.book_id)),
        ]
        if scope.chapter_numbers:
            must.append(
                models.FieldCondition(
                    key="chapter_number",
                    match=models.MatchAny(any=sorted(scope.chapter_numbers)),
                )
            )
        options.append(models.Filter(must=must))
    if len(options) == 1:
        return options[0]
    return models.Filter(should=options)


def make_textbook_filter(
    *, grade_number: int, major_code: str | None, book_id: int | None = None
) -> models.Filter:
    """Build mandatory curriculum filters (grades 1-9 use the `general` key)."""
    conditions = [models.FieldCondition(key="grade_number", match=models.MatchValue(value=grade_number))]
    if book_id is not None:
        # Exact book edition scope supersedes the deprecated major_code field.
        conditions.append(models.FieldCondition(key="book_id", match=models.MatchValue(value=book_id)))
    else:
        conditions.append(
            models.FieldCondition(
                key="major_code", match=models.MatchValue(value=major_code or "general")
            )
        )
    return models.Filter(must=conditions)


def _point_id(book_id: int, pdf_page_index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"iran-ai-tutor:book:{book_id}:pdf-page:{pdf_page_index}"))


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=get_settings().qdrant_url, timeout=20)
    return _qdrant


async def close_qdrant() -> None:
    """Close the process-wide Qdrant connection on application shutdown."""
    global _qdrant
    if _qdrant is not None:
        await _qdrant.close()
        _qdrant = None


async def _ensure_pgvector_table() -> None:
    async with async_session_factory() as session:
        await session.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await session.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS public.book_page_embeddings (
                    id SERIAL PRIMARY KEY,
                    book_page_id INTEGER NOT NULL REFERENCES public.book_pages(id) ON DELETE CASCADE,
                    book_id INTEGER NOT NULL REFERENCES public.books(id) ON DELETE CASCADE,
                    grade_number INTEGER NOT NULL,
                    major_code VARCHAR(64) NOT NULL,
                    embedding_model VARCHAR(255) NOT NULL,
                    embedding vector NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                    CONSTRAINT uq_book_page_embedding UNIQUE (book_page_id)
                )
                """
            )
        )
        await session.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS ix_book_page_embeddings_scope "
                "ON public.book_page_embeddings (book_id, grade_number, major_code)"
            )
        )
        await session.commit()


async def ensure_collection() -> None:
    settings = get_settings()
    if settings.vector_backend == "pgvector":
        await _ensure_pgvector_table()
        return
    client = _get_qdrant()
    if not await client.collection_exists(settings.qdrant_collection):
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=settings.embedding_dimension,
                distance=models.Distance.COSINE,
            ),
        )
    # Exact metadata filters are used for every search; index those payload keys.
    for field_name, field_schema in (
        ("grade_number", models.PayloadSchemaType.INTEGER),
        ("major_code", models.PayloadSchemaType.KEYWORD),
        ("book_id", models.PayloadSchemaType.INTEGER),
        ("chapter_number", models.PayloadSchemaType.INTEGER),
    ):
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


async def index_book(book_id: int, batch_size: int = 32) -> dict[str, int]:
    """Index only accepted (`done`) pages for one curriculum book in Qdrant."""
    if get_settings().demo_mode:
        raise RuntimeError("Qdrant indexing is disabled in demo mode; use a production profile")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is None:
            raise ValueError(f"book {book_id} does not exist")
        grade = await session.get(Grade, book.grade_id)
        if grade is None:
            raise ValueError(f"book {book_id} has no valid grade")
        major = await session.get(Major, book.major_id) if book.major_id is not None else None
        pages = list(
            (
                await session.scalars(
                    select(BookPage)
                    .where(BookPage.book_id == book_id, BookPage.status == PageStatus.done)
                    .order_by(BookPage.pdf_page_index)
                )
            ).all()
        )
        documents: list[tuple[BookPage, str]] = []
        for page in pages:
            text = page_embedding_text(page.markdown_content, page.visual_elements)
            if text:
                documents.append((page, text))

        payload_base = {
            "book_id": book.id,
            "book_title": book.title,
            "grade_number": grade.number,
            "major_code": major.code if major else "general",
        }
        settings = get_settings()
        if settings.vector_backend == "pgvector":
            if not documents:
                return {"book_id": book_id, "indexed_pages": 0, "skipped_empty_pages": len(pages)}
            await _ensure_pgvector_table()
            indexed = 0
            upsert_sql = sql_text(
                """
                INSERT INTO public.book_page_embeddings
                    (book_page_id, book_id, grade_number, major_code, embedding_model, embedding)
                VALUES
                    (:book_page_id, :book_id, :grade_number, :major_code, :embedding_model, CAST(:embedding AS vector))
                ON CONFLICT (book_page_id) DO UPDATE SET
                    book_id = EXCLUDED.book_id,
                    grade_number = EXCLUDED.grade_number,
                    major_code = EXCLUDED.major_code,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding = EXCLUDED.embedding,
                    created_at = now()
                """
            )
            async with async_session_factory() as write_session:
                for start in range(0, len(documents), batch_size):
                    batch = documents[start : start + batch_size]
                    embedding_result = await embed_via_gateway(
                        ctx=CallContext(feature_key="embedding", book_id=book_id),
                        texts=[text for _, text in batch],
                    )
                    vectors = embedding_result.content
                    embedding_model = (
                        getattr(embedding_result, "model_name", None)
                        or settings.embedding_model
                    )
                    for (page, _text), vector in zip(batch, vectors, strict=True):
                        await write_session.execute(
                            upsert_sql,
                            {
                                "book_page_id": page.id,
                                "book_id": book.id,
                                "grade_number": grade.number,
                                "major_code": payload_base["major_code"],
                                "embedding_model": embedding_model,
                                "embedding": json.dumps(vector),
                            },
                        )
                        indexed += 1
                await write_session.commit()
            logger.info("indexed %s pages into pgvector for book %s", indexed, book_id)
            return {
                "book_id": book_id,
                "indexed_pages": indexed,
                "skipped_empty_pages": len(pages) - len(documents),
            }

        points: list[models.PointStruct] = []
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            embedding_result = await embed_via_gateway(
                ctx=CallContext(feature_key="embedding", book_id=book_id),
                texts=[text for _, text in batch],
            )
            vectors = embedding_result.content
            embedding_model = (
                getattr(embedding_result, "model_name", None)
                or settings.embedding_model
            )
            for (page, text), vector in zip(batch, vectors, strict=True):
                points.append(
                    models.PointStruct(
                        id=_point_id(book_id, page.pdf_page_index),
                        vector=vector,
                        payload={
                            **payload_base,
                            "embedding_model": embedding_model,
                            "pdf_page_index": page.pdf_page_index,
                            "printed_page_number": page.printed_page_number,
                            "chapter_number": page.chapter_number,
                            "chapter_title": page.chapter_title,
                            "full_text": text,
                            "markdown_content": page.markdown_content,
                            "visual_elements": page.visual_elements or [],
                        },
                    )
                )

    if not points:
        return {"book_id": book_id, "indexed_pages": 0, "skipped_empty_pages": len(pages)}

    await ensure_collection()
    await _get_qdrant().upsert(
        collection_name=get_settings().qdrant_collection,
        points=points,
        wait=True,
    )
    logger.info("indexed %s pages for book %s", len(points), book_id)
    return {
        "book_id": book_id,
        "indexed_pages": len(points),
        "skipped_empty_pages": len(pages) - len(documents),
    }


def _scope_sql_clause(scopes: Sequence[TextbookScope]):
    """SQLAlchemy OR-clause over exact book editions and grade; branch scope is prevalidated by the API."""
    from sqlalchemy import and_, or_

    clauses = []
    for scope in scopes:
        conditions = [
            Book.id == scope.book_id,
            Book.status == BookStatus.ready,
            Grade.number == scope.grade_number,
        ]
        if scope.chapter_numbers:
            conditions.append(BookPage.chapter_number.in_(sorted(scope.chapter_numbers)))
        clauses.append(and_(*conditions))
    return or_(*clauses)


async def _uses_postgresql_database() -> bool:
    """Detect the active SQL dialect instead of assuming demo_mode means SQLite."""
    async with async_session_factory() as session:
        get_bind = getattr(session, "get_bind", None)
        # Lightweight fake sessions in query-construction tests predate
        # dialect introspection and represent the configured production DB.
        if not callable(get_bind):
            return True
        bind = get_bind()
        return bool(bind is not None and bind.dialect.name == "postgresql")


async def _search_postgres_scopes(
    query: str, *, scopes: Sequence[TextbookScope], limit: int
) -> list[dict[str, Any]]:
    """Keyword/full-text channel over approved textbook pages.

    Demo mode uses a small deterministic token-overlap scorer so the project can
    be explored with SQLite and no PostgreSQL/Qdrant/embedding credentials.
    """
    scope_clause = _scope_sql_clause(scopes)
    if get_settings().demo_mode or not await _uses_postgresql_database():
        def _terms(value: str) -> set[str]:
            normalized = normalize_persian_text(value).casefold()
            tokens = re.findall(r"[\w۰-۹]+", normalized)
            filtered = {t for t in tokens if len(t) > 1 and t not in _PERSIAN_STOPWORDS}
            return filtered or set(tokens)

        query_terms = _terms(query)
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(BookPage, Book.title, Grade.number, func.coalesce(Major.code, "general"))
                    .join(Book, BookPage.book_id == Book.id)
                    .join(Grade, Book.grade_id == Grade.id)
                    .outerjoin(Major, Book.major_id == Major.id)
                    .where(scope_clause, BookPage.status == PageStatus.done)
                    .order_by(BookPage.pdf_page_index.asc())
                )
            ).all()
        matches: list[dict[str, Any]] = []
        for page, title, grade, major in rows:
            full_text = page_embedding_text(page.markdown_content, page.visual_elements)
            page_terms = _terms(full_text)
            overlap = len(query_terms & page_terms)
            if overlap:
                matches.append(
                    {
                        "book_id": page.book_id,
                        "book_title": title,
                        "grade_number": grade,
                        "major_code": major,
                        "pdf_page_index": page.pdf_page_index,
                        "printed_page_number": page.printed_page_number,
                        "chapter_number": page.chapter_number,
                        "chapter_title": page.chapter_title,
                        "full_text": full_text,
                        "markdown_content": page.markdown_content,
                        "visual_elements": page.visual_elements or [],
                        "lexical_score": float(overlap),
                    }
                )
        return sorted(matches, key=lambda item: item["lexical_score"], reverse=True)[:limit]

    raw_doc = func.concat(
        func.coalesce(BookPage.markdown_content, ""),
        " ",
        cast(BookPage.visual_elements, Text),
    )
    normalized_doc = func.replace(
        func.replace(func.replace(raw_doc, "ي", "ی"), "ك", "ک"),
        "\u200c",
        " ",
    )
    ts_document = func.to_tsvector("simple", normalized_doc)
    lexical_query = build_lexical_query(query)
    if not lexical_query:
        return []
    ts_query = func.websearch_to_tsquery("simple", lexical_query)
    rank = func.ts_rank_cd(ts_document, ts_query).label("lexical_score")

    async with async_session_factory() as session:
        statement = (
            select(BookPage, Book.title, Grade.number, func.coalesce(Major.code, "general"), rank)
            .join(Book, BookPage.book_id == Book.id)
            .join(Grade, Book.grade_id == Grade.id)
            .outerjoin(Major, Book.major_id == Major.id)
            .where(scope_clause, BookPage.status == PageStatus.done, ts_document.op("@@")(ts_query))
            .order_by(rank.desc(), BookPage.pdf_page_index.asc())
            .limit(limit)
        )
        rows = (await session.execute(statement)).all()

    matches: list[dict[str, Any]] = []
    for page, title, grade, major, lexical_score in rows:
        full_text = page_embedding_text(page.markdown_content, page.visual_elements)
        matches.append(
            {
                "book_id": page.book_id,
                "book_title": title,
                "grade_number": grade,
                "major_code": major,
                "pdf_page_index": page.pdf_page_index,
                "printed_page_number": page.printed_page_number,
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "full_text": full_text,
                "markdown_content": page.markdown_content,
                "visual_elements": page.visual_elements or [],
                "lexical_score": float(lexical_score),
            }
        )
    return matches


async def _search_postgres(
    query: str, *, grade_number: int, major_code: str | None, book_id: int, limit: int
) -> list[dict[str, Any]]:
    """Keyword/full-text channel over approved textbook pages.

    The exact book id is the authoritative edition boundary. major_code remains
    in the signature for compatibility but is not a retrieval filter.
    """
    if get_settings().demo_mode or not await _uses_postgresql_database():

        def _terms(value: str) -> set[str]:
            normalized = normalize_persian_text(value).casefold()
            tokens = re.findall(r"[\w۰-۹]+", normalized)
            filtered = {t for t in tokens if len(t) > 1 and t not in _PERSIAN_STOPWORDS}
            return filtered or set(tokens)

        query_terms = _terms(query)
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(BookPage, Book.title, Grade.number, func.coalesce(Major.code, "general"))
                    .join(Book, BookPage.book_id == Book.id)
                    .join(Grade, Book.grade_id == Grade.id)
                    .outerjoin(Major, Book.major_id == Major.id)
                    .where(
                        Book.id == book_id,
                        Grade.number == grade_number,
                        Book.status == BookStatus.ready,
                        BookPage.status == PageStatus.done,
                    )
                    .order_by(BookPage.pdf_page_index.asc())
                )
            ).all()
        matches: list[dict[str, Any]] = []
        for page, title, grade, major in rows:
            full_text = page_embedding_text(page.markdown_content, page.visual_elements)
            page_terms = _terms(full_text)
            overlap = len(query_terms & page_terms)
            if overlap:
                matches.append(
                    {
                        "book_id": page.book_id,
                        "book_title": title,
                        "grade_number": grade,
                        "major_code": major,
                        "pdf_page_index": page.pdf_page_index,
                        "printed_page_number": page.printed_page_number,
                        "chapter_number": page.chapter_number,
                        "chapter_title": page.chapter_title,
                        "full_text": full_text,
                        "markdown_content": page.markdown_content,
                        "visual_elements": page.visual_elements or [],
                        "lexical_score": float(overlap),
                    }
                )
        return sorted(matches, key=lambda item: item["lexical_score"], reverse=True)[:limit]

    raw_doc = func.concat(
        func.coalesce(BookPage.markdown_content, ""),
        " ",
        cast(BookPage.visual_elements, Text),
    )
    normalized_doc = func.replace(
        func.replace(func.replace(raw_doc, "ي", "ی"), "ك", "ک"),
        "\u200c",
        " ",
    )
    ts_document = func.to_tsvector("simple", normalized_doc)
    lexical_query = build_lexical_query(query)
    if not lexical_query:
        return []
    ts_query = func.websearch_to_tsquery("simple", lexical_query)
    rank = func.ts_rank_cd(ts_document, ts_query).label("lexical_score")

    async with async_session_factory() as session:
        statement = (
            select(BookPage, Book.title, Grade.number, func.coalesce(Major.code, "general"), rank)
            .join(Book, BookPage.book_id == Book.id)
            .join(Grade, Book.grade_id == Grade.id)
            .outerjoin(Major, Book.major_id == Major.id)
            .where(
                Book.id == book_id,
                Grade.number == grade_number,
                Book.status == BookStatus.ready,
                BookPage.status == PageStatus.done,
                ts_document.op("@@")(ts_query),
            )
            .order_by(rank.desc(), BookPage.pdf_page_index.asc())
            .limit(limit)
        )
        rows = (await session.execute(statement)).all()

    matches: list[dict[str, Any]] = []
    for page, title, grade, major, lexical_score in rows:
        full_text = page_embedding_text(page.markdown_content, page.visual_elements)
        matches.append(
            {
                "book_id": page.book_id,
                "book_title": title,
                "grade_number": grade,
                "major_code": major,
                "pdf_page_index": page.pdf_page_index,
                "printed_page_number": page.printed_page_number,
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "full_text": full_text,
                "markdown_content": page.markdown_content,
                "visual_elements": page.visual_elements or [],
                "lexical_score": float(lexical_score),
            }
        )
    return matches


def merge_hybrid_results(
    vector_results: Sequence[dict[str, Any]],
    lexical_results: Sequence[dict[str, Any]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse ranked vector and lexical results using reciprocal-rank fusion."""
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    for channel, results in (("vector", vector_results), ("lexical", lexical_results)):
        for rank, result in enumerate(results, start=1):
            identity = (result.get("book_id"), result.get("pdf_page_index"))
            if identity not in merged:
                merged[identity] = {key: value for key, value in result.items() if key != "score"}
                merged[identity]["score"] = 0.0
            record = merged[identity]
            for key, value in result.items():
                if key != "score" and value is not None:
                    record.setdefault(key, value)
            record[f"{channel}_rank"] = rank
            record[f"{channel}_score"] = result.get("score", result.get("lexical_score"))
            record["score"] += 1.0 / (rrf_k + rank)

    return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:top_k]


async def _search_pgvector_scopes(
    query: str, *, scopes: Sequence[TextbookScope], limit: int,
    route_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    embedding_result = await embed_via_gateway(
        ctx=CallContext(feature_key="embedding_query", book_id=scopes[0].book_id),
        texts=[query],
        session=route_session,
    )
    vector = embedding_result.content[0]
    embedding_model = (
        getattr(embedding_result, "model_name", None) or get_settings().embedding_model
    )
    params: dict[str, Any] = {
        "query_vector": json.dumps(vector),
        "embedding_model": embedding_model,
        "limit": limit,
    }
    clauses: list[str] = []
    for index, scope in enumerate(scopes):
        clause = f"(e.book_id = :book_id_{index} AND e.grade_number = :grade_{index}"
        params[f"book_id_{index}"] = scope.book_id
        params[f"grade_{index}"] = scope.grade_number
        if scope.chapter_numbers:
            clause += f" AND bp.chapter_number = ANY(:chapters_{index})"
            params[f"chapters_{index}"] = sorted(scope.chapter_numbers)
        clauses.append(clause + ")")
    statement = sql_text(
        """
        SELECT
            bp.book_id,
            b.title AS book_title,
            e.grade_number,
            e.major_code,
            bp.pdf_page_index,
            bp.printed_page_number,
            bp.chapter_number,
            bp.chapter_title,
            bp.markdown_content,
            bp.visual_elements,
            (1.0 - (e.embedding <=> CAST(:query_vector AS vector))) AS score
        FROM public.book_page_embeddings e
        JOIN public.book_pages bp ON bp.id = e.book_page_id
        JOIN public.books b ON b.id = bp.book_id
        WHERE ("""
        + " OR ".join(clauses)
        + """)
          AND bp.status = 'done'
          AND b.status = 'ready'
          AND e.embedding_model = :embedding_model
          AND (1.0 - (e.embedding <=> CAST(:query_vector AS vector))) >= 0.15
        ORDER BY e.embedding <=> CAST(:query_vector AS vector) ASC, bp.pdf_page_index ASC
        LIMIT :limit
        """
    )
    async with async_session_factory() as session:
        rows = (await session.execute(statement, params)).mappings().all()

    results: list[dict[str, Any]] = []
    for row in rows:
        visuals = row["visual_elements"] or []
        markdown = row["markdown_content"] or ""
        results.append(
            {
                "book_id": row["book_id"],
                "book_title": row["book_title"],
                "grade_number": row["grade_number"],
                "major_code": row["major_code"],
                "pdf_page_index": row["pdf_page_index"],
                "printed_page_number": row["printed_page_number"],
                "chapter_number": row["chapter_number"],
                "chapter_title": row["chapter_title"],
                "full_text": page_embedding_text(markdown, visuals),
                "markdown_content": markdown,
                "visual_elements": visuals,
                "score": float(row["score"]),
            }
        )
    return results


async def _search_pgvector(
    query: str,
    *,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    limit: int,
    route_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    embedding_result = await embed_via_gateway(
        ctx=CallContext(feature_key="embedding_query", book_id=book_id),
        texts=[query],
        session=route_session,
    )
    vector = embedding_result.content[0]
    embedding_model = (
        getattr(embedding_result, "model_name", None) or get_settings().embedding_model
    )
    statement = sql_text(
        """
        SELECT
            bp.book_id,
            b.title AS book_title,
            e.grade_number,
            e.major_code,
            bp.pdf_page_index,
            bp.printed_page_number,
            bp.chapter_number,
            bp.chapter_title,
            bp.markdown_content,
            bp.visual_elements,
            (1.0 - (e.embedding <=> CAST(:query_vector AS vector))) AS score
        FROM public.book_page_embeddings e
        JOIN public.book_pages bp ON bp.id = e.book_page_id
        JOIN public.books b ON b.id = bp.book_id
        WHERE e.book_id = :book_id
          AND e.grade_number = :grade_number
          AND bp.status = 'done'
          AND b.status = 'ready'
          AND e.embedding_model = :embedding_model
          AND (1.0 - (e.embedding <=> CAST(:query_vector AS vector))) >= 0.15
        ORDER BY e.embedding <=> CAST(:query_vector AS vector) ASC, bp.pdf_page_index ASC
        LIMIT :limit
        """
    )
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                statement,
                {
                    "query_vector": json.dumps(vector),
                    "book_id": book_id,
                    "grade_number": grade_number,
                                "embedding_model": embedding_model,
                    "limit": limit,
                },
            )
        ).mappings().all()

    results: list[dict[str, Any]] = []
    for row in rows:
        visuals = row["visual_elements"] or []
        markdown = row["markdown_content"] or ""
        results.append(
            {
                "book_id": row["book_id"],
                "book_title": row["book_title"],
                "grade_number": row["grade_number"],
                "major_code": row["major_code"],
                "pdf_page_index": row["pdf_page_index"],
                "printed_page_number": row["printed_page_number"],
                "chapter_number": row["chapter_number"],
                "chapter_title": row["chapter_title"],
                "full_text": page_embedding_text(markdown, visuals),
                "markdown_content": markdown,
                "visual_elements": visuals,
                "score": float(row["score"]),
            }
        )
    return results


async def _filter_qdrant_points(
    points: Sequence[Any],
    *,
    scopes: Sequence[TextbookScope],
    expected_embedding_model: str | None = None,
) -> list[dict[str, Any]]:
    """Reconcile vector hits with the current, approved textbook page rows.

    Qdrant is an index, not the source of truth. A page may have been edited or
    moved to needs_review since it was indexed. Keep a vector hit only when the
    corresponding database page is still approved and its indexed text exactly
    matches the current text; return the current database metadata/content.
    """
    from sqlalchemy import and_, or_

    requested: set[tuple[int, int]] = set()
    point_payloads: list[tuple[Any, dict[str, Any], tuple[int, int]]] = []
    for point in points:
        payload = dict(getattr(point, "payload", None) or {})
        book_id = payload.get("book_id")
        page_index = payload.get("pdf_page_index")
        if (
            isinstance(book_id, bool)
            or not isinstance(book_id, int)
            or book_id <= 0
            or isinstance(page_index, bool)
            or not isinstance(page_index, int)
            or page_index < 0
        ):
            continue
        identity = (book_id, page_index)
        requested.add(identity)
        point_payloads.append((point, payload, identity))

    if not requested:
        return []

    identity_clause = or_(
        *(
            and_(BookPage.book_id == book_id, BookPage.pdf_page_index == page_index)
            for book_id, page_index in requested
        )
    )
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    BookPage,
                    Book.title,
                    Grade.number,
                    func.coalesce(Major.code, "general"),
                )
                .join(Book, BookPage.book_id == Book.id)
                .join(Grade, Book.grade_id == Grade.id)
                .outerjoin(Major, Book.major_id == Major.id)
                .where(
                    _scope_sql_clause(scopes),
                    identity_clause,
                    BookPage.status == PageStatus.done,
                )
            )
        ).all()

    current: dict[tuple[int, int], tuple[BookPage, str, int, str]] = {
        (page.book_id, page.pdf_page_index): (page, title, grade_number, major_code)
        for page, title, grade_number, major_code in rows
    }

    verified: list[dict[str, Any]] = []
    for point, payload, identity in point_payloads:
        record = current.get(identity)
        if record is None:
            continue
        page, title, grade_number, major_code = record
        if expected_embedding_model and payload.get("embedding_model") != expected_embedding_model:
            continue
        current_text = page_embedding_text(page.markdown_content or "", page.visual_elements or [])
        # Old or stale payloads without an exact source snapshot must be re-indexed.
        if not current_text or payload.get("full_text") != current_text:
            continue
        verified.append(
            {
                "book_id": page.book_id,
                "book_title": title,
                "grade_number": grade_number,
                "major_code": major_code,
                "pdf_page_index": page.pdf_page_index,
                "printed_page_number": page.printed_page_number,
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "full_text": current_text,
                "markdown_content": page.markdown_content,
                "visual_elements": page.visual_elements or [],
                "score": float(point.score),
            }
        )
    return verified


async def _search_qdrant_scopes(
    query: str, *, scopes: Sequence[TextbookScope], limit: int,
    route_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    embedding_result = await embed_via_gateway(
        ctx=CallContext(feature_key="embedding_query", book_id=scopes[0].book_id),
        texts=[query],
        session=route_session,
    )
    vector = embedding_result.content[0]
    settings = get_settings()
    expected_embedding_model = (
        getattr(embedding_result, "model_name", None) or settings.embedding_model
    )
    scope_filter = make_scope_filter(scopes)
    model_condition = models.FieldCondition(
        key="embedding_model",
        match=models.MatchValue(value=expected_embedding_model),
    )
    # Apply model identity before top-k selection; otherwise stale vectors can
    # occupy the candidate window and hide usable points from the current model.
    if scope_filter.must:
        query_filter = models.Filter(
            must=[*scope_filter.must, model_condition],
            must_not=scope_filter.must_not,
        )
    else:
        query_filter = models.Filter(
            must=[model_condition],
            should=scope_filter.should,
            must_not=scope_filter.must_not,
        )
    response = await _get_qdrant().query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
        score_threshold=0.15,
    )
    return await _filter_qdrant_points(
        response.points,
        scopes=scopes,
        expected_embedding_model=expected_embedding_model,
    )


async def _search_qdrant(
    query: str,
    *,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    limit: int,
    route_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    embedding_result = await embed_via_gateway(
        ctx=CallContext(feature_key="embedding_query", book_id=book_id),
        texts=[query],
        session=route_session,
    )
    vector = embedding_result.content[0]
    settings = get_settings()
    expected_embedding_model = (
        getattr(embedding_result, "model_name", None) or settings.embedding_model
    )
    textbook_filter = make_textbook_filter(
        grade_number=grade_number, major_code=major_code, book_id=book_id
    )
    query_filter = models.Filter(
        must=[
            *(textbook_filter.must or []),
            models.FieldCondition(
                key="embedding_model",
                match=models.MatchValue(value=expected_embedding_model),
            ),
        ],
        must_not=textbook_filter.must_not,
    )
    response = await _get_qdrant().query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
        score_threshold=0.15,
    )
    return await _filter_qdrant_points(
        response.points,
        scopes=[
            TextbookScope(
                book_id=book_id,
                grade_number=grade_number,
                major_code=major_code,
            )
        ],
        expected_embedding_model=expected_embedding_model,
    )


async def search_textbook_scopes(
    query: str,
    *,
    scopes: Sequence[TextbookScope],
    top_k: int = 5,
    route_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search across one or more exact (book, grade[, chapters]) scopes.

    PostgreSQL's `simple` full-text search and the vector backend are fused with
    reciprocal-rank fusion. If the vector provider/backend is unavailable,
    approved PostgreSQL lexical matches remain usable.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")
    if not scopes:
        raise ValueError("at least one textbook scope is required")

    candidate_limit = min(max(top_k * 4, 20), 100)
    lexical_results = await _search_postgres_scopes(query, scopes=scopes, limit=candidate_limit)

    if get_settings().demo_mode:
        vector_results = []
    else:
        try:
            if get_settings().vector_backend == "pgvector":
                vector_results = await _search_pgvector_scopes(
                    query, scopes=scopes, limit=candidate_limit, route_session=route_session
                )
            else:
                vector_results = await _search_qdrant_scopes(
                    query, scopes=scopes, limit=candidate_limit, route_session=route_session
                )
        except Exception:  # noqa: BLE001 - lexical fallback is intentional
            logger.exception("vector search unavailable; using PostgreSQL lexical results")
            vector_results = []

    return merge_hybrid_results(vector_results, lexical_results, top_k=top_k)


async def search_textbook(
    query: str,
    *,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    top_k: int = 5,
    route_session: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search, always scoped to the exact selected grade and book edition.

    PostgreSQL's `simple` full-text search and Qdrant vector search are fused
    with reciprocal-rank fusion. If the vector provider/Qdrant is unavailable,
    approved PostgreSQL lexical matches remain usable.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")

    candidate_limit = min(max(top_k * 4, 20), 100)
    lexical_results = await _search_postgres(
        query,
        grade_number=grade_number,
        major_code=major_code,
        book_id=book_id,
        limit=candidate_limit,
    )

    if get_settings().demo_mode:
        vector_results = []
    else:
        try:
            if get_settings().vector_backend == "pgvector":
                vector_results = await _search_pgvector(
                    query,
                    grade_number=grade_number,
                    major_code=major_code,
                    book_id=book_id,
                    limit=candidate_limit,
                    route_session=route_session,
                )
            else:
                vector_results = await _search_qdrant(
                    query,
                    grade_number=grade_number,
                    major_code=major_code,
                    book_id=book_id,
                    limit=candidate_limit,
                    route_session=route_session,
                )
        except Exception:  # noqa: BLE001 - lexical fallback is intentional
            logger.exception("vector search unavailable; using PostgreSQL lexical results")
            vector_results = []

    return merge_hybrid_results(
        vector_results, lexical_results, top_k=top_k
    )


async def probe_qdrant(url: str | None = None, collection: str | None = None) -> dict[str, Any]:
    """Live connectivity probe for the Qdrant backend (`POST /admin/settings/test-vector`).

    Owns the only direct Qdrant HTTP call outside the client library, keeping the API
    layer free of transport code.
    """
    import httpx

    settings = get_settings()
    base = (url or settings.qdrant_url or "").strip().rstrip("/")
    target = (collection or settings.qdrant_collection or "").strip()
    started = time.perf_counter()

    def _elapsed() -> int:
        return max(1, int(round((time.perf_counter() - started) * 1000)))

    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "ok": False,
            "backend": "qdrant",
            "latency_ms": _elapsed(),
            "detail": "آدرس Qdrant معتبر نیست.",
            "invalid_url": True,
        }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(f"{base}/collections")
            latency_ms = _elapsed()
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "backend": "qdrant",
                    "latency_ms": latency_ms,
                    "detail": f"پاسخ غیرموفق از Qdrant (HTTP {response.status_code})",
                }
            payload = response.json()
            collections = [
                item.get("name")
                for item in ((payload.get("result") or {}).get("collections") or [])
                if isinstance(item, dict)
            ]
            return {
                "ok": True,
                "backend": "qdrant",
                "latency_ms": latency_ms,
                "detail": (
                    f"اتصال به Qdrant برقرار شد؛ مجموعه «{target}» "
                    + (
                        "یافت شد."
                        if target in collections
                        else "هنوز ایجاد نشده (با اولین ایندکس ساخته می‌شود)."
                    )
                ),
                "collection_info": {
                    "collections": collections,
                    "target_exists": target in collections,
                },
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "backend": "qdrant",
            "latency_ms": _elapsed(),
            "detail": f"عدم دسترسی به Qdrant در {base}: {str(exc)[:180]}",
        }
