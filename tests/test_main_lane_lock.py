import asyncio
import logging

import pytest

import main


@pytest.fixture
def isolated_product_lane_lock(monkeypatch):
    lock = asyncio.Lock()
    monkeypatch.setattr(main, "_PRODUCT_LANE_LOCK", lock)
    return lock


def test_sourcing_price_job_waits_for_product_lane_and_logs(
    monkeypatch, caplog, isolated_product_lane_lock
):
    async def scenario():
        calls = 0

        async def fake_sourcing_price_job():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)

        monkeypatch.setattr(main, "sourcing_price_job", fake_sourcing_price_job)

        await isolated_product_lane_lock.acquire()
        caplog.set_level(logging.INFO, logger="musinsa_bot.main")

        task = asyncio.create_task(main.scheduled_sourcing_price_job())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert not task.done()
        assert "sourcing_price_job waiting: product lane busy" in caplog.text

        isolated_product_lane_lock.release()
        await task

        assert calls == 1
        assert "sourcing_price_job acquired lane after" in caplog.text
        assert "sourcing_price_job finished in" in caplog.text

    asyncio.run(scenario())


def test_sourcing_match_job_still_skips_when_product_lane_busy(
    monkeypatch, caplog, isolated_product_lane_lock
):
    async def scenario():
        calls = 0

        async def fake_sourcing_match_job():
            nonlocal calls
            calls += 1

        monkeypatch.setattr(main, "sourcing_match_job", fake_sourcing_match_job)

        await isolated_product_lane_lock.acquire()
        caplog.set_level(logging.INFO, logger="musinsa_bot.main")

        await main.scheduled_sourcing_match_job()

        assert calls == 0
        assert "sourcing_match_job skipped: product lane busy" in caplog.text

        isolated_product_lane_lock.release()

    asyncio.run(scenario())


def test_sourcing_price_job_scheduler_overrides_in_full_mode(monkeypatch):
    captured = {}

    class _FakeScheduler:
        def __init__(self, *, job_defaults):
            captured["job_defaults"] = job_defaults
            captured["jobs"] = []

        def add_job(self, func, **kwargs):
            captured["jobs"].append((func, kwargs))

        def start(self):
            captured["started"] = True

        def shutdown(self, wait=True):
            pass

    async def _stop_sleep(seconds):
        raise RuntimeError("stop")

    async def _noop():
        return None

    monkeypatch.setattr(main, "AsyncIOScheduler", _FakeScheduler)
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "log_webhook_routing_once", lambda: None)
    monkeypatch.setattr(main, "load_state", lambda: None)
    monkeypatch.setattr(main, "check_once", _noop)
    monkeypatch.setattr(main, "run_initial_coupang_lanes", _noop)
    monkeypatch.setattr(main.asyncio, "sleep", _stop_sleep)
    monkeypatch.setenv("BOT_MODE", "full")

    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(main.main())

    jobs = {kwargs["id"]: kwargs for _, kwargs in captured["jobs"]}
    assert jobs["sourcing_price"]["coalesce"] is False
    assert jobs["sourcing_price"]["max_instances"] == 2
    assert jobs["sourcing_price"]["misfire_grace_time"] == 900
    assert "coalesce" not in jobs["coupang_order"]


def test_sourcing_price_job_scheduler_overrides_in_sourcing_only_mode(monkeypatch):
    captured = {}

    class _FakeScheduler:
        def __init__(self, *, job_defaults):
            captured["job_defaults"] = job_defaults
            captured["jobs"] = []

        def add_job(self, func, **kwargs):
            captured["jobs"].append((func, kwargs))

        def start(self):
            captured["started"] = True

        def shutdown(self, wait=True):
            pass

    async def _stop_sleep(seconds):
        raise RuntimeError("stop")

    async def _noop():
        return None

    monkeypatch.setattr(main, "AsyncIOScheduler", _FakeScheduler)
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "log_webhook_routing_once", lambda: None)
    monkeypatch.setattr(main, "run_initial_sourcing_only_lane", _noop)
    monkeypatch.setattr(main.asyncio, "sleep", _stop_sleep)
    monkeypatch.setenv("BOT_MODE", "sourcing_only")

    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(main.main())

    jobs = {kwargs["id"]: kwargs for _, kwargs in captured["jobs"]}
    assert jobs["sourcing_price"]["coalesce"] is False
    assert jobs["sourcing_price"]["max_instances"] == 2
    assert jobs["sourcing_price"]["misfire_grace_time"] == 900
    assert "coalesce" not in jobs["sourcing_match"]
