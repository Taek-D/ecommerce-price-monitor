"""
tests/test_migration.py
Unit tests for migrate.py — JSON-to-DB migration script.

Covers MIG-01 (price_state), MIG-02 (discovery_state), MIG-03 (.bak backup).

All tests use file-backed tmp_path DBs (WAL mode does NOT work on :memory:).
Each test resets db._conn to None and monkeypatches db.DB_FILE to a temp file.
"""

import json
import pytest
import db
import migrate


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _open_db(tmp_path, monkeypatch):
    """Open DB against a temp file. Returns db_path."""
    db_path = str(tmp_path / "test_ops.db")
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(db, "_conn", None)
    await db.open_db()
    return db_path


def _write_json(path, data):
    """Write JSON data to a file."""
    path.write_text(json.dumps(data), encoding="utf-8")


# ── Test 1: Bot running — migration refused ────────────────────────────────


async def test_bot_running_refuses_migration(tmp_path, monkeypatch):
    """If .main.lock exists, migration refuses with an error and makes no DB changes."""
    db_path = await _open_db(tmp_path, monkeypatch)

    # Create a lock file
    lock_file = tmp_path / ".main.lock"
    lock_file.write_text("12345")

    # Patch LOCK_FILE to point to our tmp lock file
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)

    # Patch STATE_FILE and DISCOVERY_STATE_FILE to point to tmp_path
    price_json = tmp_path / "price_state.json"
    _write_json(price_json, {"https://example.com/1": 10000})
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))

    result = await migrate.main()

    # Migration should be refused (return False or similar)
    assert result is False, "main() should return False when bot is running"

    # DB should be unchanged — no price_state rows inserted
    conn = db.get_conn()
    async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
        row = await cur.fetchone()
    assert row[0] == 0, "No rows should be inserted when bot is running"

    await db.close_db()


# ── Test 2: price_state.json with 3 URLs (mix int and None) ───────────────


async def test_price_state_migrates_3_urls(tmp_path, monkeypatch):
    """price_state.json with 3 URLs (mix of int and None) -> 3 rows in price_state table."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    _write_json(
        price_json,
        {
            "https://shop.com/item/1": 15000,
            "https://shop.com/item/2": None,
            "https://shop.com/item/3": 32000,
        },
    )

    lock_file = tmp_path / ".main.lock"  # does NOT exist
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(
        migrate, "DISCOVERY_STATE_FILE", str(tmp_path / "discovery_state.json")
    )

    result = await migrate.main()
    assert result is True

    # main() closes the DB in its finally block — re-open to verify data
    await db.open_db()
    conn = db.get_conn()
    async with conn.execute("SELECT url, price FROM price_state ORDER BY url") as cur:
        rows = await cur.fetchall()

    assert len(rows) == 3
    url_price = {r[0]: r[1] for r in rows}
    assert url_price["https://shop.com/item/1"] == 15000
    assert url_price["https://shop.com/item/2"] is None
    assert url_price["https://shop.com/item/3"] == 32000

    await db.close_db()


# ── Test 3: Row-count mismatch -> ROLLBACK, DB unchanged, JSON preserved ──


async def test_row_count_mismatch_rollback(tmp_path, monkeypatch):
    """Row-count mismatch causes ROLLBACK; DB unchanged and JSON original preserved."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    original_content = {"https://a.com": 10000, "https://b.com": 20000}
    _write_json(price_json, original_content)

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(
        migrate, "DISCOVERY_STATE_FILE", str(tmp_path / "discovery_state.json")
    )

    # Monkey-patch _migrate_price_state to simulate a row-count mismatch
    original_fn = migrate._migrate_price_state

    async def _fake_migrate_price(conn):
        # Insert only 1 row instead of 2 (simulating mismatch)
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO price_state(url, price, updated_at) VALUES (?,?,?)",
                ("https://a.com", 10000, "2026-01-01T00:00:00"),
            )
            # Force mismatch: json_count=2 but we only inserted 1
            async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
                db_count = (await cur.fetchone())[0]
            json_count = 2
            if db_count != json_count:
                await conn.execute("ROLLBACK")
                return False, 0
            await conn.commit()
            return True, 1
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    monkeypatch.setattr(migrate, "_migrate_price_state", _fake_migrate_price)

    result = await migrate.main()
    assert result is False

    # main() closes the DB in its finally block — re-open to verify data
    await db.open_db()
    conn = db.get_conn()
    async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
        row = await cur.fetchone()
    assert row[0] == 0, "DB should be empty after rollback"

    # JSON original should still exist (not renamed to .bak)
    assert price_json.exists(), "Original JSON should be preserved on failure"
    bak_file = tmp_path / "price_state.json.bak"
    assert not bak_file.exists(), ".bak should NOT be created on failure"

    await db.close_db()


# ── Test 4: price_state.json missing -> skip with log, no error ──────────


async def test_price_state_missing_skip(tmp_path, monkeypatch):
    """price_state.json missing -> migration skips gracefully (no error)."""
    await _open_db(tmp_path, monkeypatch)

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(
        migrate, "STATE_FILE", str(tmp_path / "price_state.json")
    )  # doesn't exist
    monkeypatch.setattr(
        migrate, "DISCOVERY_STATE_FILE", str(tmp_path / "discovery_state.json")
    )

    result = await migrate.main()
    assert result is True, "Missing price_state.json should not cause failure"

    # main() closes the DB in its finally block — re-open to verify data
    await db.open_db()
    conn = db.get_conn()
    async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
        row = await cur.fetchone()
    assert row[0] == 0

    await db.close_db()


