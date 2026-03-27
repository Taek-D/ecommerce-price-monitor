# Phase 6: Migration - Research

**Researched:** 2026-03-27
**Domain:** SQLite state migration, aiosqlite sync/async bridge, JSON-to-DB data mapping
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **마이그레이션 실행 방식:** 별도 `migrate.py` 스크립트로 수동 실행 (`python migrate.py`)
- **봇 실행 중 감지:** main.py의 기존 single_instance_lock 파일 존재 여부로 봇 실행 중 감지. 실행 중이면 마이그레이션 거부
- **결과 검증:** JSON 키 수 == DB 행 수 (row-count 매치). 불일치 시 자동 ROLLBACK
- **로그 출력:** 요약만 ("✓ price_state: 42개 마이그레이션 완료, .bak 생성" 수준)
- **load_state() 전환:** DB price_state 테이블에서 읽도록 전환 (MIG-04)
- **save_state() 전환:** DB 기반으로 리라이팅. 함수 내부만 변경, 호출자 무수정
- **DB single source of truth:** 마이그레이션 후 price_state.json 파일은 더 이상 생성/업데이트하지 않음
- **트랜잭션 패턴:** BEGIN IMMEDIATE → INSERT → row-count verify → COMMIT or ROLLBACK
- **롤백/백업:** 성공 시 JSON → .bak 리네임. 실패 시 JSON 원본 유지
- **discovery_state.json 없으면:** 조용히 스킵 ("✓ discovery_state.json 없음 — 스킵" 로그)
- **주기적 JSON 백업 (1일 1회 내보내기):** Phase 6 범위 밖 — 향후 페이즈로 이연
- **.bak 자동 삭제:** 불필요 (수동 삭제로 결정)

### Claude's Discretion

- migrate.py 내부 함수 구조 (단일 함수 vs 분리)
- save_state() DB 리라이팅의 구체적 구현 (전체 state dict를 매번 upsert vs 변경된 URL만 upsert)
- discovery_state.json의 JSON 구조 → discovery_candidates 테이블 컬럼 매핑의 세부 사항
- 마이그레이션 중 로깅 레벨 선택

### Deferred Ideas (OUT OF SCOPE)

- 주기적 JSON 백업 (1일 1회 DB → JSON 내보내기) — 향후 페이즈
- .bak 자동 삭제 타이머 — 불필요 (수동 삭제로 결정)
- coupang_manager 내부 상태(_price_state, _sourcing_price_state) DB화 — v1.4 후보 (Out of Scope)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MIG-01 | price_state.json → DB price_state 테이블 마이그레이션 | price_state.json 구조 확인 완료 (236 키, 값은 int\|None). DB price_state 스키마 이미 존재. UPSERT/INSERT OR REPLACE 패턴 사용 |
| MIG-02 | discovery_state.json → DB discovery_candidates 테이블 마이그레이션 | discovery_state.json 구조 확인 완료 (discovered_urls 딕셔너리 531개 URL→date, 후보 candidates 없음). 파일 없을 때 스킵 패턴 필요 |
| MIG-03 | 마이그레이션 후 48시간 JSON 백업 유지 | os.rename(json → json.bak) 패턴. 성공 확인 후에만 리네임. .bak은 수동 삭제 |
| MIG-04 | load_state()를 DB 기반으로 전환 (DB = source of truth) | 현재 load_state()는 동기 함수이고 main.py:374에서 동기 컨텍스트에서 호출됨. open_db() 이후에 호출되므로 asyncio.get_event_loop().run_until_complete() 불필요 — main() 자체가 async이므로 async def load_state()로 전환 필요. 호출자(main.py:374)도 await 추가 필요 |
</phase_requirements>

---

## Summary

Phase 6는 JSON 파일 기반 상태 저장을 aiosqlite DB 기반으로 전환하는 마이그레이션이다. 작업은 두 부분으로 나뉜다: (1) `migrate.py` 스크립트로 기존 JSON 데이터를 DB로 이전하는 일회성 작업, (2) `load_state()`/`save_state()` 함수를 DB 기반으로 교체하여 봇의 상태 저장소를 DB로 전환하는 코드 변경.

