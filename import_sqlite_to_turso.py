import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.database.db import DB_PATH, connect_database, create_schema

TABLES_IN_IMPORT_ORDER = (
    "items",
    "story_clusters",
    "story_cluster_items",
    "generated_articles",
    "eval_runs",
    "claim_evaluations",
)

JSON_FIELDS = {
    "items": ("entities", "evidence_json", "embedding"),
    "generated_articles": (
        "sources_json",
        "cluster_ids_json",
        "citation_map_json",
    ),
    "eval_runs": ("checks_json",),
    "claim_evaluations": ("citation_ids_json",),
}

RELATIONSHIP_CHECKS = {
    "story cluster item -> cluster": """
        SELECT COUNT(*)
        FROM story_cluster_items AS membership
        LEFT JOIN story_clusters AS cluster
          ON cluster.id = membership.cluster_id
        WHERE membership.cluster_id IS NOT NULL
          AND cluster.id IS NULL
    """,
    "story cluster item -> item": """
        SELECT COUNT(*)
        FROM story_cluster_items AS membership
        LEFT JOIN items AS item
          ON item.id = membership.item_id
        WHERE membership.item_id IS NOT NULL
          AND item.id IS NULL
    """,
    "eval run -> generated article": """
        SELECT COUNT(*)
        FROM eval_runs AS run
        LEFT JOIN generated_articles AS article
          ON article.id = run.generated_article_id
        WHERE article.id IS NULL
    """,
    "claim evaluation -> eval run": """
        SELECT COUNT(*)
        FROM claim_evaluations AS claim
        LEFT JOIN eval_runs AS run
          ON run.id = claim.eval_run_id
        WHERE run.id IS NULL
    """,
}


@dataclass(frozen=True)
class ImportResult:
    imported: bool
    table_counts: dict[str, int]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def table_columns(connection, table_name: str) -> tuple[str, ...]:
    rows = connection.execute(
        f"PRAGMA table_info({quote_identifier(table_name)})"
    ).fetchall()
    columns = tuple(row[1] for row in rows)

    if not columns:
        raise RuntimeError(f"Missing required table: {table_name}")

    return columns


def table_rows(
    connection,
    table_name: str,
    columns: tuple[str, ...],
) -> tuple[tuple, ...]:
    selected_columns = ", ".join(
        quote_identifier(column)
        for column in columns
    )
    query = (
        f"SELECT {selected_columns} "
        f"FROM {quote_identifier(table_name)} "
        "ORDER BY id"
    )
    return tuple(connection.execute(query).fetchall())


def database_snapshot(connection) -> dict[str, dict]:
    snapshot = {}

    for table_name in TABLES_IN_IMPORT_ORDER:
        columns = table_columns(connection, table_name)
        snapshot[table_name] = {
            "columns": columns,
            "rows": table_rows(connection, table_name, columns),
        }

    return snapshot


def verify_relationships(connection) -> None:
    for relationship_name, query in RELATIONSHIP_CHECKS.items():
        orphan_count = connection.execute(query).fetchone()[0]

        if orphan_count:
            raise RuntimeError(
                f"Relationship verification failed for {relationship_name}: "
                f"{orphan_count} orphaned row(s)."
            )


def verify_json_fields(connection) -> None:
    for table_name, field_names in JSON_FIELDS.items():
        selected_fields = ", ".join(
            [quote_identifier("id")]
            + [quote_identifier(field_name) for field_name in field_names]
        )
        rows = connection.execute(
            f"SELECT {selected_fields} FROM {quote_identifier(table_name)}"
        ).fetchall()

        for row in rows:
            row_id = row[0]

            for field_name, value in zip(field_names, row[1:]):
                if value is None:
                    continue

                try:
                    json.loads(value)
                except (TypeError, json.JSONDecodeError) as error:
                    raise RuntimeError(
                        f"Invalid JSON in {table_name}.{field_name} "
                        f"for row {row_id}."
                    ) from error


def verify_database(connection) -> None:
    verify_relationships(connection)
    verify_json_fields(connection)


def import_sqlite_database(
    source_path: str | Path,
    target_connection,
) -> ImportResult:
    source_path = Path(source_path)

    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source_path}")

    source_connection = sqlite3.connect(source_path)

    try:
        create_schema(target_connection)
        source_snapshot = database_snapshot(source_connection)
        target_snapshot = database_snapshot(target_connection)

        for table_name in TABLES_IN_IMPORT_ORDER:
            if (
                source_snapshot[table_name]["columns"]
                != target_snapshot[table_name]["columns"]
            ):
                raise RuntimeError(
                    f"Schema mismatch for table: {table_name}"
                )

        target_has_data = any(
            table_snapshot["rows"]
            for table_snapshot in target_snapshot.values()
        )
        table_counts = {
            table_name: len(table_snapshot["rows"])
            for table_name, table_snapshot in source_snapshot.items()
        }

        if target_has_data:
            if target_snapshot != source_snapshot:
                raise RuntimeError(
                    "Target database already contains data that does not "
                    "exactly match the SQLite source."
                )

            verify_database(target_connection)
            return ImportResult(imported=False, table_counts=table_counts)

        try:
            for table_name in TABLES_IN_IMPORT_ORDER:
                columns = source_snapshot[table_name]["columns"]
                rows = source_snapshot[table_name]["rows"]

                if not rows:
                    continue

                column_list = ", ".join(
                    quote_identifier(column)
                    for column in columns
                )
                placeholders = ", ".join("?" for _ in columns)
                target_connection.executemany(
                    f"INSERT INTO {quote_identifier(table_name)} "
                    f"({column_list}) VALUES ({placeholders})",
                    list(rows),
                )

            imported_snapshot = database_snapshot(target_connection)

            if imported_snapshot != source_snapshot:
                raise RuntimeError(
                    "Imported Turso data does not exactly match the SQLite source."
                )

            verify_database(target_connection)
            target_connection.commit()
        except Exception:
            target_connection.rollback()
            raise

        return ImportResult(imported=True, table_counts=table_counts)
    finally:
        source_connection.close()


def require_turso_configuration() -> None:
    turso_url = os.getenv("TURSO_DATABASE_URL", "").strip()
    turso_auth_token = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    if not turso_url or not turso_auth_token:
        raise RuntimeError(
            "Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN before importing."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import the local NineAM SQLite database into Turso."
    )
    parser.add_argument(
        "--source",
        default=DB_PATH,
        help="Path to the source SQLite database.",
    )
    args = parser.parse_args()

    require_turso_configuration()
    target_connection = connect_database()

    try:
        result = import_sqlite_database(args.source, target_connection)
    finally:
        target_connection.close()

    action = "Imported" if result.imported else "Already verified"
    print(f"{action} NineAM database:")

    for table_name, row_count in result.table_counts.items():
        print(f"- {table_name}: {row_count} row(s)")


if __name__ == "__main__":
    main()
