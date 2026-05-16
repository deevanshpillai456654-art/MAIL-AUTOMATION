from __future__ import annotations

import time
from pathlib import Path


def test_atomic_json_store_recovers_corrupt_state_from_backup(tmp_path):
    from backend.core.atomic_persistence import AtomicJSONStore

    store = AtomicJSONStore(tmp_path, "runtime_state")
    store.write({"version": 1, "accounts": ["a@example.com"]})
    store.write({"version": 2, "accounts": ["a@example.com", "b@example.com"]})

    store.path.write_text("{corrupt-json", encoding="utf-8")
    restored = store.read(default={})

    assert restored == {"version": 2, "accounts": ["a@example.com", "b@example.com"]}
    validation = store.validate().as_dict()
    assert validation["status"] == "ok"
    assert store.journal_path.exists()
    assert "recovered_from_backup" in store.journal_path.read_text(encoding="utf-8")


def test_wal_manager_configures_and_checkpoints_sqlite_database(tmp_path):
    import sqlite3
    from backend.storage.wal_manager import WALHardeningManager

    db_path = tmp_path / "test.db"
    storage_root = tmp_path / "wal_storage"

    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO items VALUES (1, 'hello')")
    conn.commit()
    conn.close()

    mgr = WALHardeningManager(db_path=str(db_path), storage_root=str(storage_root))
    assert mgr.db_path == db_path
    assert storage_root.exists()

    conn2 = sqlite3.connect(str(db_path))
    assert mgr.configure_database(conn2) is True
    cursor = conn2.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0] == "wal"
    conn2.close()

    result = mgr.checkpoint()
    assert result.success is True

    stats = mgr.get_stats()
    assert stats.total_checkpoints == 1


def test_persistent_job_queue_survives_restart_and_recovers_expired_lease(tmp_path):
    from backend.core.persistent_job_queue import PersistentJobQueue

    db_path = tmp_path / "jobs.db"
    q1 = PersistentJobQueue(db_path)
    job_id = q1.enqueue("email_sync", {"account_id": 11, "folder": "INBOX"}, max_attempts=2)

    q2 = PersistentJobQueue(db_path)
    job = q2.lease_next("email_sync", lease_seconds=1)
    assert job is not None
    assert job["job_id"] == job_id
    assert job["payload"]["folder"] == "INBOX"
    assert q2.counts()["leased"] == 1

    time.sleep(1.05)
    assert q2.recover_stale_leases() == 1
    assert q2.counts()["pending"] == 1

    job = q2.lease_next("email_sync", lease_seconds=5)
    assert job is not None
    q2.complete(job["job_id"])
    assert q2.counts()["completed"] == 1
