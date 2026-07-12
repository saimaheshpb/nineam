import os
import sqlite3

import libsql
from dotenv import load_dotenv

# This forces Python to look in the root folder of your project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "news_aggregator.db")

load_dotenv(os.path.join(BASE_DIR, ".env"))


def connect_database():
    """Connects to Turso when configured, otherwise to local SQLite."""
    turso_url = os.getenv("TURSO_DATABASE_URL", "").strip()
    turso_auth_token = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    if bool(turso_url) != bool(turso_auth_token):
        raise RuntimeError(
            "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be configured together."
        )

    if turso_url:
        return libsql.connect(
            turso_url,
            auth_token=turso_auth_token,
        )

    return sqlite3.connect(DB_PATH)


def row_to_dict(cursor, row):
    """Converts a database result tuple into a column-name dictionary."""
    if row is None:
        return None

    column_names = [
        column_description[0]
        for column_description in cursor.description
    ]

    return dict(zip(column_names, row))


def create_schema(conn):
    """Creates the database tables on an existing connection."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        source_name TEXT,
        source_category TEXT,
        headline TEXT,
        summary TEXT,
        full_text TEXT,
        entities TEXT,
        evidence_json TEXT,
        category TEXT,
        importance_score INTEGER,
        embedding TEXT,
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS story_clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT,
        representative_headline TEXT,
        cluster_size INTEGER,
        rank_score REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS story_cluster_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id INTEGER,
        item_id INTEGER,
        similarity_to_representative REAL,
        FOREIGN KEY (cluster_id) REFERENCES story_clusters(id),
        FOREIGN KEY (item_id) REFERENCES items(id)
    )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition_date TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            cluster_ids_json TEXT NOT NULL,
            citation_map_json TEXT NOT NULL,
            generator_model TEXT NOT NULL,
            generation_prompt_version TEXT NOT NULL,
            eval_status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_article_id INTEGER NOT NULL,
            overall_status TEXT NOT NULL,
            faithfulness_score REAL,
            citation_validity_score REAL,
            citation_completeness_score REAL,
            contradiction_score REAL,
            coverage_score REAL,
            editorial_quality_score REAL,
            checks_json TEXT NOT NULL,
            judge_model TEXT NOT NULL,
            judge_prompt_version TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (generated_article_id) REFERENCES generated_articles(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claim_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eval_run_id INTEGER NOT NULL,
            claim_index INTEGER NOT NULL,
            claim_text TEXT NOT NULL,
            citation_ids_json TEXT NOT NULL,
            citation_valid INTEGER NOT NULL,
            verdict TEXT NOT NULL,
            confidence REAL,
            severity TEXT NOT NULL,
            rationale TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (eval_run_id) REFERENCES eval_runs(id)
        )
    """)

    conn.commit()


def setup_database():
    """Creates the database tables on the configured database."""
    conn = connect_database()

    try:
        create_schema(conn)
    finally:
        conn.close()
