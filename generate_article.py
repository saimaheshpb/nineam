import json
from datetime import date
import argparse
from app.database.db import connect_database

from app.services.llm import (
    generate_daily_article,
    GENERATOR_MODEL,
    GENERATION_PROMPT_VERSION,
)


def parse_edition_date() -> date:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--edition-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Edition date in YYYY-MM-DD format.",
    )
    return parser.parse_args().edition_date


def load_top_clusters(edition_date: str, limit: int = 5, ) -> list[dict]:
    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, representative_headline, cluster_size, rank_score
        FROM story_clusters
        WHERE run_date = ?
        ORDER BY rank_score DESC
        LIMIT ?
    """, (edition_date, limit))

    cluster_rows = cursor.fetchall()

    clusters = []

    for cluster_id, representative_headline, cluster_size, rank_score in cluster_rows:
        cursor.execute("""
            SELECT
                items.id,
                items.source_name,
                items.headline,
                items.summary,
                items.evidence_json,
                items.url,
                items.importance_score
            FROM story_cluster_items
            JOIN items ON items.id = story_cluster_items.item_id
            WHERE story_cluster_items.cluster_id = ?
            ORDER BY items.importance_score DESC, items.id
        """, (cluster_id,))

        article_rows = cursor.fetchall()
        articles = []

        for (article_id, source_name, headline, summary, evidence_json,
             url, importance_score) in article_rows:
            evidence = json.loads(evidence_json) if evidence_json else []
            articles.append({
                "id": article_id,
                "source_name": source_name,
                "headline": headline,
                "summary": summary,
                "evidence": evidence,
                "url": url,
                "importance_score": importance_score,
            })

        clusters.append({
            "id": cluster_id,
            "representative_headline": representative_headline,
            "cluster_size": cluster_size,
            "rank_score": rank_score,
            "articles": articles,
        })

    conn.close()

    return clusters


def build_article_brief(clusters: list[dict]) -> tuple[str, dict[str, dict]]:
    sections = []
    citation_map = {}

    for index, cluster in enumerate(clusters, start=1):
        lines = [
            f"STORY CLUSTER {index}",
            f"Representative headline: {cluster['representative_headline']}",
            f"Rank score: {cluster['rank_score']:.2f}",
        ]

        for article in cluster["articles"]:
            lines.extend([
                "",
                f"Source: {article['source_name']}",
                f"Headline: {article['headline']}",
                f"URL: {article['url']}",
                "Evidence:",
            ])

            for fact_number, fact in enumerate(article["evidence"], start=1):
                citation_id = f"S{article['id']}-F{fact_number}"

                citation_map[citation_id] = {
                    "item_id": article["id"],
                    "fact_number": fact_number,
                    "source_name": article["source_name"],
                    "headline": article["headline"],
                    "url": article["url"],
                    "claim": fact["claim"],
                    "supporting_excerpt": fact["supporting_excerpt"],
                }

                lines.extend([
                    f"[{citation_id}]",
                    f"Claim: {fact['claim']}",
                    f"Supporting excerpt: {fact['supporting_excerpt']}",
                ])

        sections.append("\n".join(lines))

    return "\n\n---\n\n".join(sections), citation_map


def save_generated_article(edition_date: str, generated_article: dict,
                           clusters: list[dict], citation_map: dict[str, dict], ) -> None:
    sources = []

    for cluster in clusters:
        for article in cluster["articles"]:
            sources.append({
                "source_name": article["source_name"],
                "headline": article["headline"],
                "url": article["url"]
            })

    cluster_ids = [cluster["id"] for cluster in clusters]

    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO generated_articles (
            edition_date,
            title,
            body,
            sources_json,
            cluster_ids_json,
            citation_map_json,
            generator_model,
            generation_prompt_version,
            eval_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(edition_date) DO UPDATE SET
            title = excluded.title,
            body = excluded.body,
            sources_json = excluded.sources_json,
            cluster_ids_json = excluded.cluster_ids_json,
            citation_map_json = excluded.citation_map_json,
            generator_model = excluded.generator_model,
            generation_prompt_version = excluded.generation_prompt_version,
            eval_status = 'pending'
    """, (
        edition_date,
        generated_article["title"],
        generated_article["body"],
        json.dumps(sources),
        json.dumps(cluster_ids),
        json.dumps(citation_map),
        GENERATOR_MODEL,
        GENERATION_PROMPT_VERSION,
    ))

    conn.commit()
    conn.close()


def generate_edition(edition_date: str) -> dict | None:
    clusters = load_top_clusters(edition_date)

    if not clusters:
        return None

    article_brief, citation_map = build_article_brief(clusters)

    print("\nGenerating daily article...\n")

    generated_article = generate_daily_article(article_brief)

    if not generated_article:
        return None

    save_generated_article(edition_date, generated_article, clusters, citation_map)

    return generated_article


def main():
    edition_date = parse_edition_date().isoformat()
    generated_article = generate_edition(edition_date)

    if generated_article is None:
        print(f"Article generation failed or no clusters found for {edition_date}.")
        return

    print(f"\n{generated_article['title']}\n")
    print(generated_article["body"])
    print("\nSaved generated article and source snapshot.")


if __name__ == "__main__":
    main()
