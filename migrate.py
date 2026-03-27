"""
migrate.py
One-shot JSON-to-DB migration script.

Migrates price_state.json and discovery_state.json into the SQLite DB tables
created in Phase 4. Designed for manual execution with the bot stopped.

Usage:
    python migrate.py

Safety checks:
  - Refuses to run if .main.lock exists (bot is running)
  - Uses BEGIN IMMEDIATE transaction for atomic writes
  - Verifies row-count after INSERT — ROLLBACK on mismatch
  - Renames JSON to .bak ONLY after successful COMMIT
  - Missing JSON files are silently skipped (no error)

Dependency chain: config <- db <- migrate  (no other project imports)
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import db
from config import DB_FILE, KST, STATE_FILE  # noqa: F401 (DB_FILE imported for monkeypatching)

# ── Module-level constants (monkeypatch-friendly) ─────────────────────────────

LOCK_FILE = Path(__file__).resolve().parent / ".main.lock"
DISCOVERY_STATE_FILE = str(Path(__file__).resolve().parent / "discovery_state.json")


# ── Migration helpers ─────────────────────────────────────────────────────────


async def _migrate_price_state(conn) -> tuple[bool, int]:
    """Migrate price_state.json -> DB price_state table.

    Returns:
        (success, count) — success=True and count=N rows on success,
        (False, 0) on mismatch or error, (True, 0) if file missing.
    """
    src = Path(STATE_FILE)
    if not src.exists():
        print("migrate: price_state.json not found -- skip")
        return True, 0

    with open(src, encoding="utf-8") as f:
        data: dict = json.load(f)

    json_count = len(data)
    now = datetime.now(KST).isoformat()

    await conn.execute("BEGIN IMMEDIATE")
    try:
        for url, price in data.items():
            await conn.execute(
                "INSERT OR REPLACE INTO price_state(url, price, updated_at) VALUES (?,?,?)",
                (url, price, now),
            )
        async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
            db_count = (await cur.fetchone())[0]

        if db_count != json_count:
            await conn.execute("ROLLBACK")
            print(
                f"migrate: ERROR price_state row-count mismatch "
                f"(json={json_count}, db={db_count}) -- ROLLBACK"
            )
            return False, 0

        await conn.commit()
        return True, json_count

    except Exception:
        await conn.execute("ROLLBACK")
        raise


async def _migrate_discovery_state(conn) -> tuple[bool, int]:
    """Migrate discovery_state.json -> DB discovery_candidates table.

    Uses count_before/count_after approach to handle pre-existing rows.

    Returns:
        (success, count) — success=True and count=N new rows on success,
        (False, 0) on mismatch or error, (True, 0) if file missing.
    """
    src = Path(DISCOVERY_STATE_FILE)
    if not src.exists():
        print("migrate: discovery_state.json not found -- skip")
        return True, 0

    with open(src, encoding="utf-8") as f:
        data: dict = json.load(f)

    discovered_urls: dict = data.get("discovered_urls", {})
    json_count = len(discovered_urls)

    if json_count == 0:
        print("migrate: discovery_state.json has no discovered_urls -- skip")
        return True, 0

    # Capture row count before transaction
    async with conn.execute("SELECT COUNT(*) FROM discovery_candidates") as cur:
        count_before = (await cur.fetchone())[0]

    await conn.execute("BEGIN IMMEDIATE")
    try:
        for url, discovered_at in discovered_urls.items():
            await conn.execute(
                "INSERT OR IGNORE INTO discovery_candidates"
                "(source, name, url, price, margin_pct, score, discovered_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("discovery_state", None, url, None, None, None, discovered_at),
            )

        async with conn.execute("SELECT COUNT(*) FROM discovery_candidates") as cur:
            count_after = (await cur.fetchone())[0]

        inserted = count_after - count_before
        if inserted != json_count:
            await conn.execute("ROLLBACK")
            print(
                f"migrate: ERROR discovery_state row-count mismatch "
                f"(json={json_count}, inserted={inserted}) -- ROLLBACK"
            )
            return False, 0

        await conn.commit()
        return True, inserted

    except Exception:
        await conn.execute("ROLLBACK")
        raise


def _backup_json(path: str) -> None:
    """Rename original JSON to .bak using Path.rename()."""
    p = Path(path)
    if p.exists():
        p.rename(str(p) + ".bak")


# ── Entry point ───────────────────────────────────────────────────────────────


async def main() -> bool:
    """Run the full migration. Returns True on success, False on failure/refusal."""
    # 1. Bot-running guard
    if LOCK_FILE.exists():
        print(
            "migrate: ERROR bot is running (.main.lock exists). "
            "Stop the bot before migrating."
        )
        return False

    # 2. Open DB (creates tables if needed)
    await db.open_db()

    try:
        conn = db.get_conn()

        # 3. Migrate price_state.json
        price_ok, price_count = await _migrate_price_state(conn)
        if not price_ok:
            return False

        # 4. Migrate discovery_state.json
        disc_ok, disc_count = await _migrate_discovery_state(conn)
        if not disc_ok:
            return False

    finally:
        await db.close_db()

    # 5. Both succeeded — rename JSON files to .bak (after COMMIT)
    _backup_json(STATE_FILE)
    _backup_json(DISCOVERY_STATE_FILE)

    print(f"migrate: price_state: {price_count} items migrated, .bak created")
    print(f"migrate: discovery_state: {disc_count} items migrated, .bak created")
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
