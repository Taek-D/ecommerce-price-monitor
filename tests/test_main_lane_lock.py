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
