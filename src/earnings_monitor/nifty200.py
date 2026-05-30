import csv
import io
import logging
from src.earnings_monitor.http_client import build_session

logger = logging.getLogger(__name__)

def load_nifty200(csv_url: str) -> dict:
    session = build_session()
    response = session.get(csv_url, timeout=60)
    response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.text)))
    watchlist = {}
    for row in rows:
        symbol = row.get("Symbol", "").strip().upper()
        if symbol:
            watchlist[symbol] = {
                "company_name": row.get("Company Name", "").strip(),
                "industry": row.get("Industry", "").strip(),
                "isin": row.get("ISIN Code", "").strip()
            }
    logger.info("Nifty 200 watchlist loaded: %d companies", len(watchlist))
    return watchlist
