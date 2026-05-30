import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.earnings_monitor.http_client import build_session
from src.earnings_monitor.integrated_financials import extract_structured_financials
from src.earnings_monitor.nifty200 import load_nifty200
from src.earnings_monitor.notifier import build_message, send_telegram
from src.earnings_monitor.nse_source import fetch_historical_results, fetch_latest_results
from src.earnings_monitor.parser import (
    compute_yoy_metrics,
    merge_structured_over_current,
    parse_result_record,
)
from src.earnings_monitor.scoring import score_result
from src.earnings_monitor.state import load_state, save_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    return json.loads(Path("config.json").read_text(encoding="utf-8"))


def filing_key(symbol: str, quarter_label: str, filing_time: str, basis: str) -> str:
    return f"{symbol}|{quarter_label}|{filing_time}|{basis}"


def _parse_broadcast_dt(value: str):
    if not value:
        return None

    value = str(value).strip()

    formats = [
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    logger.warning("Could not parse broadcast datetime: %s", value)
    return None


def _extract_broadcast_value(record: dict) -> str:
    return (
        str(record.get("broadcastDateTime", "")).strip()
        or str(record.get("broadcastDate", "")).strip()
        or str(record.get("broadcastDt", "")).strip()
    )


def _split_recent_results(raw_results: list, window_minutes: int):
    recent_results = []
    old_count = 0
    unparsable_count = 0
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(minutes=window_minutes)

    for record in raw_results:
        raw_dt = _extract_broadcast_value(record)
        filing_dt = _parse_broadcast_dt(raw_dt)

        if filing_dt is None:
            unparsable_count += 1
            continue

        if filing_dt >= cutoff:
            recent_results.append(record)
        else:
            old_count += 1

    return recent_results, old_count, unparsable_count


def main():
    config = load_config()
    thresholds = config["thresholds"]
    allow_standalone = config.get("allow_standalone_if_no_consolidated", True)
    recent_window_minutes = int(config.get("recent_results_window_minutes", 10))

    logger.info("Loading Nifty 200 watchlist...")
    watchlist = load_nifty200(config["nifty200_csv_url"])

    logger.info("Loading state...")
    state = load_state(config["state_file"])
    processed = set(state.get("processed", []))

    logger.info("Building NSE session...")
    session = build_session()

    logger.info("Fetching latest NSE quarterly results...")
    raw_results = fetch_latest_results(config["nse_results_api"], session)
    logger.info("Received %d records from NSE", len(raw_results))

    recent_results, old_count, unparsable_count = _split_recent_results(
        raw_results, recent_window_minutes
    )
    logger.info(
        "Recent filings within last %d minutes: %d",
        recent_window_minutes,
        len(recent_results),
    )
    logger.info("Skipped old filings: %d", old_count)
    logger.info("Skipped unparsable filings: %d", unparsable_count)

    changed = False
    alerted = 0
    processed_now = 0
    watchlist_recent = 0

    for record in recent_results:
        parsed = parse_result_record(record)
        symbol = parsed["symbol"]

        if symbol not in watchlist:
            continue

        watchlist_recent += 1

        consolidated_flag = str(record.get("consolidated", "")).strip().lower()
        if consolidated_flag in ("yes", "true", "1", "consolidated"):
            basis = "consolidated"
        elif allow_standalone:
            basis = "standalone"
        else:
            continue

        key = filing_key(symbol, parsed["quarter_label"], parsed["filing_time"], basis)
        if key in processed:
            logger.info(
                "Skipping already processed filing: %s %s (%s)",
                symbol,
                parsed["quarter_label"],
                basis,
            )
            continue

        logger.info(
            "New recent filing detected: %s %s (%s) broadcast=%s",
            symbol,
            parsed["quarter_label"],
            basis,
            parsed["filing_time"],
        )

        structured = extract_structured_financials(record, config)
        merged = merge_structured_over_current(parsed, structured)
        historical = fetch_historical_results(config["nse_past_results_api"], symbol, session)
        analytics = compute_yoy_metrics(merged, historical)

        full_item = {**merged, **analytics, "basis": basis}
        full_item["company_name"] = watchlist[symbol]["company_name"] or parsed["company_name"]

        scored = score_result(full_item, thresholds)
        logger.info(
            "%s %s -> xbrl_found=%s source=%s score=%.1f classification=%s",
            symbol,
            parsed["quarter_label"],
            full_item.get("xbrl_found", False),
            full_item.get("structured_source"),
            scored["score"],
            scored["classification"],
        )

        if scored["classification"] in {"exceptional", "very_exceptional"}:
            message = build_message(full_item, scored)
            success = send_telegram(message)
            if success:
                alerted += 1
                logger.info("Alert sent for %s", symbol)

        processed.add(key)
        changed = True
        processed_now += 1

    if changed:
        state["processed"] = sorted(processed)
        save_state(config["state_file"], state)
        logger.info("State updated. Total processed keys: %d", len(processed))

    logger.info(
        "Run complete. raw_rows=%d recent_rows=%d old_rows=%d unparsable_rows=%d watchlist_recent=%d processed_now=%d alerts_sent=%d",
        len(raw_results),
        len(recent_results),
        old_count,
        unparsable_count,
        watchlist_recent,
        processed_now,
        alerted,
    )


if __name__ == "__main__":
    main()
