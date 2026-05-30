from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


def safe_num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("\u00a0", " ").strip()
            if value in {"", "-", "NA", "N/A", "null", "None"}:
                return default
            if value.startswith("(") and value.endswith(")"):
                value = "-" + value[1:-1]
        return float(value)
    except Exception:
        return default


def pct_change(current: float, previous: float, default: float = 0.0) -> float:
    if previous == 0:
        return default
    try:
        return ((current - previous) / abs(previous)) * 100.0
    except Exception:
        return default


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    text = (text or "").lower()
    return any(k.lower() in text for k in keywords)


def _pick_first(data: Dict[str, Any], candidates: List[str], default: float = 0.0) -> float:
    normalized = {_norm(k): v for k, v in data.items()}
    for candidate in candidates:
        key = _norm(candidate)
        if key in normalized:
            return safe_num(normalized[key], default)
    return default


def _extract_json_candidates(payload_text: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    try:
        obj = json.loads(payload_text)
        if isinstance(obj, dict):
            candidates.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    candidates.append(item)
    except Exception:
        pass

    try:
        soup = BeautifulSoup(payload_text, "html.parser")
        scripts = soup.find_all("script")
        for script in scripts:
            text = script.get_text(" ", strip=True)
            if not text:
                continue
            for match in re.findall(r"\{.*?\}", text):
                try:
                    obj = json.loads(match)
                    if isinstance(obj, dict):
                        candidates.append(obj)
                except Exception:
                    continue
    except Exception:
        pass

    return candidates


def _flatten_dict(d: Dict[str, Any], parent: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{parent}.{k}" if parent else str(k)
        if isinstance(v, dict):
            out.update(_flatten_dict(v, key))
        else:
            out[key] = v
    return out


def _extract_inline_xbrl_facts(payload_text: str) -> Dict[str, Any]:
    facts: Dict[str, Any] = {}
    soup = BeautifulSoup(payload_text, "xml")

    for tag_name in ["ix:nonFraction", "ix:nonNumeric", "nonFraction", "nonNumeric"]:
        for node in soup.find_all(tag_name):
            name = node.get("name") or node.get("contextRef") or node.name
            value = node.get_text(" ", strip=True)
            if name and value:
                facts[name] = value

    if facts:
        return facts

    soup = BeautifulSoup(payload_text, "html.parser")
    for node in soup.find_all():
        attrs = node.attrs or {}
        name = attrs.get("name") or attrs.get("data-name") or attrs.get("contextref")
        if name:
            value = node.get_text(" ", strip=True)
            if value:
                facts[str(name)] = value

    return facts


def compute_enhanced_metrics(
    cur: Dict[str, Any],
    prev_yoy: Optional[Dict[str, Any]] = None,
    prev_qoq: Optional[Dict[str, Any]] = None,
    context_text: str = "",
) -> Dict[str, Any]:
    revenue_cur = _pick_first(
        cur,
        [
            "revenue",
            "revenue from operations",
            "income from operations",
            "total income",
            "revenuefromoperations",
            "incomefromoperations",
            "revenuefromcontractswithcustomers",
        ],
    )
    revenue_prev_yoy = _pick_first(prev_yoy or {}, ["revenue", "revenue from operations", "total income"])
    revenue_prev_qoq = _pick_first(prev_qoq or {}, ["revenue", "revenue from operations", "total income"])

    net_profit_cur = _pick_first(
        cur,
        [
            "profit after tax",
            "net profit",
            "profit for the period",
            "profitaftertax",
            "profitfortheperiod",
        ],
    )
    net_profit_prev_yoy = _pick_first(prev_yoy or {}, ["profit after tax", "net profit", "profit for the period"])

    pbt_cur = _pick_first(
        cur,
        [
            "profit before tax",
            "profit before tax from continuing operations",
            "profitbeforetax",
        ],
    )
    pbt_prev_yoy = _pick_first(prev_yoy or {}, ["profit before tax", "profitbeforetax"])
    pbt_prev_qoq = _pick_first(prev_qoq or {}, ["profit before tax", "profitbeforetax"])

    exceptional_cur = _pick_first(
        cur,
        [
            "exceptional items",
            "exceptional item",
            "exceptionalitems",
        ],
    )
    exceptional_prev_yoy = _pick_first(prev_yoy or {}, ["exceptional items", "exceptionalitems"])
    exceptional_prev_qoq = _pick_first(prev_qoq or {}, ["exceptional items", "exceptionalitems"])

    pbt_before_exc_cur = _pick_first(
        cur,
        [
            "profit before exceptional items and tax",
            "profit before exceptional items",
            "profitbeforeexceptionalitemsandtax",
            "profitbeforeexceptionalitems",
        ],
    )
    pbt_before_exc_prev_yoy = _pick_first(
        prev_yoy or {},
        [
            "profit before exceptional items and tax",
            "profit before exceptional items",
            "profitbeforeexceptionalitemsandtax",
            "profitbeforeexceptionalitems",
        ],
    )
    pbt_before_exc_prev_qoq = _pick_first(
        prev_qoq or {},
        [
            "profit before exceptional items and tax",
            "profit before exceptional items",
            "profitbeforeexceptionalitemsandtax",
            "profitbeforeexceptionalitems",
        ],
    )

    normalized_pbt_cur = pbt_before_exc_cur if pbt_before_exc_cur != 0 else (pbt_cur - exceptional_cur)
    normalized_pbt_prev_yoy = (
        pbt_before_exc_prev_yoy if pbt_before_exc_prev_yoy != 0 else (pbt_prev_yoy - exceptional_prev_yoy)
    )
    normalized_pbt_prev_qoq = (
        pbt_before_exc_prev_qoq if pbt_before_exc_prev_qoq != 0 else (pbt_prev_qoq - exceptional_prev_qoq)
    )

    ebitda_cur = _pick_first(
        cur,
        [
            "ebitda",
            "earnings before interest tax depreciation and amortisation",
            "profit before depreciation interest and tax",
            "operating profit",
        ],
    )
    ebitda_prev_yoy = _pick_first(
        prev_yoy or {},
        [
            "ebitda",
            "earnings before interest tax depreciation and amortisation",
            "profit before depreciation interest and tax",
            "operating profit",
        ],
    )

    finance_cost_cur = _pick_first(cur, ["finance costs", "finance cost", "interest expense"])
    finance_cost_prev_yoy = _pick_first(prev_yoy or {}, ["finance costs", "finance cost", "interest expense"])

    tax_expense_cur = _pick_first(cur, ["tax expense", "current tax", "tax"])
    tax_expense_prev_yoy = _pick_first(prev_yoy or {}, ["tax expense", "current tax", "tax"])

    ebitda_margin_cur = (ebitda_cur / revenue_cur * 100.0) if revenue_cur > 0 else 0.0
    ebitda_margin_prev_yoy = (ebitda_prev_yoy / revenue_prev_yoy * 100.0) if revenue_prev_yoy > 0 else 0.0

    revenue_yoy = pct_change(revenue_cur, revenue_prev_yoy)
    qoq_revenue = pct_change(revenue_cur, revenue_prev_qoq)
    net_profit_yoy = pct_change(net_profit_cur, net_profit_prev_yoy)
    normalized_pbt_yoy = pct_change(normalized_pbt_cur, normalized_pbt_prev_yoy)
    qoq_pbt = pct_change(normalized_pbt_cur, normalized_pbt_prev_qoq)
    finance_cost_yoy = pct_change(finance_cost_cur, finance_cost_prev_yoy)

    tax_rate_cur = ((tax_expense_cur / pbt_cur) * 100.0) if pbt_cur else 0.0
    tax_rate_prev_yoy = ((tax_expense_prev_yoy / pbt_prev_yoy) * 100.0) if pbt_prev_yoy else 0.0
    tax_rate_change_pct = tax_rate_cur - tax_rate_prev_yoy

    text = (context_text or "").lower()

    return {
        "xbrl_found": True,
        "revenue_current": revenue_cur,
        "net_profit_current": net_profit_cur,
        "normalized_pbt_current": normalized_pbt_cur,
        "revenue_yoy_pct": revenue_yoy,
        "net_profit_yoy_pct": net_profit_yoy,
        "normalized_pbt_yoy_pct": normalized_pbt_yoy,
        "qoq_revenue_pct": qoq_revenue,
        "qoq_pbt_pct": qoq_pbt,
        "pbt_vs_revenue_spread_pct": normalized_pbt_yoy - revenue_yoy,
        "ebitda_margin_current_pct": ebitda_margin_cur,
        "ebitda_margin_previous_yoy_pct": ebitda_margin_prev_yoy,
        "ebitda_margin_yoy_bps": (ebitda_margin_cur - ebitda_margin_prev_yoy) * 100.0,
        "finance_cost_yoy_pct": finance_cost_yoy,
        "exceptional_items_pct_of_pbt": (abs(exceptional_cur) / abs(pbt_cur) * 100.0) if pbt_cur else 0.0,
        "tax_rate_change_pct": tax_rate_change_pct,
        "has_buyback": _contains_any(text, ["buyback"]),
        "has_bonus": _contains_any(text, ["bonus issue", "bonus shares", "bonus"]),
        "has_special_dividend": _contains_any(text, ["special dividend"]),
        "has_revision": _contains_any(text, ["revised", "revision"]),
        "has_audit_qualification": _contains_any(
            text,
            ["audit qualification", "qualified opinion", "emphasis of matter", "adverse opinion"],
        ),
    }


def parse_xbrl_payload(
    payload_text: str,
    previous_year_payload_text: Optional[str] = None,
    previous_quarter_payload_text: Optional[str] = None,
    context_text: str = "",
) -> Dict[str, Any]:
    if not payload_text:
        return {"xbrl_found": False}

    current_fact_dicts: List[Dict[str, Any]] = []
    previous_yoy_fact_dicts: List[Dict[str, Any]] = []
    previous_qoq_fact_dicts: List[Dict[str, Any]] = []

    inline_current = _extract_inline_xbrl_facts(payload_text)
    if inline_current:
        current_fact_dicts.append(inline_current)

    for obj in _extract_json_candidates(payload_text):
        current_fact_dicts.append(_flatten_dict(obj))

    if previous_year_payload_text:
        inline_prev_yoy = _extract_inline_xbrl_facts(previous_year_payload_text)
        if inline_prev_yoy:
            previous_yoy_fact_dicts.append(inline_prev_yoy)
        for obj in _extract_json_candidates(previous_year_payload_text):
            previous_yoy_fact_dicts.append(_flatten_dict(obj))

    if previous_quarter_payload_text:
        inline_prev_qoq = _extract_inline_xbrl_facts(previous_quarter_payload_text)
        if inline_prev_qoq:
            previous_qoq_fact_dicts.append(inline_prev_qoq)
        for obj in _extract_json_candidates(previous_quarter_payload_text):
            previous_qoq_fact_dicts.append(_flatten_dict(obj))

    current = max(current_fact_dicts, key=lambda x: len(x), default={})
    prev_yoy = max(previous_yoy_fact_dicts, key=lambda x: len(x), default={})
    prev_qoq = max(previous_qoq_fact_dicts, key=lambda x: len(x), default={})

    if not current:
        logger.warning("No structured facts found in current XBRL payload")
        return {"xbrl_found": False}

    metrics = compute_enhanced_metrics(
        cur=current,
        prev_yoy=prev_yoy,
        prev_qoq=prev_qoq,
        context_text=context_text,
    )
    metrics["raw_fact_count_current"] = len(current)
    metrics["raw_fact_count_prev_yoy"] = len(prev_yoy)
    metrics["raw_fact_count_prev_qoq"] = len(prev_qoq)
    return metrics
