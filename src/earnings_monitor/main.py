from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

from src.earnings_monitor.nse_source import fetch_latest_results
from src.earnings_monitor.notifier import send_telegram_message
from src.earnings_monitor.scoring import score_result
from src.earnings_monitor.xbrl_parser import parse_xbrl_payload


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.json") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_watchlist(path: str) -> Set[str]:
    p = Path(path)
    if not p.exists():
        logger.warning("Watchlist file not found: %s", path)
        return set()

    if p.suffix.lower() == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(x).strip().upper() for x in data if str(x).strip()}

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
    if not value:
        return None

    value = value.strip()
    patterns = [
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
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


def fetch_text(url: str, timeout: int = 30) -> str:
    if not url:
        return ""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return ""


def collect_context_text(record: Dict[str, Any]) -> str:
    pieces = [
        str(record.get("subject") or ""),
        str(record.get("headline") or ""),
        str(record.get("desc") or ""),
        str(record.get("remarks") or ""),
        str(record.get("bmDesc") or ""),
        str(record.get("companyName") or ""),
    ]
    return " | ".join(x for x in pieces if x)


def is_recent(record: Dict[str, Any], minutes: int) -> Optional[bool]:
    dt = parse_dt(
        record.get("broadcastDateTime")
        or record.get("dateTime")
        or record.get("an_dt")
        or record.get("sort_date")
    )
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    return dt >= now - timedelta(minutes=minutes)


def fetch_historical_payloads(record: Dict[str, Any]) -> Dict[str, str]:
    return {
        "previous_year_payload_text": "",
        "previous_quarter_payload_text": "",
    }


def build_alert_message(
    parsed: Dict[str, Any],
    result: Dict[str, Any],
    record: Dict[str, Any],
) -> str:
    symbol = parsed.get("symbol") or normalize_symbol(record) or "UNKNOWN"
    company_name = parsed.get("company_name") or record.get("companyName") or symbol
    reasons = result.get("reasons", [])
    penalties = result.get("penalties", [])

    lines = [
        f"📊 {company_name} ({symbol})",
        f"Classification: {result['classification'].replace('_', ' ').title()}",
        f"Score: {result['score']}",
        f"Core signals: {result.get('core_signals', 0)}",
        "",
        "Why it qualified:",
    ]
    lines.extend([f"- {r}" for r in reasons[:6]])

    if penalties:
        lines.extend(["", "Cautions:"])
        lines.extend([f"- {p}" for p in penalties[:3]])

    source_url = (
        record.get("xbrl")
        or record.get("attachment")
        or record.get("attchmntFile")
        or record.get("pdfUrl")
        or ""
    )
    if source_url:
        lines.extend(["", f"Source: {source_url}"])

    return "\n".join(lines)


def main() -> None:
    config = load_config()
    thresholds = config["thresholds"]
    recent_window_minutes = int(config.get("recent_results_window_minutes", 10))

    watchlist = load_watchlist(config["watchlist_file"])
    logger.info("Watchlist loaded: %s symbols", len(watchlist))

    state = load_state(config["state_file"])
    processed: Set[str] = set(state.get("processed", []))

    raw_results = fetch_latest_results(config)
    logger.info("Received %s records from NSE", len(raw_results))

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
        symbol = normalize_symbol(row)

        xbrl_url = row.get("xbrl") or row.get("xbrlUrl") or row.get("xmlUrl") or ""
        attachment_url = row.get("attachment") or row.get("attchmntFile") or row.get("pdfUrl") or ""
        primary_url = xbrl_url or attachment_url

        payload_text = fetch_text(primary_url) if primary_url else ""
        historical = fetch_historical_payloads(row)
        context_text = collect_context_text(row)

        parsed = parse_xbrl_payload(
            payload_text=payload_text,
            previous_year_payload_text=historical.get("previous_year_payload_text"),
            previous_quarter_payload_text=historical.get("previous_quarter_payload_text"),
            context_text=context_text,
        )

        parsed["symbol"] = symbol
        parsed["company_name"] = row.get("companyName") or symbol

        result = score_result(parsed, thresholds)

        logger.info(
            "Scored %s | classification=%s score=%s xbrl_found=%s",
            symbol,
            result["classification"],
            result["score"],
            parsed.get("xbrl_found"),
        )

        if result["alert"]:
            message = build_alert_message(parsed, result, row)
            send_telegram_message(config, message)
            alert_count += 1

        processed.add(fid)

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
