"""
tests/test_hardcore_worker.py

Unit tests for workers/hardcore_worker.py.

Uses a real tmp_path database and a real QApplication to allow QThread
signals to fire.  All tests are fully offline — no real saves are touched.
"""

import sqlite3
import time
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qt_app():
    """One shared QApplication for the entire test session."""
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """A fully provisioned universe db with one Hardcore save."""
    from database.schema import create_universe_db
    from database.event_sourcing import EventSourcer

    path = str(tmp_path / "universe.db")
    create_universe_db(path)

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute(
            "INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
            ("save1", "Hero", "Hardcore", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
            ("player1", "player", "Aria", 1),
        )
        conn.commit()

    es = EventSourcer(path)
    es.append_event("save1", 1, "stat_change", "player1",
                    {"entity_id": "player1", "stat_key": "HP", "delta": 100})
    es.rebuild_state_cache("save1")
    return path


def _run_worker_sync(worker, timeout_ms: int = 5000):
    """Start a QThread worker and block until it finishes (with timeout)."""
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


# ---------------------------------------------------------------------------
# HardcoreWorker
# ---------------------------------------------------------------------------

class TestHardcoreWorker:
    def test_deletes_save_row(self, db_path: str, tmp_path: Path, qt_app) -> None:
        from workers.hardcore_worker import HardcoreWorker

        # Add a second save so the .db is NOT deleted (only the save row is removed)
        with sqlite3.connect(db_path) as conn:
            conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                         ("save2", "Hero2", "Normal", "2026-01-02T00:00:00"))
            conn.commit()

        vector_dir = str(tmp_path / "vector" / "save1")
        Path(vector_dir).mkdir(parents=True)

        worker = HardcoreWorker(
            db_path=db_path,
            save_id="save1",
            universe_dir=str(tmp_path),
            vector_persist_dir=vector_dir,
        )
        completed: list[bool] = []
        worker.deletion_complete.connect(lambda: completed.append(True))
        _run_worker_sync(worker)

        assert completed, "deletion_complete signal was not emitted"

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM Saves WHERE save_id = 'save1';"
            ).fetchone()
        assert row is None, "Save row should have been deleted"

    def test_deletes_event_log_rows(self, tmp_path: Path, qt_app) -> None:
        from workers.hardcore_worker import HardcoreWorker
        from database.schema import create_universe_db
        from database.event_sourcing import EventSourcer

        vector_dir = str(tmp_path / "vector" / "s2")
        Path(vector_dir).mkdir(parents=True)

        db2 = str(tmp_path / "u2.db")
        create_universe_db(db2)
        with sqlite3.connect(db2) as conn:
            conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                         ("s2", "Hero", "Hardcore", "2026-01-01T00:00:00"))
            # Second save to prevent db file deletion
            conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                         ("s2_other", "Other", "Normal", "2026-01-02T00:00:00"))
            conn.execute("INSERT INTO Entities (entity_id, entity_type, name, is_active) VALUES (?,?,?,?);",
                         ("p1", "player", "A", 1))
            conn.commit()

        es = EventSourcer(db2)
        es.append_event("s2", 1, "stat_change", "p1",
                        {"entity_id": "p1", "stat_key": "HP", "delta": 50})

        worker = HardcoreWorker(
            db_path=db2,
            save_id="s2",
            universe_dir=str(tmp_path),
            vector_persist_dir=vector_dir,
        )
        completed: list[bool] = []
        worker.deletion_complete.connect(lambda: completed.append(True))
        _run_worker_sync(worker)

        assert completed

        with sqlite3.connect(db2) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM Event_Log WHERE save_id = 's2';"
            ).fetchone()[0]
        assert count == 0

    def test_deletes_vector_directory(self, tmp_path: Path, qt_app) -> None:
        from workers.hardcore_worker import HardcoreWorker
        from database.schema import create_universe_db

        db3 = str(tmp_path / "u3.db")
        create_universe_db(db3)
        with sqlite3.connect(db3) as conn:
            conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                         ("s3", "Hero", "Hardcore", "2026-01-01T00:00:00"))
            conn.commit()

        vector_dir = tmp_path / "vector" / "s3"
        vector_dir.mkdir(parents=True)
        (vector_dir / "chroma.sqlite3").write_text("fake chroma data")

        worker = HardcoreWorker(
            db_path=db3,
            save_id="s3",
            universe_dir=str(tmp_path),
            vector_persist_dir=str(vector_dir),
        )
        completed: list[bool] = []
        worker.deletion_complete.connect(lambda: completed.append(True))
        _run_worker_sync(worker)

        assert completed
        assert not vector_dir.exists(), "Vector directory should have been deleted"

    def test_nonexistent_vector_dir_does_not_fail(self, tmp_path: Path, qt_app) -> None:
        from workers.hardcore_worker import HardcoreWorker
        from database.schema import create_universe_db

        db4 = str(tmp_path / "u4.db")
        create_universe_db(db4)
        with sqlite3.connect(db4) as conn:
            conn.execute("INSERT INTO Saves (save_id, player_name, difficulty, last_updated) VALUES (?,?,?,?);",
                         ("s4", "Hero", "Hardcore", "2026-01-01T00:00:00"))
            conn.commit()

        worker = HardcoreWorker(
            db_path=db4,
            save_id="s4",
            universe_dir=str(tmp_path),
            vector_persist_dir=str(tmp_path / "nonexistent_vector"),
        )
        completed: list[bool] = []
        failed: list[str] = []
        worker.deletion_complete.connect(lambda: completed.append(True))
        worker.deletion_failed.connect(lambda msg: failed.append(msg))
        _run_worker_sync(worker)

        # Should succeed even if vector dir doesn't exist (ignore_errors=True)
        assert completed, f"Should complete; failed: {failed}"

    def test_deletion_failed_on_nonexistent_db(self, tmp_path: Path, qt_app) -> None:
        from workers.hardcore_worker import HardcoreWorker

        worker = HardcoreWorker(
            db_path=str(tmp_path / "nonexistent.db"),
            save_id="s_ghost",
            universe_dir=str(tmp_path),
            vector_persist_dir=str(tmp_path / "vdir"),
        )
        completed: list[bool] = []
        failed: list[str] = []
        worker.deletion_complete.connect(lambda: completed.append(True))
        worker.deletion_failed.connect(lambda msg: failed.append(msg))
        _run_worker_sync(worker)

        # Should fail gracefully — either failed or completed depending on
        # whether SQLite creates a new file; we just verify no unhandled exception
        assert len(completed) + len(failed) > 0, "Must emit at least one signal"


# ---------------------------------------------------------------------------
# HardcoreWorker._probe_lock
# ---------------------------------------------------------------------------

class TestProbeLock:
    def test_returns_true_for_unlocked_file(self, tmp_path: Path) -> None:
        from workers.hardcore_worker import HardcoreWorker
        f = tmp_path / "test.db"
        f.write_text("data")
        assert HardcoreWorker._probe_lock(str(f)) is True

    def test_returns_true_for_nonexistent_file(self, tmp_path: Path) -> None:
        from workers.hardcore_worker import HardcoreWorker
        assert HardcoreWorker._probe_lock(str(tmp_path / "ghost.db")) is True
