import json
from app.scrapers.article import get_article_text
from app.scrapers.rss import get_latest_urls
from app.scrapers.youtube import get_newest_video, get_video_transcript
from app.services.embeddings import calculate_similarity, get_embedding
from app.services.llm import extract_structured_data
from app.services.pacing import GroupedCallPacer
from app.database.db import connect_database, setup_database
from app.config import RSS_SOURCES, YOUTUBE_SOURCE

SIMILARITY_THRESHOLD = 0.75
RSS_ENTRY_LIMIT = 2


class EvidenceExtractionCallPacer(GroupedCallPacer):
    def __init__(self, *, sleep_fn=None):
        arguments = {"log_prefix": "EVIDENCE_EXTRACTION"}
        if sleep_fn is not None:
            arguments["sleep_fn"] = sleep_fn
        super().__init__(**arguments)


def find_semantic_match(
        new_embedding: list[float],
) -> tuple[int, str, float] | None:
    """Returns the most similar stored story when it crosses the threshold."""

    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, headline, embedding
        FROM items
        WHERE embedding IS NOT NULL
    """)
    rows = cursor.fetchall()
    conn.close()

    best_match = None

    for db_id, db_headline, db_embedding_str in rows:
        db_embedding = json.loads(db_embedding_str)
        score = calculate_similarity(new_embedding, db_embedding)

        if score >= SIMILARITY_THRESHOLD:
            if best_match is None or score > best_match[2]:
                best_match = (db_id, db_headline, score)

    return best_match


def _is_exact_duplicate(cursor, url: str) -> bool:
    cursor.execute("SELECT id FROM items WHERE url=?", (url,))
    return cursor.fetchone() is not None


def _process_source_text(
        cursor,
        conn,
        *,
        source,
        url: str,
        source_text: str,
        pacer: GroupedCallPacer,
) -> None:
    pacer.before_call()
    data = extract_structured_data(source_text)
    if not data or "error" in data:
        print("AI model failed to extract data. Skipping.")
        return

    summary = data.get("summary", "")
    headline = data.get("headline", "")
    embedding_vector = get_embedding(summary)
    semantic_match = find_semantic_match(embedding_vector)

    if semantic_match:
        _, matched_headline, score = semantic_match
        print(
            f"  -> Related coverage detected: '{matched_headline}' "
            f"(similarity {score:.2f}). Saving for clustering."
        )
    else:
        print(f"  -> New story detected: {headline}. Saving to database...")

    cursor.execute("""
        INSERT INTO items (
            url, source_name, source_category,
            headline, summary, full_text,
            entities,
            evidence_json,
            category,
            importance_score,
            embedding
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url, source.name, source.category,
            headline, summary, source_text,
            json.dumps(data.get("entities", [])),
            json.dumps(data.get("key_facts", [])),
            data.get("category", ""),
            data.get("importance_score", 0),
            json.dumps(embedding_vector),
        ),
    )
    conn.commit()


def run_ingestion(pacer: GroupedCallPacer | None = None):
    setup_database()
    pacer = pacer or EvidenceExtractionCallPacer()

    conn = connect_database()
    cursor = conn.cursor()

    for source in RSS_SOURCES:
        if not source.enabled:
            continue

        latest_links = get_latest_urls(source.url, RSS_ENTRY_LIMIT)

        for link in latest_links:
            if _is_exact_duplicate(cursor, link):
                print("  -> Already processed this exact URL. Skipping.")
                continue

            article_text = get_article_text(link)
            if not article_text:
                continue

            _process_source_text(
                cursor,
                conn,
                source=source,
                url=link,
                source_text=article_text,
                pacer=pacer,
            )

    newest_video = get_newest_video(YOUTUBE_SOURCE.url)
    if newest_video is not None:
        if _is_exact_duplicate(cursor, newest_video.url):
            print("  -> Already processed this exact YouTube URL. Skipping.")
        else:
            transcript = get_video_transcript(newest_video.video_id)
            if transcript:
                _process_source_text(
                    cursor,
                    conn,
                    source=YOUTUBE_SOURCE,
                    url=newest_video.url,
                    source_text=transcript,
                    pacer=pacer,
                )

    conn.close()


def run_daily_pipeline():
    """Backward-compatible name for the direct ingestion script."""
    run_ingestion()


if __name__ == "__main__":
    run_daily_pipeline()