핵심 주의사항: `load_state()`는 현재 동기 함수이지만 `main.py:374`에서 `await db.open_db()` 이후에 호출된다. `main()` 함수는 이미 `async def`이므로, `load_state()`를 `async def`로 전환하고 `main.py`에서 `await load_state()`로 호출하면 된다. `save_state()`도 현재 동기이나 호출 위치 4곳(lines 463, 503, 509, 695)이 모두 async 컨텍스트 내부이므로 `async def save_state()`로 전환 가능하다.

`migrate.py`는 aiosqlite를 직접 열지 않고 `db.open_db()`/`db.get_conn()`을 재사용한다. 스크립트는 `asyncio.run(main())`으로 실행하는 async main 패턴을 사용하며, LOCK_FILE 존재 여부로 봇 실행 중 여부를 확인한 후 `BEGIN IMMEDIATE` 트랜잭션 내에서 INSERT를 수행하고 row-count 일치 검증 후 COMMIT/ROLLBACK을 결정한다.

**Primary recommendation:** `migrate.py`를 `asyncio.run()` 기반 async 스크립트로 작성하고, `load_state()`/`save_state()`는 async 함수로 전환하되 내부 구현만 교체한다. 호출자 수정은 `main.py:374`에서 `await` 추가 하나뿐이다.

---

## Standard Stack

### Core (이미 프로젝트에 설치됨)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | 설치됨 | async SQLite 접근 | 프로젝트 기존 DB 스택 |
| asyncio | stdlib | async 실행 컨텍스트 | migrate.py의 asyncio.run() |
| sqlite3 | stdlib | 동기 SQLite (migrate.py 대안) | DB가 이미 aiosqlite로 관리되므로 db.py 재사용 |

### 재사용 가능한 프로젝트 자산

| 자산 | 위치 | 용도 |
|------|------|------|
| `db.open_db()` | db.py | migrate.py에서 DB 연결 초기화 |
| `db.get_conn()` | db.py | INSERT 실행용 커넥션 획득 |
| `db._write_lock` | db.py | save_state()의 upsert 직렬화 |
| `config.STATE_FILE` | config.py | price_state.json 경로 |
| `config.DB_FILE` | config.py | ops.db 경로 |
| `LOCK_FILE` | main.py | 봇 실행 중 감지 상수 |
| `_db_write_guarded()` | musinsa_price_watch.py | save_state() 내 DB 쓰기 실패 처리 |

---

## Architecture Patterns

### 권장 파일 구조

```
E:\musinsa-bot\
├── migrate.py               # 신규: 일회성 마이그레이션 스크립트
├── musinsa_price_watch.py   # 수정: load_state(), save_state() DB 전환
├── main.py                  # 소수정: await load_state() 추가
└── db.py                    # 무수정
```

### Pattern 1: migrate.py — asyncio.run() 기반 async 스크립트

**What:** migrate.py는 `async def main()`을 정의하고 `asyncio.run(main())`으로 실행. `db.open_db()`를 호출하여 기존 DB 모듈 재사용.

**When to use:** aiosqlite는 event loop 안에서만 동작. 동기 스크립트에서 aiosqlite를 직접 사용하면 RuntimeError 발생.

```python
# migrate.py 핵심 골격
import asyncio
import json
import os
from pathlib import Path
import db
from config import STATE_FILE, DB_FILE

LOCK_FILE = Path(__file__).resolve().parent / ".main.lock"

async def _migrate_price_state(conn) -> int:
    """price_state.json → DB price_state 테이블. 삽입 행 수 반환."""
    src = Path(STATE_FILE)
    if not src.exists():
        print("✓ price_state.json 없음 — 스킵")
        return 0
    with open(src, encoding="utf-8") as f:
        data: dict = json.load(f)
    now = __import__("datetime").datetime.now().isoformat()
    async with conn.execute("BEGIN IMMEDIATE"):
        pass  # BEGIN IMMEDIATE via executescript or manual
    # ... INSERT OR REPLACE loop ...
    # row-count verify → COMMIT or ROLLBACK

async def main():
    # 1. 봇 실행 중 감지
    if LOCK_FILE.exists():
        print("ERROR: 봇 실행 중 (.main.lock 존재). 봇 정지 후 재실행.")
        return
    # 2. DB 열기
    await db.open_db()
    # 3. 마이그레이션 실행
    # ...
    await db.close_db()

if __name__ == "__main__":
    asyncio.run(main())
```