# ── Test 5: discovery_state.json with discovered_urls -> rows inserted ────


async def test_discovery_state_migrates_urls(tmp_path, monkeypatch):
    """discovery_state.json with discovered_urls dict -> rows inserted in discovery_candidates."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    _write_json(price_json, {})

    disc_json = tmp_path / "discovery_state.json"
    _write_json(
        disc_json,
        {
            "last_run": "2026-03-01T00:00:00",
            "discovered_urls": {
                "https://shop.com/product/A": "2026-03-01",
                "https://shop.com/product/B": "2026-03-02",
            },
            "daily_stats": {},
        },
    )

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(migrate, "DISCOVERY_STATE_FILE", str(disc_json))

    result = await migrate.main()
    assert result is True

    # main() closes the DB in its finally block — re-open to verify data
    await db.open_db()
    conn = db.get_conn()
    async with conn.execute(
        "SELECT source, url, discovered_at FROM discovery_candidates ORDER BY url"
    ) as cur:
        rows = await cur.fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row[0] == "discovery_state"  # source
    urls = {r[1] for r in rows}
    assert urls == {"https://shop.com/product/A", "https://shop.com/product/B"}

    await db.close_db()


# ── Test 6: discovery_state.json missing -> skip, no error ───────────────


async def test_discovery_state_missing_skip(tmp_path, monkeypatch):
    """discovery_state.json missing -> skip gracefully, migration still succeeds."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    _write_json(price_json, {"https://x.com/p": 5000})

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(
        migrate, "DISCOVERY_STATE_FILE", str(tmp_path / "discovery_state.json")
    )  # missing

    result = await migrate.main()
    assert result is True

    # main() closes the DB in its finally block — re-open to verify data
    await db.open_db()
    conn = db.get_conn()
    async with conn.execute("SELECT COUNT(*) FROM discovery_candidates") as cur:
        row = await cur.fetchone()
    assert row[0] == 0

    await db.close_db()


# ── Test 7: Successful migration -> price_state.json renamed to .bak ──────


async def test_successful_migration_creates_bak(tmp_path, monkeypatch):
    """Successful migration renames price_state.json to price_state.json.bak."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    _write_json(price_json, {"https://shop.com/item": 9999})

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(
        migrate, "DISCOVERY_STATE_FILE", str(tmp_path / "discovery_state.json")
    )

    result = await migrate.main()
    assert result is True

    bak_file = tmp_path / "price_state.json.bak"
    assert bak_file.exists(), ".bak file should be created on success"
    assert not price_json.exists(), "Original JSON should be renamed (no longer exists)"

    await db.close_db()


# ── Test 8: Successful migration with discovery_state.json -> .bak created ─


async def test_successful_migration_with_discovery_creates_bak(tmp_path, monkeypatch):
    """Successful migration with discovery_state.json renames it to .bak."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    _write_json(price_json, {})

    disc_json = tmp_path / "discovery_state.json"
    _write_json(
        disc_json,
        {
            "last_run": "2026-03-01T00:00:00",
            "discovered_urls": {"https://shop.com/p": "2026-03-01"},
            "daily_stats": {},
        },
    )

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(migrate, "DISCOVERY_STATE_FILE", str(disc_json))

    result = await migrate.main()
    assert result is True

    disc_bak = tmp_path / "discovery_state.json.bak"
    assert disc_bak.exists(), "discovery_state.json.bak should be created on success"
    assert not disc_json.exists(), "Original discovery_state.json should be renamed"

    await db.close_db()


# ── Test 9: Migration failure -> JSON originals NOT renamed ───────────────


async def test_migration_failure_no_bak(tmp_path, monkeypatch):
    """Migration failure (exception during migrate) -> JSON originals not renamed."""
    await _open_db(tmp_path, monkeypatch)

    price_json = tmp_path / "price_state.json"
    _write_json(price_json, {"https://a.com": 1000})

    disc_json = tmp_path / "discovery_state.json"
    _write_json(
        disc_json,
        {
            "last_run": "2026-03-01T00:00:00",
            "discovered_urls": {"https://shop.com/p": "2026-03-01"},
            "daily_stats": {},
        },
    )

    lock_file = tmp_path / ".main.lock"
    monkeypatch.setattr(migrate, "LOCK_FILE", lock_file)
    monkeypatch.setattr(migrate, "STATE_FILE", str(price_json))
    monkeypatch.setattr(migrate, "DISCOVERY_STATE_FILE", str(disc_json))

    # Force failure in price state migration
    async def _bad_migrate_price(conn):
        return False, 0

    monkeypatch.setattr(migrate, "_migrate_price_state", _bad_migrate_price)

    result = await migrate.main()
    assert result is False

    # Neither JSON should be renamed
    assert price_json.exists(), "price_state.json should be preserved on failure"
    assert disc_json.exists(), "discovery_state.json should be preserved on failure"
    assert not (tmp_path / "price_state.json.bak").exists()
    assert not (tmp_path / "discovery_state.json.bak").exists()

    await db.close_db()
