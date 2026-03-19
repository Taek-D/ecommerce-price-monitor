"""Shared fixtures for musinsa-bot tests.

Both musinsa_price_watch and coupang_manager call load_dotenv() at
import time, but that is a no-op when .env is absent — no special
setup is required.
"""
