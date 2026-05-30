"""
Extracts and normalises financial metrics from NSE API responses and combines
current filing facts with historical quarter analytics.
"""
import logging

logger = logging.getLogger(__name__)


def safe_float(val, default=None):
    if val is None or val == "" or val == "-":
        return default
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return default


def parse_result_record(record: dict) -> dict:
    symbol = str(record.get("symbol", record.get("Symbol", ""))).strip().upper()
    company_name = str(record.get("companyName", record.get("symbol", ""))).strip()
    period_end = str(record.get("toDate", record.get("periodEnded", record.get("period", "")))).strip()
    from_date = str(record.get("fromDate", "")).strip()
    filing_time = str(record.get("broadcastDateTime", record.get("broadcastDate", record.get("broadcastDt", "")))).strip()
    xbrl_link = str(record.get("xbrlAttachment", record.get("xbrl", record.get("attchmntFile", "")))).strip()
    quarter_label = _derive_quarter_label(period_end)

    revenue = safe_float(record.get("totalIncome", record.get("netSales", record.get("revenue"))))
    pat = safe_float(record.get("netProfit", record.get("profitAfterTax", record.get("pat"))))
    eps_diluted = safe_float(record.get("dilutedEPS", record.get("eps", record.get("eps_diluted"))))
    operating_profit = safe_float(record.get("ebitda", record.get("operatingProfit", record.get("operating_profit"))))
    ebitda_margin_pct = safe_float(record.get("ebitdaMargin", record.get("ebitda_margin_pct")))
    pat_margin_pct = safe_float(record.get("patMargin", record.get("pat_margin_pct")))

    return {
        "symbol": symbol,
        "company_name": company_name,
        "quarter_label": quarter_label,
        "period_end": period_end,
        "from_date": from_date,
        "filing_time": filing_time,
        "source_url": xbrl_link or "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
        "revenue": revenue,
        "pat": pat,
        "eps_diluted": eps_diluted,
        "operating_profit": operating_profit,
        "ebitda_margin_pct": ebitda_margin_pct,
        "pat_margin_pct": pat_margin_pct,
        "exceptional_items": safe_float(record.get("exceptional_items", record.get("exceptionalItems"))),
    }


def merge_structured_over_current(current: dict, structured: dict) -> dict:
    merged = dict(current)
    for key in [
        'revenue', 'total_income', 'pat', 'pbt', 'finance_cost', 'depreciation',
        'eps_diluted', 'eps_basic', 'operating_profit', 'ebitda_margin_pct',
        'pat_margin_pct', 'exceptional_items'
    ]:
        if structured.get(key) is not None:
            merged[key] = structured.get(key)
    merged['structured_source'] = structured.get('structured_source')
    merged['xbrl_found'] = bool(structured.get('xbrl_found'))
    return merged


def compute_yoy_metrics(current: dict, historical: list) -> dict:
    analytics = {}
    if not historical:
        return analytics

    same_q_history = _find_same_quarter_history(current['quarter_label'], historical)
    rolling = _get_rolling_history(historical, n=8)

    if same_q_history:
        prior = parse_result_record(same_q_history)
        analytics['revenue_yoy_pct'] = _pct_change(current.get('revenue'), prior.get('revenue'))
        analytics['pat_yoy_pct'] = _pct_change(current.get('pat'), prior.get('pat'))
        analytics['eps_yoy_pct'] = _pct_change(current.get('eps_diluted'), prior.get('eps_diluted'))
        if current.get('ebitda_margin_pct') is not None and prior.get('ebitda_margin_pct') is not None:
            analytics['ebitda_margin_change_bps'] = round((current['ebitda_margin_pct'] - prior['ebitda_margin_pct']) * 100, 2)
        if prior.get('pat') is not None and prior['pat'] < 0:
            analytics['low_base_flag'] = True

    if rolling:
        rev_values = [parse_result_record(r).get('revenue') for r in rolling]
        rev_values = [v for v in rev_values if v is not None]
        pat_values = [parse_result_record(r).get('pat') for r in rolling]
        pat_values = [v for v in pat_values if v is not None]
        if rev_values and current.get('revenue') not in (None, 0):
            analytics['revenue_vs_8q_median_pct'] = _pct_change(current['revenue'], _median(rev_values))
        if pat_values and current.get('pat') not in (None, 0):
            analytics['pat_vs_8q_median_pct'] = _pct_change(current['pat'], _median(pat_values))

    exceptional_items = current.get('exceptional_items')
    revenue = current.get('revenue')
    analytics['one_time_gain_flag'] = bool(
        exceptional_items is not None and revenue not in (None, 0) and abs(exceptional_items) >= 0.05 * abs(revenue)
    )
    return analytics


def _derive_quarter_label(period_end: str) -> str:
    try:
        parts = period_end.split('-')
        if len(parts) != 3:
            return period_end
        month_str = parts[1].lower()
        year = int(parts[2])
        month_map = {
            'jun': ('Q1', year, year + 1),
            'sep': ('Q2', year, year + 1),
            'dec': ('Q3', year, year + 1),
            'mar': ('Q4', year - 1, year),
        }
        for key, (q, fy_start, fy_end) in month_map.items():
            if key in month_str:
                return f"{q}FY{str(fy_end)[2:]}"
    except Exception:
        pass
    return period_end


def _find_same_quarter_history(quarter_label: str, historical: list):
    if not quarter_label:
        return None
    q_num = quarter_label[:2]
    fy_str = quarter_label[2:]
    try:
        fy_year = int(fy_str[2:])
        prior_fy = f"FY{str(fy_year - 1).zfill(2)}"
        target = f"{q_num}{prior_fy}"
    except Exception:
        return None
    for rec in historical:
        parsed = parse_result_record(rec)
        if parsed['quarter_label'] == target:
            return rec
    return None


def _get_rolling_history(historical: list, n: int = 8) -> list:
    return historical[:n]


def _pct_change(current, prior):
    if current is None or prior is None or prior == 0:
        return None
    return round(((current - prior) / abs(prior)) * 100, 2)


def _median(values: list) -> float:
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]
