"""Balanced exception scoring with XBRL-aware penalties."""

def score_result(metrics: dict, thresholds: dict) -> dict:
    score = 0.0
    reasons = []
    penalties = []

    revenue_yoy = metrics.get('revenue_yoy_pct')
    pat_yoy = metrics.get('pat_yoy_pct')
    eps_yoy = metrics.get('eps_yoy_pct')
    ebitda_bps = metrics.get('ebitda_margin_change_bps')
    rev_vs_median = metrics.get('revenue_vs_8q_median_pct')
    pat_vs_median = metrics.get('pat_vs_8q_median_pct')
    low_base = metrics.get('low_base_flag', False)
    one_time_gain = metrics.get('one_time_gain_flag', False)
    xbrl_found = metrics.get('xbrl_found', False)

    if revenue_yoy is not None and revenue_yoy >= thresholds['revenue_yoy_pct']:
        score += 2
        reasons.append(f"Revenue YoY {revenue_yoy:.1f}%")

    if pat_yoy is not None and pat_yoy >= thresholds['pat_yoy_pct']:
        score += 2
        reasons.append(f"PAT YoY {pat_yoy:.1f}%")

    if ebitda_bps is not None and ebitda_bps >= thresholds['ebitda_margin_bps']:
        score += 2
        reasons.append(f"EBITDA margin +{int(ebitda_bps)} bps")

    if eps_yoy is not None and eps_yoy >= thresholds['eps_yoy_pct']:
        score += 1
        reasons.append(f"EPS YoY {eps_yoy:.1f}%")

    if rev_vs_median is not None and rev_vs_median >= thresholds['revenue_vs_median_pct']:
        score += 1
        reasons.append(f"Revenue {rev_vs_median:.1f}% above 8-quarter median")

    if pat_vs_median is not None and pat_vs_median >= thresholds['pat_vs_median_pct']:
        score += 1
        reasons.append(f"PAT {pat_vs_median:.1f}% above 8-quarter median")

    if low_base:
        score -= 1
        penalties.append('Low base effect: -1 point')

    if one_time_gain:
        score -= 2
        penalties.append('Material exceptional/one-time item detected: -2 points')

    if not xbrl_found:
        penalties.append('Structured XBRL facts unavailable; no alert unless score qualifies on available metrics')

    classification = 'normal'
    if score >= thresholds['min_score_very_exceptional']:
        classification = 'very_exceptional'
    elif score >= thresholds['min_score_exceptional']:
        classification = 'exceptional'

    return {
        'score': round(score, 1),
        'classification': classification,
        'reasons': reasons,
        'penalties': penalties,
    }
