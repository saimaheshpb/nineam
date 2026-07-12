import json
import time
from app.scrapers.article import get_article_text
from app.scrapers.rss import get_latest_urls
from app.services.embeddings import calculate_similarity, get_embedding
from app.services.llm import extract_structured_data
from app.database.db import connect_database, setup_database
from app.config import RSS_SOURCES

SIMILARITY_THRESHOLD = 0.75


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


def run_daily_pipeline():
    setup_database()

    conn = connect_database()
    cursor = conn.cursor()

    for source in RSS_SOURCES:
        if not source.enabled:
            continue

        latest_links = get_latest_urls(source.url, 1)

        for link in latest_links:
            # 1. Check if we've already processed this exact URL (Idempotency)
            cursor.execute("SELECT  id FROM items WHERE url=?", (link,))
            if cursor.fetchone():
                print("  -> Already processed this exact URL. Skipping.")
                continue

            # 2. Scrape the text
            article_text = get_article_text(link)
            if not article_text:
                continue

            # 3. Force the AI to give us structured JSON data
            data = extract_structured_data(article_text)
            if not data or "error" in data:
                print("AI model failed to extract data. Skipping.")
                continue

            summary = data.get("summary", "")
            headline = data.get("headline", "")

            # 4. Turn summary into vector
            embedding_vector = get_embedding(summary)

            # 5. Check if it's a semantic duplicate of an older story
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
                               link, source.name, source.category,
                               headline, summary, article_text,
                               json.dumps(data.get("entities", [])),
                               json.dumps(data.get("key_facts", [])),
                               data.get("category", ""),
                               data.get("importance_score", 0),
                               json.dumps(embedding_vector),
                           )
                           )

            conn.commit()

            print("  -> Sleeping for 12 seconds to respect API rate limits...")
            time.sleep(12)

    conn.close()


if __name__ == "__main__":
    run_daily_pipeline()
