import json
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
import argparse
from app.database.db import connect_database
from app.services.clustering import ArticleForClustering, cluster_articles

INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def parse_edition_date() -> date:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--edition-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Edition date in YYYY-MM-DD format.",
    )
    return parser.parse_args().edition_date


def edition_window_utc(edition_date: date) -> tuple[str, str]:
    window_end = datetime.combine(
        edition_date,
        time(9, 0),
        tzinfo=INDIA_TIMEZONE,
    ).astimezone(timezone.utc)

    window_start = window_end - timedelta(days=1)

    return (
        window_start.strftime("%Y-%m-%d %H:%M:%S"),
        window_end.strftime("%Y-%m-%d %H:%M:%S"),
    )


def load_articles(window_start: str, window_end: str) -> list[ArticleForClustering]:
    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, source_name, headline, url, embedding, importance_score
        FROM items
        WHERE embedding IS NOT NULL
          AND processed_at >= ?
          AND processed_at < ?
    """, (window_start, window_end))

    rows = cursor.fetchall()
    conn.close()

    articles = []

    for row in rows:
        article_id, source_name, headline, url, embedding_json, importance_score = row

        articles.append(
            ArticleForClustering(
                id=article_id,
                source_name=source_name,
                headline=headline,
                url=url,
                embedding=json.loads(embedding_json),
                importance_score=importance_score or 0,
            )
        )

    return articles


def save_clusters(clusters, run_date: str) -> None:
    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
            DELETE FROM story_cluster_items
            WHERE cluster_id IN (
                SELECT id
                FROM story_clusters
                WHERE run_date = ?
            )
        """, (run_date,))

    cursor.execute("""
            DELETE FROM story_clusters
            WHERE run_date = ?
        """, (run_date,))

    for cluster in clusters:
        cursor.execute("""
            INSERT INTO story_clusters (
                run_date,
                representative_headline,
                cluster_size,
                rank_score
            )
            VALUES (?, ?, ?, ?)
        """, (
            run_date,
            cluster.representative_headline,
            cluster.size,
            cluster.rank_score
        ))

        cluster_id = cursor.lastrowid

        for article in cluster.articles:
            cursor.execute("""
                INSERT INTO story_cluster_items (
                    cluster_id,
                    item_id,
                    similarity_to_representative
                )
                VALUES (?, ?, ?)
            """, (
                cluster_id,
                article.id,
                None,
            ))

    conn.commit()
    conn.close()


def main():
    edition_date = parse_edition_date()
    window_start, window_end = edition_window_utc(edition_date)

    articles = load_articles(window_start, window_end)
    clusters = cluster_articles(articles)
    save_clusters(clusters, edition_date.isoformat())

    print(f"\nLoaded {len(articles)} articles")
    print(f"Created {len(clusters)} story clusters\n")
    print("Saved clusters to database\n")

    for index, cluster in enumerate(clusters, start=1):
        print(f"Cluster {index} - {cluster.size} article(s) - score {cluster.rank_score:.2f}")
        print(f"Representative: {cluster.representative_headline}")

        for article in cluster.articles:
            print(f"- {article.source_name}: {article.headline}")
            print(f"  {article.url}")

        print()


if __name__ == "__main__":
    main()