### Pattern 2: BEGIN IMMEDIATE 트랜잭션 + row-count 검증

**What:** aiosqlite에서 명시적 트랜잭션 제어.

**Key insight:** aiosqlite는 기본적으로 `isolation_level`이 있어 자동 커밋 모드가 아니다. `conn.execute("BEGIN IMMEDIATE")`로 명시적 트랜잭션 시작, 검증 실패 시 `conn.execute("ROLLBACK")`.

```python
# Source: aiosqlite docs + sqlite3 stdlib patterns
async def _migrate_price_state(conn) -> tuple[bool, int]:
    src = Path(STATE_FILE)
    if not src.exists():
        print("✓ price_state.json 없음 — 스킵")
        return True, 0

    with open(src, encoding="utf-8") as f:
        data: dict = json.load(f)

    json_count = len(data)
    now = __import__("datetime").datetime.now().isoformat()

    await conn.execute("BEGIN IMMEDIATE")
    try:
        for url, price in data.items():
            await conn.execute(
                "INSERT OR REPLACE INTO price_state(url, price, updated_at) VALUES (?,?,?)",
                (url, price, now),
            )
        # row-count 검증
        async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
            row = await cur.fetchone()
        db_count = row[0]
        if db_count != json_count:
            await conn.execute("ROLLBACK")
            print(f"ERROR: row-count 불일치 ({json_count} vs {db_count}) — ROLLBACK")
            return False, 0
        await conn.commit()
        return True, json_count
    except Exception as e:
        await conn.execute("ROLLBACK")
        raise
```

### Pattern 3: load_state() async 전환

**What:** `async def load_state()` — 내부만 DB SELECT로 교체, 시그니처 유지.

**Critical:** `main.py:374`에서 `load_state()`가 호출된다. 현재 동기 호출이지만 `main()`이 `async def`이므로 `await load_state()`로 변경 한 줄이면 된다. `musinsa_price_watch.py:716`의 자체 `main()` 안의 호출도 동일하게 `await` 추가.

```python
# musinsa_price_watch.py 수정 후
async def load_state():
    global state
    try:
        conn = db.get_conn()
        async with conn.execute("SELECT url, price FROM price_state") as cur:
            rows = await cur.fetchall()
        state = {row[0]: row[1] for row in rows}
    except Exception:
        state = {}
```

### Pattern 4: save_state() async 전환 — full upsert 방식

**What:** 호출 시점마다 전체 state dict를 DB에 upsert. 호출자 수정 없이 `async def`로 전환.

