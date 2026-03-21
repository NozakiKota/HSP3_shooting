"""
Windows Activity Logger - SQLite Database Module
エラー時の再処理を防ぐため、ActivityRecord を SQLite に一時保存する
"""
import sqlite3
import threading
from pathlib import Path

from logger import ActivityRecord

DEFAULT_DB_PATH = Path.home() / ".windows_activity_logger" / "activity.db"


class ActivityDatabase:
    """
    ActivityRecord を SQLite に保存・取得するクラス。
    CSVと並行して使用し、アプリ再起動後も途中から再開できる。
    スレッドセーフ（check_same_thread=False + Lock使用）。
    """

    def __init__(self, db_path: "str | Path | None" = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._create_table()

    def _create_table(self) -> None:
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_records (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    app_name    TEXT    NOT NULL,
                    window_title TEXT   NOT NULL,
                    duration_sec REAL   NOT NULL,
                    category    TEXT    NOT NULL DEFAULT 'other',
                    session_id  TEXT,
                    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON activity_records (timestamp)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_id
                ON activity_records (session_id)
            """)
            self._conn.commit()

    def insert(self, record: ActivityRecord, session_id: str = "") -> None:
        """レコードを1件挿入する"""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO activity_records
                    (timestamp, app_name, window_title, duration_sec, category, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.app_name,
                    record.window_title,
                    record.duration_sec,
                    record.category,
                    session_id,
                ),
            )
            self._conn.commit()

    def insert_many(self, records: list[ActivityRecord], session_id: str = "") -> None:
        """レコードをまとめて挿入する（バルクインサート）"""
        rows = [
            (r.timestamp, r.app_name, r.window_title, r.duration_sec, r.category, session_id)
            for r in records
        ]
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO activity_records
                    (timestamp, app_name, window_title, duration_sec, category, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()

    def fetch_all(self) -> list[ActivityRecord]:
        """全レコードをタイムスタンプ順で返す"""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT timestamp, app_name, window_title, duration_sec, category "
                "FROM activity_records ORDER BY timestamp"
            )
            return [
                ActivityRecord(
                    timestamp=row[0],
                    app_name=row[1],
                    window_title=row[2],
                    duration_sec=float(row[3]),
                    category=row[4],
                )
                for row in cursor.fetchall()
            ]

    def fetch_by_session(self, session_id: str) -> list[ActivityRecord]:
        """特定セッションのレコードを返す"""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT timestamp, app_name, window_title, duration_sec, category "
                "FROM activity_records WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            )
            return [
                ActivityRecord(
                    timestamp=row[0],
                    app_name=row[1],
                    window_title=row[2],
                    duration_sec=float(row[3]),
                    category=row[4],
                )
                for row in cursor.fetchall()
            ]

    def fetch_since(self, timestamp: str) -> list[ActivityRecord]:
        """指定タイムスタンプ以降のレコードを返す（再開用）"""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT timestamp, app_name, window_title, duration_sec, category "
                "FROM activity_records WHERE timestamp >= ? ORDER BY timestamp",
                (timestamp,),
            )
            return [
                ActivityRecord(
                    timestamp=row[0],
                    app_name=row[1],
                    window_title=row[2],
                    duration_sec=float(row[3]),
                    category=row[4],
                )
                for row in cursor.fetchall()
            ]

    def get_latest_timestamp(self) -> str | None:
        """DBに保存されている最新タイムスタンプを返す（再開ポイント特定用）"""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT MAX(timestamp) FROM activity_records"
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    def count(self) -> int:
        """保存済みレコード数を返す"""
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM activity_records")
            return cursor.fetchone()[0]

    def delete_old_records(self, keep_days: int = 30) -> int:
        """指定日数より古いレコードを削除し、削除件数を返す"""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM activity_records "
                "WHERE timestamp < datetime('now', ?, 'localtime')",
                (f"-{keep_days} days",),
            )
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
