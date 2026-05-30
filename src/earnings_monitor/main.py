from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.earnings_monitor.nse_source import fetch_latest_results
from src.earnings_monitor.notifier import send_telegram_message


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

_PARSE_DEBUG_LIMIT = 10
_parse_debug_count = 0


def load_config(path: str = "config.json") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    config["TELEGRAM_BOT_TOKEN"] = os.getenv("TELEGRAM_BOT_TOKEN", "")
    config["TELEGRAM_CHAT_ID"] = os.getenv("TELEGRAM_CHAT_ID", "")
    return config


def load_watchlist(path: str) -> Set[str]:
    p = Path(path)
    if not p.exists():
        logger.warning("Watchlist file not found: %s", path)
        return set()

    with open(p, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return {line.upper() for line in lines}


def load_state(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"processed": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, data: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    global _parse_debug_count

    if not value:
        return None

    value = str(value).strip()
    patterns = [
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%b-%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ]

    for fmt in patterns:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    if _parse_debug_count < _PARSE_DEBUG_LIMIT:
        logger.info("Unparsed datetime sample: raw_value=%r", value)
        _parse_debug_count += 1

    return None


def normalize_symbol(record: Dict[str, Any]) -> str:
    for key in ["symbol", "ticker", "companySymbol", "sm_symbol", "stockCode"]:
        value = record.get(key)
        if value:
            return str(value).strip().upper()
    return ""


def filing_id(record: Dict[str, Any]) -> str:
    parts = [
        normalize_symbol(record),
        str(record.get("broadcastDateTime") or record.get("dateTime") or record.get("an_dt") or ""),
        str(record.get("subject") or record.get("desc") or record.get("headline") or ""),
        str(record.get("attachment") or record.get("attchmntFile") or record.get("xbrl") or ""),
    ]
    return "|".join(part.strip() for part in parts if part is not None)


def extract_timestamp_candidates(record: Dict[str, Any]) -> Dict[str, Any]:
    candidate_keys = [
        "broadcastDateTime",
        "dateTime",
        "an_dt",
        "sort_date",
        "filingDate",
        "filing_date",
        "dt",
        "date",
        "broadcastdate",
        "xbrlDateTime",
        "createdOn",
        "created_at",
        "lastUpdateTime",
        "time",
    ]
    found: Dict[str, Any] = {}
    for key in candidate_keys:
        if key in record:
            found[key] = record.get(key)
    return found


def log_timestamp_debug_samples(rows: List[Dict[str, Any]], sample_size: int = 5) -> None:
    logger.info("Timestamp debug: total rows available=%s", len(rows))

    if not rows:
        return

    for idx, row in enumerate(rows[:sample_size], start=1):
        symbol = normalize_symbol(row)
        ts_fields = extract_timestamp_candidates(row)
        logger.info(
            "Timestamp sample %s | symbol=%s | keys=%s",
            idx,
            symbol or "UNKNOWN",
            ts_fields,
        )

    first_row = rows[0]
    logger.info("First row keys snapshot: %s", sorted(list(first_row.keys())))


def is_recent(record: Dict[str, Any], minutes: int) -> Optional[bool]:
    raw_ts = (
        record.get("broadcastDateTime")
        or record.get("dateTime")
        or record.get("an_dt")
        or record.get("sort_date")
        or record.get("filingDate")
        or record.get("filing_date")
        or record.get("dt")
        or record.get("date")
        or record.get("createdOn")
        or record.get("lastUpdateTime")
    )

    dt = parse_dt(raw_ts)
    if not dt:
        return None

    now = datetime.now(timezone.utc)
    return dt >= now - timedelta(minutes=minutes)


def build_test_message(record: Dict[str, Any]) -> str:
    symbol = normalize_symbol(record) or "UNKNOWN"
    company_name = record.get("companyName") or symbol
    subject = record.get("subject") or record.get("headline") or "Result filing detected"
    return f"Test repo detected filing:\n{company_name} ({symbol})\n{subject}"


def main() -> None:
    config = load_config()
    recent_window_minutes = int(config.get("recent_results_window_minutes", 10))

    watchlist = load_watchlist(config.get("watchlist_file", "data/watchlist.txt"))
    logger.info("Watchlist loaded: %s symbols", len(watchlist))

    state = load_state(config["state_file"])
    processed: Set[str] = set(state.get("processed", []))

    raw_results = fetch_latest_results(config)
    logger.info("Received %s records from NSE", len(raw_results))

    log_timestamp_debug_samples(raw_results, sample_size=5)

    recent_rows: List[Dict[str, Any]] = []
    old_rows = 0
    unparsable_rows = 0

    for row in raw_results:
        recent_flag = is_recent(row, recent_window_minutes)
        if recent_flag is True:
            recent_rows.append(row)
        elif recent_flag is False:
            old_rows += 1
        else:
            unparsable_rows += 1

    logger.info("Recent filings within last %s minutes: %s", recent_window_minutes, len(recent_rows))
    logger.info("Skipped old filings: %s", old_rows)
    logger.info("Skipped unparsable filings: %s", unparsable_rows)

    watchlist_rows = [r for r in recent_rows if normalize_symbol(r) in watchlist]
    logger.info("Recent watchlist filings: %s", len(watchlist_rows))

    new_results: List[Dict[str, Any]] = []
    for row in watchlist_rows:
        fid = filing_id(row)
        if fid not in processed:
            new_results.append(row)

    logger.info("New unprocessed watchlist filings: %s", len(new_results))

    alert_count = 0

    for row in new_results:
        fid = filing_id(row)
        message = build_test_message(row)
        send_telegram_message(config, message)
        processed.add(fid)
        alert_count += 1

    logger.info(
        "Run complete. raw_rows=%s recent_rows=%s old_rows=%s unparsable_rows=%s watchlist_rows=%s new_results=%s alerts_sent=%s",
        len(raw_results),
        len(recent_rows),
        old_rows,
        unparsable_rows,
        len(watchlist_rows),
        len(new_results),
        alert_count,
    )

    save_state(config["state_file"], {"processed": sorted(processed)})


if __name__ == "__main__":
    main()
