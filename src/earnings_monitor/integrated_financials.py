from __future__ import annotations

import logging
from typing import Dict, Optional

from bs4 import BeautifulSoup

from src.earnings_monitor.http_client import build_session
from src.earnings_monitor.xbrl_parser import XBRLParser

logger = logging.getLogger(__name__)


def _fetch_bytes(url: str, referer: str) -> Optional[bytes]:
    if not url:
        return None
    session = build_session()
    session.headers.update({
        'Referer': referer,
        'Accept': 'application/json, text/plain, text/html, application/xhtml+xml, application/xml, */*',
        'X-Requested-With': 'XMLHttpRequest',
    })
    try:
        resp = session.get(url, timeout=90)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        logger.warning('Integrated filing fetch failed url=%s error=%s', url, exc)
        return None


def _parse_html_table_fallback(payload: bytes) -> Dict[str, Optional[float]]:
    text = payload.decode('utf-8', errors='ignore')
    soup = BeautifulSoup(text, 'lxml')
    table_map = {}
    for row in soup.select('tr'):
        cols = [c.get_text(' ', strip=True) for c in row.select('th,td')]
        if len(cols) >= 2:
            table_map[cols[0].lower()] = cols[1]

    def num(*keys):
        for k in keys:
            v = table_map.get(k.lower())
            if v is None:
                continue
            try:
                return float(v.replace(',', '').replace('%', '').replace('(', '-').replace(')', '').strip())
            except Exception:
                pass
        return None

    revenue = num('revenue from operations', 'revenue', 'net sales', 'total income')
    pat = num('profit after tax', 'pat', 'net profit')
    eps = num('diluted eps', 'eps')
    ebitda = num('ebitda', 'operating profit')
    out = {
        'revenue': revenue,
        'pat': pat,
        'eps_diluted': eps,
        'operating_profit': ebitda,
        'total_income': num('total income'),
        'pbt': num('profit before tax', 'pbt'),
        'finance_cost': num('finance cost', 'finance costs'),
        'depreciation': num('depreciation', 'depreciation and amortisation'),
        'exceptional_items': num('exceptional items', 'exceptional item'),
        'eps_basic': num('basic eps'),
        'ebitda_margin_pct': None,
        'pat_margin_pct': None,
        'xbrl_found': any(v is not None for v in [revenue, pat, eps, ebitda]),
    }
    if out['operating_profit'] is not None and out['revenue'] not in (None, 0):
        out['ebitda_margin_pct'] = round((out['operating_profit'] / out['revenue']) * 100, 2)
    if out['pat'] is not None and out['revenue'] not in (None, 0):
        out['pat_margin_pct'] = round((out['pat'] / out['revenue']) * 100, 2)
    return out


def extract_structured_financials(record: dict, config: dict) -> Dict[str, Optional[float]]:
    referer = config.get('integrated_filing_url', config.get('nse_base_url', 'https://www.nseindia.com'))
    lookup_keys = config.get('xbrl_lookup_keys', ['xbrlAttachment', 'xbrl', 'attchmntFile'])
    attachment_url = ''
    for key in lookup_keys:
        attachment_url = str(record.get(key, '') or '').strip()
        if attachment_url:
            break

    if not attachment_url:
        return {'xbrl_found': False}

    payload = _fetch_bytes(attachment_url, referer)
    if not payload:
        return {'xbrl_found': False}

    parser = XBRLParser()
    try:
        metrics = parser.parse_bytes(payload, source_name=attachment_url)
        if metrics.get('xbrl_found'):
            metrics['structured_source'] = 'xbrl'
            return metrics
    except Exception as exc:
        logger.warning('XBRL parse failed url=%s error=%s', attachment_url, exc)

    html_metrics = _parse_html_table_fallback(payload)
    html_metrics['structured_source'] = 'html_table_fallback' if html_metrics.get('xbrl_found') else None
    return html_metrics
