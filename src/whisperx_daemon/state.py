"""SQLite-backed job tracking for idempotent file processing."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobRecord:
    """Persisted metadata for a tracked source file.

    The watcher uses ``source_path`` plus ``file_digest`` to decide whether an
    input file needs to be reprocessed.
    """

    source_path: str
    file_digest: str
    status: str
    output_path: str | None


class JobStore:
    """Small SQLite wrapper for idempotent job tracking.

    The store deliberately exposes only the few operations the watcher needs:
    initialise the schema, load an existing record, and upsert the latest known
    state for a source file.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection for a short-lived store operation.

        Callers use this helper together with :func:`contextlib.closing`
        because ``sqlite3.Connection`` context managers commit or roll back
        transactions but do not close the connection automatically.
        """

        return sqlite3.connect(self._database_path)

    def initialise(self) -> None:
        """Create the jobs table and timestamp trigger when absent.

        The ``updated_at`` trigger keeps the schema operationally useful without
        requiring callers to manage timestamps manually.
        """

        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    file_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_path TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS jobs_touch_updated_at
                AFTER UPDATE ON jobs
                FOR EACH ROW
                BEGIN
                    UPDATE jobs
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = OLD.id;
                END
                """
            )
            connection.commit()

    def fetch_by_source_path(self, source_path: str) -> JobRecord | None:
        """Return the stored job record for a given source path.

        Args:
            source_path: Absolute path string used as the job's stable key.

        Returns:
            The matching :class:`JobRecord`, or ``None`` when the file has not
            been seen before.
        """

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT source_path, file_digest, status, output_path
                FROM jobs
                WHERE source_path = ?
                """,
                (source_path,),
            ).fetchone()
        if row is None:
            return None
        return JobRecord(*row)

    def upsert_job(
        self,
        source_path: str,
        file_digest: str,
        status: str,
        output_path: str | None = None,
    ) -> None:
        """Insert or replace the stored state for a source file.

        The upsert behaviour keeps the table compact: one row per source path,
        always reflecting the most recent processing attempt.
        """

        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO jobs (source_path, file_digest, status, output_path)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_path)
                DO UPDATE SET
                    file_digest = excluded.file_digest,
                    status = excluded.status,
                    output_path = excluded.output_path
                """,
                (source_path, file_digest, status, output_path),
            )
            connection.commit()
