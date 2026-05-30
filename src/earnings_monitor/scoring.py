from __future__ import annotations

from typing import Any, Dict, List


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            if not value:
                return default
        return float(value)
    except Exception:
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def score_result(metrics: Dict[str, Any], thresholds: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    penalties: List[str] = []
    positive_signals = 0
    core_signals = 0

    revenue_yoy = _safe_num(metrics.get("revenue_yoy_pct"))
    net_profit_yoy = _safe_num(metrics.get("net_profit_yoy_pct"))
    normalized_pbt_yoy = _safe_num(metrics.get("normalized_pbt_yoy_pct"))
    pbt_vs_revenue_spread = _safe_num(metrics.get("pbt_vs_revenue_spread_pct"))
    ebitda_margin_yoy_bps = _safe_num(metrics.get("ebitda_margin_yoy_bps"))
    ebitda_margin_current = _safe_num(metrics.get("ebitda_margin_current_pct"))
    qoq_revenue = _safe_num(metrics.get("qoq_revenue_pct"))
    qoq_pbt = _safe_num(metrics.get("qoq_pbt_pct"))
    finance_cost_yoy = _safe_num(metrics.get("finance_cost_yoy_pct"))
    exceptional_items_pct_of_pbt = _safe_num(metrics.get("exceptional_items_pct_of_pbt"))
    tax_rate_change_pct = _safe_num(metrics.get("tax_rate_change_pct"))
    revenue_current = _safe_num(metrics.get("revenue_current"))
    has_buyback = _bool(metrics.get("has_buyback"))
    has_bonus = _bool(metrics.get("has_bonus"))
    has_special_dividend = _bool(metrics.get("has_special_dividend"))
    has_revision = _bool(metrics.get("has_revision"))
    has_audit_qualification = _bool(metrics.get("has_audit_qualification"))
    is_seasonal = _bool(metrics.get("is_seasonal"))
    xbrl_found = _bool(metrics.get("xbrl_found", True))

    if not xbrl_found:
        return {
            "score": 0,
            "classification": "unclassified",
            "reasons": ["Structured XBRL data not found"],
            "penalties": [],
            "positive_signals": 0,
            "core_signals": 0,
            "alert": False,
        }

    if revenue_yoy >= thresholds.get("revenue_yoy_good_pct", 12):
        score += 2
        positive_signals += 1
        core_signals += 1
        reasons.append(f"Revenue growth strong at {revenue_yoy:.1f}% YoY")

    if revenue_yoy >= thresholds.get("revenue_yoy_very_strong_pct", 20):
        score += 1
        reasons.append(f"Revenue growth very strong at {revenue_yoy:.1f}% YoY")

    if normalized_pbt_yoy >= thresholds.get("normalized_pbt_yoy_good_pct", 20):
        score += 3
        positive_signals += 1
        core_signals += 1
        reasons.append(f"Normalized PBT grew {normalized_pbt_yoy:.1f}% YoY")
    elif net_profit_yoy >= thresholds.get("net_profit_yoy_good_pct", 20):
        score += 1
        positive_signals += 1
        reasons.append(f"Net profit grew {net_profit_yoy:.1f}% YoY")

    if pbt_vs_revenue_spread >= thresholds.get("pbt_vs_revenue_spread_good_pct", 5):
        score += 2
        positive_signals += 1
        core_signals += 1
        reasons.append(
            f"Normalized PBT outpaced revenue by {pbt_vs_revenue_spread:.1f} percentage points"
        )

    if ebitda_margin_yoy_bps >= thresholds.get("ebitda_margin_expand_good_bps", 250):
        score += 3
        positive_signals += 1
        core_signals += 1
        reasons.append(
            f"EBITDA margin expanded by {ebitda_margin_yoy_bps:.0f} bps to {ebitda_margin_current:.1f}%"
        )

    if not is_seasonal:
        if qoq_revenue >= thresholds.get("qoq_revenue_good_pct", 8):
            score += 2
            positive_signals += 1
            core_signals += 1
            reasons.append(f"Sequential revenue momentum strong at {qoq_revenue:.1f}% QoQ")

        if qoq_pbt >= thresholds.get("qoq_pbt_good_pct", 10):
            score += 2
            positive_signals += 1
            core_signals += 1
            reasons.append(f"Sequential normalized PBT momentum strong at {qoq_pbt:.1f}% QoQ")

    if finance_cost_yoy <= thresholds.get("finance_cost_decline_good_pct", -20):
        score += 2
        positive_signals += 1
        reasons.append(f"Finance costs fell {abs(finance_cost_yoy):.1f}% YoY")

    if has_buyback:
        score += 2
        reasons.append("Buyback announced with results")

    if has_bonus:
        score += 1
        reasons.append("Bonus issue announced with results")

    if has_special_dividend:
        score += 1
        reasons.append("Special dividend announced with results")

    if exceptional_items_pct_of_pbt >= thresholds.get("exceptional_items_penalty_pct", 20):
        score -= 4
        penalties.append(
            f"Exceptional items are {exceptional_items_pct_of_pbt:.1f}% of PBT, reducing earnings quality"
        )

    if revenue_current <= 0:
        score -= 3
        penalties.append("Revenue unavailable or invalid")

    if revenue_yoy < thresholds.get("revenue_yoy_min_pct", 0) and normalized_pbt_yoy > 0:
        score -= 1
        penalties.append("Profit growth without revenue support needs caution")

    if abs(tax_rate_change_pct) >= thresholds.get("tax_rate_change_penalty_pct", 15):
        score -= 1
        penalties.append("Large tax-rate movement may distort bottom-line growth")

    if has_revision:
        score -= 2
        penalties.append("Results appear revised or updated")

    if has_audit_qualification:
        score -= 4
        penalties.append("Audit qualification or adverse comment detected")

    min_exc = thresholds.get("min_score_exceptional", 7)
    min_very_exc = thresholds.get("min_score_very_exceptional", 10)

    classification = "normal"
    alert = False

    major_red_flag = has_audit_qualification or (
        exceptional_items_pct_of_pbt >= thresholds.get("exceptional_items_blocker_pct", 35)
    )

    if score >= min_very_exc and core_signals >= 3 and not major_red_flag:
        classification = "very_exceptional"
        alert = True
    elif score >= min_exc and core_signals >= 2:
        classification = "exceptional"
        alert = True
    elif score >= thresholds.get("min_score_good", 4):
        classification = "good"

    return {
        "score": score,
        "classification": classification,
        "reasons": reasons,
        "penalties": penalties,
        "positive_signals": positive_signals,
        "core_signals": core_signals,
        "alert": alert,
    }