**Rationale (Claude's Discretion):** "변경된 URL만 upsert" 방식은 변경 추적 로직이 필요하여 복잡성이 증가한다. 현재 save_state()는 전체 상태를 JSON으로 덮어쓰는 패턴이므로 DB에서도 동일하게 전체 upsert가 일관성 있다. state dict 크기(현재 236개)는 매 호출마다 236개 INSERT OR REPLACE를 실행해도 SQLite WAL 모드에서 충분히 빠르다.

```python
async def save_state():
    if settings.dry_run:
        _log.debug("DRY_RUN state save skipped")
        return

    async def _do_upsert():
        conn = db.get_conn()
        now = datetime.now(KST).isoformat()
        async with db._write_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                for url, price in state.items():
                    await conn.execute(
                        "INSERT OR REPLACE INTO price_state(url, price, updated_at)"
                        " VALUES (?,?,?)",
                        (url, price, now),
                    )
                await conn.commit()
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    await _db_write_guarded(_do_upsert)
```

### Pattern 5: discovery_state.json → discovery_candidates 매핑

**What:** discovery_state.json의 `discovered_urls` 딕셔너리(url → date 문자열)를 discovery_candidates 테이블에 삽입.

**실제 데이터 구조 (검증됨):**
- `discovery_state.json` 최상위 키: `last_run`, `discovered_urls`, `daily_stats`
- `discovered_urls`: `{url: "YYYY-MM-DD"}` 형태의 딕셔너리, 531개 항목
- `candidates` 키: 없음 (빈 리스트)

**컬럼 매핑 (Claude's Discretion):**

| JSON 소스 | DB 컬럼 | 값 |
|-----------|---------|---|
| `discovered_urls` 딕셔너리의 key | `url` | URL 문자열 |
| "unknown" (미저장) | `source` | "discovery_state" |
| NULL | `name` | NULL |
| NULL | `price` | NULL |
| NULL | `margin_pct` | NULL |
| NULL | `score` | NULL |
| `discovered_urls[url]` 값 | `discovered_at` | "YYYY-MM-DD" 문자열 |

```python
async def _migrate_discovery_state(conn) -> tuple[bool, int]:
    src = Path("discovery_state.json")
    if not src.exists():
        print("✓ discovery_state.json 없음 — 스킵")
        return True, 0

    with open(src, encoding="utf-8") as f:
        data: dict = json.load(f)

    discovered_urls: dict = data.get("discovered_urls", {})
    count = len(discovered_urls)

    await conn.execute("BEGIN IMMEDIATE")
    try:
        for url, discovered_at in discovered_urls.items():
            await conn.execute(
                "INSERT OR IGNORE INTO discovery_candidates"
                "(source, name, url, price, margin_pct, score, discovered_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ("discovery_state", None, url, None, None, None, discovered_at),
            )
        async with conn.execute(
            "SELECT COUNT(*) FROM discovery_candidates"
        ) as cur:
            row = await cur.fetchone()
        db_count = row[0]
        if db_count != count:
            await conn.execute("ROLLBACK")
            print(f"ERROR: discovery row-count 불일치 ({count} vs {db_count}) — ROLLBACK")
            return False, 0
        await conn.commit()
        return True, count
    except Exception:
        await conn.execute("ROLLBACK")
        raise
```

### Anti-Patterns to Avoid

- **동기 sqlite3로 별도 연결 열기:** `db.open_db()`가 관리하는 연결과 별개로 동기 sqlite3 연결을 열면 WAL 모드에서 lock 충돌 가능. 항상 `db.get_conn()` 재사용.
- **aiosqlite autocommit 의존:** aiosqlite는 기본적으로 자동 커밋이 아님. `conn.commit()` 명시적 호출 필수.
- **마이그레이션 성공 전 .bak 리네임:** COMMIT 완료 + row-count 검증 이후에만 `os.rename()` 실행.
- **save_state()에서 BEGIN IMMEDIATE 중첩:** `_write_lock`이 이미 직렬화하므로 동일 락 안에서 트랜잭션 중첩 주의. `BEGIN IMMEDIATE`는 `_write_lock` 내부에서만 사용.
- **load_state() 호출자를 모두 수정:** 함수 시그니처를 `async def`로만 변경하면 됨. 내부 구현 교체이므로 `check_once()` 등의 호출자는 수정 불필요. `await` 추가가 필요한 호출자는 `main.py:374`와 `musinsa_price_watch.py:716` 두 곳뿐.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB 연결 열기 | 새 aiosqlite.connect() 호출 | `db.open_db()` + `db.get_conn()` | WAL pragma, 싱글톤 보장 이미 구현됨 |
| DB 쓰기 실패 처리 | try/except + 카운터 직접 구현 | `_db_write_guarded()` | Phase 5에서 완성된 패턴. 5회 실패 시 Discord 알림 포함 |
| 쓰기 직렬화 | 별도 Lock 생성 | `db._write_lock` | 기존 asyncio.Lock 재사용 |
| 봇 실행 중 감지 | psutil PID 체크 직접 구현 | `LOCK_FILE` 존재 여부 확인 | main.py의 `acquire_single_instance_lock()`이 이미 PID 검증 포함 |

**Key insight:** 이 페이즈는 신규 인프라 없이 Phase 4/5에서 구축된 모든 패턴을 재사용한다. migrate.py의 트랜잭션 패턴만 신규 작성이다.

---

## Common Pitfalls

### Pitfall 1: aiosqlite 트랜잭션 상태 혼란

**What goes wrong:** `conn.execute("BEGIN IMMEDIATE")` 실행 후 예외가 발생했을 때 ROLLBACK을 호출하지 않으면 커넥션이 트랜잭션 상태로 남아 이후 모든 쓰기가 실패.

**Why it happens:** aiosqlite는 python sqlite3 래퍼이며, BEGIN 후 COMMIT/ROLLBACK 없이 예외가 발생하면 커넥션 상태가 불확실해짐.

**How to avoid:** `try/except` 블록의 `except` 절에서 반드시 `await conn.execute("ROLLBACK")` 실행. 또는 `async with conn` 컨텍스트 매니저 사용 (자동 ROLLBACK).

**Warning signs:** migrate.py 재실행 시 "database is locked" 또는 "cannot start a transaction" 오류.

### Pitfall 2: load_state() async 전환 후 호출자 누락

**What goes wrong:** `load_state()`를 `async def`로 전환했지만 `await` 없이 호출하면 coroutine 객체를 반환하고 실제 실행되지 않음. `state`가 비어 있는 채로 봇이 시작되어 모든 URL에 대해 "first_seen" 이벤트와 Discord 알림 발생.

**Why it happens:** Python에서 async 함수를 await 없이 호출하면 coroutine 객체만 생성됨.

**How to avoid:** `load_state()` 전환 시 호출 위치 모두 확인:
- `main.py:374`: `load_state()` → `await load_state()`
- `musinsa_price_watch.py:716`: `load_state()` → `await load_state()`

**Warning signs:** 봇 시작 시 state가 비어있고 모든 URL이 "first_seen"으로 처리됨.

### Pitfall 3: row-count 검증 시점 오류 (discovery_candidates)

**What goes wrong:** `discovery_candidates` 테이블에는 마이그레이션 이전에도 Phase 5에서 삽입된 행이 있을 수 있음. `COUNT(*) == json_count`로 검증하면 불일치 발생.

**Why it happens:** INSERT OR IGNORE를 사용할 경우 기존 URL 중복 시 삽입되지 않아 새로 삽입된 수가 json_count보다 작을 수 있음.

**How to avoid:** discovery_candidates row-count 검증은 `COUNT(*) >= count_before + inserted` 방식이나, 또는 `INSERT OR IGNORE` 사용 시 검증을 "오류 없이 완료" 여부로만 확인. 또는 트랜잭션 시작 전 `count_before = SELECT COUNT(*)`로 기준점 설정.

**Warning signs:** "discovery row-count 불일치" 오류로 ROLLBACK 반복.

### Pitfall 4: save_state() 내 BEGIN IMMEDIATE와 _write_lock 중첩

**What goes wrong:** `_write_lock`을 보유한 채로 `BEGIN IMMEDIATE`를 실행하고, 동일 이벤트 루프의 다른 코루틴도 `_write_lock`을 기다리는 경우 데드락 가능성.

**Why it happens:** asyncio.Lock은 재진입 불가. 동일 코루틴 내에서 중첩 획득 시도하면 데드락.

**How to avoid:** `save_state()` 구현 시 `_write_lock` 획득 내부에서만 DB 쓰기 수행. `_db_write_guarded`가 이미 이 패턴을 구현하므로 람다/중첩 함수로 전달.

**Warning signs:** save_state() 호출 후 영원히 응답 없음 (deadlock).

### Pitfall 5: discovery_state.json 구조 오해

**What goes wrong:** `discovery_state.json`에 `candidates` 키가 있다고 가정하고 파싱하면 빈 리스트를 얻음. 실제 데이터는 `discovered_urls` 딕셔너리에 있음.

**Why it happens:** 코드에서 candidates 개념을 사용하지만 JSON 파일에는 `discovered_urls`(URL→date 매핑)만 존재.

**How to avoid:** 반드시 `data.get("discovered_urls", {})` 접근. 실제 파일 구조: `{"last_run": "...", "discovered_urls": {url: date, ...}, "daily_stats": {...}}`.

---

## Code Examples

### JSON → DB UPSERT (price_state)

```python
# Source: 검증된 프로젝트 패턴 (db.py + Phase 5 패턴)
import json
from pathlib import Path
from datetime import datetime
from config import STATE_FILE, KST
import db

async def migrate_price_state() -> tuple[bool, int]:
    src = Path(STATE_FILE)
    if not src.exists():
        print("✓ price_state.json 없음 — 스킵")
        return True, 0

    with open(src, encoding="utf-8") as f:
        data: dict = json.load(f)

    json_count = len(data)
    now = datetime.now(KST).isoformat()
    conn = db.get_conn()

    await conn.execute("BEGIN IMMEDIATE")
    try:
        for url, price in data.items():
            await conn.execute(
                "INSERT OR REPLACE INTO price_state(url, price, updated_at) VALUES (?,?,?)",
                (url, price, now),
            )
        async with conn.execute("SELECT COUNT(*) FROM price_state") as cur:
            row = await cur.fetchone()
        if row[0] != json_count:
            await conn.execute("ROLLBACK")
            return False, 0
        await conn.commit()
        return True, json_count
    except Exception:
        await conn.execute("ROLLBACK")
        raise
```

### .bak 리네임 패턴

```python
# Source: 프로젝트 기존 os.replace 원자적 패턴 응용
import os
from pathlib import Path

def _backup_json(src_path: str) -> None:
    """마이그레이션 성공 후 JSON을 .bak으로 리네임."""
    src = Path(src_path)
    if src.exists():
        bak = Path(src_path + ".bak")
        src.rename(bak)
```

### load_state() — DB 전환 후

```python
# Source: 기존 load_state() 패턴 유지, 내부만 DB SELECT로 교체
import db
import musinsa_price_watch as mpw  # state 글로벌 접근

async def load_state():
    global state
    try:
        conn = db.get_conn()
        async with conn.execute("SELECT url, price FROM price_state") as cur:
            rows = await cur.fetchall()
        state = {row[0]: row[1] for row in rows}
    except Exception:
        state = {}
```

### save_state() — DB 전환 후 (_db_write_guarded 활용)

```python
# Source: Phase 5 _db_write_guarded 패턴 응용
from datetime import datetime
from config import KST
import db

async def save_state():
    if settings.dry_run:
        _log.debug("DRY_RUN state save skipped")
        return

    async def _do_upsert():
        conn = db.get_conn()
        now = datetime.now(KST).isoformat()
        async with db._write_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                for url, price in state.items():
                    await conn.execute(
                        "INSERT OR REPLACE INTO price_state(url, price, updated_at)"
                        " VALUES (?,?,?)",
                        (url, price, now),
                    )
                await conn.commit()
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    await _db_write_guarded(_do_upsert)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| JSON tmp+replace 원자적 쓰기 | DB INSERT OR REPLACE + WAL | Phase 6 | 동시 읽기/쓰기 안전. 봇 재시작 시 파일 손상 없음 |
| `if os.path.exists(STATE_FILE)` | `SELECT COUNT(*) FROM price_state` | Phase 6 | 상태 크기 파악이 O(1) |
| 동기 `load_state()` | async `load_state()` | Phase 6 | open_db()와 동일 이벤트 루프에서 실행 |

**Deprecated/outdated after Phase 6:**
- `price_state.json`: 마이그레이션 후 `.bak`으로 리네임, 더 이상 생성/업데이트 안 함
- `save_state()`의 `tmp_path + os.replace` 패턴: DB upsert로 교체

---

## Open Questions

1. **save_state() 내 _write_lock 중첩 가능성**
   - What we know: `_db_write_guarded`는 락 없이 코루틴만 실행. `_write_lock`은 현재 Phase 5 로깅 헬퍼들에서 직접 사용됨
   - What's unclear: save_state()가 `_write_lock`을 내부에서 획득할 때 동일 이벤트 루프에서 다른 DB 쓰기와 충돌 가능성
   - Recommendation: `_db_write_guarded`에 전달하는 클로저 내부에서만 `_write_lock` 획득. 또는 `_write_lock` 없이 `_db_write_guarded`만 사용하고 직렬화는 `_db_write_guarded`의 순차 실행에 의존

2. **discovery_candidates row-count 검증 기준**
   - What we know: Phase 5 이후 discovery_candidates 테이블에 이미 행이 있을 수 있음
   - What's unclear: 마이그레이션 실행 시점에 테이블이 비어 있는지 여부
   - Recommendation: 트랜잭션 시작 전 `count_before`를 캡처하고 `count_after - count_before == 삽입_시도_수`로 검증. INSERT OR IGNORE이므로 중복 URL은 카운트에서 제외

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (asyncio_mode=auto) |
| Config file | pyproject.toml (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_migration.py -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MIG-01 | price_state.json → price_state 테이블, row-count 일치 | unit | `python -m pytest tests/test_migration.py::test_price_state_row_count_matches -x` | Wave 0 |
| MIG-01 | ROLLBACK 발생 시 DB 무변경 | unit | `python -m pytest tests/test_migration.py::test_price_state_rollback_on_mismatch -x` | Wave 0 |
| MIG-02 | discovered_urls → discovery_candidates 삽입 | unit | `python -m pytest tests/test_migration.py::test_discovery_urls_migrated -x` | Wave 0 |
| MIG-02 | discovery_state.json 없으면 에러 없이 완료 | unit | `python -m pytest tests/test_migration.py::test_discovery_missing_file_skipped -x` | Wave 0 |
| MIG-03 | 성공 후 price_state.json.bak 존재 | unit | `python -m pytest tests/test_migration.py::test_bak_file_created_after_success -x` | Wave 0 |
| MIG-03 | 실패 시 price_state.json 원본 유지 | unit | `python -m pytest tests/test_migration.py::test_original_json_preserved_on_failure -x` | Wave 0 |
| MIG-04 | 봇 재시작 후 load_state()가 DB에서 로드 | unit | `python -m pytest tests/test_migration.py::test_load_state_reads_from_db -x` | Wave 0 |
| MIG-04 | load_state() 후 check_once() 에서 Discord 알림 없음 | unit | `python -m pytest tests/test_migration.py::test_no_spurious_alerts_after_load -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_migration.py -q --tb=short`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_migration.py` — MIG-01~04 전체 커버 (신규 파일)
- [ ] `tests/test_migration.py` — fixture: tmp_path 기반 DB + 임시 JSON 파일 생성

*(기존 test infrastructure: pytest asyncio_mode=auto, tmp_path DB 패턴은 test_db.py/test_event_logging.py에서 검증됨)*

---

## Sources

### Primary (HIGH confidence)

- `E:\musinsa-bot\db.py` — aiosqlite 싱글톤 API, 스키마 정의, WAL 설정
- `E:\musinsa-bot\musinsa_price_watch.py` (lines 246-266, 463-695) — 현재 load_state/save_state 구현, 호출 위치 4곳
- `E:\musinsa-bot\main.py` (lines 26, 84-127, 374) — LOCK_FILE 위치, single_instance_lock 구현, load_state() 호출 컨텍스트
- `E:\musinsa-bot\config.py` — STATE_FILE, DB_FILE 상수
- `E:\musinsa-bot\tests\test_db.py` — 검증된 DB 테스트 패턴 (tmp_path, monkeypatch)
- `E:\musinsa-bot\tests\test_event_logging.py` — _db_write_guarded 테스트 패턴
- `E:\musinsa-bot\price_state.json` — 실제 데이터 구조 (236 키, int|None 값)
- `E:\musinsa-bot\discovery_state.json` — 실제 데이터 구조 (discovered_urls: 531개 URL→date)
- `E:\musinsa-bot\pyproject.toml` — pytest asyncio_mode=auto 확인

### Secondary (MEDIUM confidence)

- aiosqlite BEGIN IMMEDIATE 트랜잭션 패턴: sqlite3 stdlib 동작과 동일하게 검증됨
- INSERT OR REPLACE vs INSERT OR IGNORE 선택: price_state(PRIMARY KEY url)에는 OR REPLACE, discovery_candidates(중복 가능)에는 OR IGNORE

### Tertiary (LOW confidence)

- save_state() 내 _write_lock 중첩 안전성: 이론적으로 안전하나 실제 경쟁 조건은 런타임 검증 필요

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 모두 기존 프로젝트 라이브러리 재사용
- Architecture: HIGH — 기존 패턴(test_db.py, _db_write_guarded) 직접 확인
- Pitfalls: HIGH (load_state async 전환 누락, aiosqlite 트랜잭션) / MEDIUM (discovery row-count 검증 방식)
- Data structures: HIGH — 실제 JSON 파일 직접 파싱으로 확인

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable SQLite/aiosqlite stack, 30-day validity)
