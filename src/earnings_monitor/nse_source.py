from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests


logger = logging.getLogger(__name__)


def _default_headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    }


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_default_headers())
    return session


def _warmup_session(session: requests.Session, config: Dict[str, Any]) -> None:
    base_url = config.get("nse_base_url", "https://www.nseindia.com")
    try:
        session.get(base_url, timeout=20)
        time.sleep(1)
    except Exception as exc:
        logger.warning("Failed to warm NSE session: %s", exc)


def _get_json(session: requests.Session, url: str, config: Dict[str, Any]) -> Any:
    _warmup_session(session, config)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        preview = resp.text[:500] if resp.text else ""
        logger.warning("Non-JSON response from NSE url=%s preview=%s", url, preview)
        raise


def fetch_latest_results(
    config: Dict[str, Any],
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    own_session = session is None
    session = session or create_session()

    try:
        url = config["nse_results_api"]
        data = _get_json(session, url, config)

        if isinstance(data, dict):
            for key in ["data", "results", "value", "rows"]:
                if isinstance(data.get(key), list):
                    return data[key]
            return []

        if isinstance(data, list):
            return data

        return []
    finally:
        if own_session:
            session.close()


def fetch_historical_results(
    config: Dict[str, Any],
    symbol: str,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    own_session = session is None
    session = session or create_session()

    try:
        base = config.get("nse_past_results_api", "")
        url = f"{base}{symbol}"
        data = _get_json(session, url, config)

        if isinstance(data, dict):
            for key in ["data", "results", "value", "rows"]:
                if isinstance(data.get(key), list):
                    return data[key]
            return []

        if isinstance(data, list):
            return data

        return []
    finally:
        if own_session:
            session.close()
