"""
NSE source adapters.

Two endpoints:
  1. corporates-financial-results  -> latest declared results list
  2. results-comparision           -> historical quarterly data per symbol

NSE requires cookie seeding via the homepage before API calls will succeed.
"""
import logging

logger = logging.getLogger(__name__)


def fetch_latest_results(api_url: str, session) -> list:
    """
    Calls the NSE quarterly results API and returns the raw list.
    API: /api/corporates-financial-results?index=equities&period=Quarterly
    """
    try:
        resp = session.get(api_url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        logger.error("Failed to fetch latest results: %s", e)
        return []


def fetch_historical_results(base_url: str, symbol: str, session) -> list:
    """
    Calls the past-results comparison API for a given symbol.
    API: /api/results-comparision?symbol=SYMBOL
    Returns historical quarterly records for YoY/median calculations.
    """
    url = f"{base_url}{symbol}"
    try:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        logger.warning("Could not fetch history for %s: %s", symbol, e)
        return []
