import os
import unittest
from unittest.mock import Mock, patch

from app.database.db import DB_PATH, connect_database, row_to_dict, setup_database


class DatabaseConnectionTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    @patch("app.database.db.sqlite3.connect")
    def test_uses_local_sqlite_without_turso_credentials(
        self,
        sqlite_connect,
    ):
        connection = connect_database()

        sqlite_connect.assert_called_once_with(DB_PATH)
        self.assertIs(connection, sqlite_connect.return_value)

    @patch.dict(
        os.environ,
        {
            "TURSO_DATABASE_URL": "libsql://nineam-test.turso.io",
            "TURSO_AUTH_TOKEN": "test-token",
        },
        clear=True,
    )
    @patch("app.database.db.libsql.connect")
    def test_uses_turso_when_both_credentials_exist(
        self,
        libsql_connect,
    ):
        connection = connect_database()

        libsql_connect.assert_called_once_with(
            "libsql://nineam-test.turso.io",
            auth_token="test-token",
        )
        self.assertIs(connection, libsql_connect.return_value)

    def test_rejects_partial_turso_configuration(self):
        incomplete_configurations = [
            {
                "TURSO_DATABASE_URL": "libsql://nineam-test.turso.io",
            },
            {
                "TURSO_AUTH_TOKEN": "test-token",
            },
        ]

        for configuration in incomplete_configurations:
            with self.subTest(configuration=configuration):
                with patch.dict(os.environ, configuration, clear=True):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "must be configured together",
                    ):
                        connect_database()

    @patch("app.database.db.connect_database")
    def test_setup_database_uses_shared_connection(
        self,
        connect_database_mock,
    ):
        connection = connect_database_mock.return_value
        cursor = connection.cursor.return_value

        setup_database()

        connect_database_mock.assert_called_once_with()
        self.assertEqual(cursor.execute.call_count, 6)
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_row_to_dict_uses_cursor_column_names(self):
        cursor = Mock()
        cursor.description = (
            ("id", None, None, None, None, None, None),
            ("title", None, None, None, None, None, None),
        )

        result = row_to_dict(cursor, (1, "NineAM"))

        self.assertEqual(
            result,
            {
                "id": 1,
                "title": "NineAM",
            },
        )

    def test_row_to_dict_preserves_missing_row(self):
        cursor = Mock()

        self.assertIsNone(row_to_dict(cursor, None))


if __name__ == "__main__":
    unittest.main()
