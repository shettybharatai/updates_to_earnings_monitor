import os
import requests

def send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        return resp.ok
    except Exception:
        return False

def build_message(item: dict, scored: dict) -> str:
    emoji = "ðŸš€" if scored["classification"] == "very_exceptional" else "â­"
    lines = [
        f"{emoji} <b>{item.get('company_name', item.get('symbol', 'Unknown'))}</b> â€” {scored['classification'].replace('_', ' ').title()}",
        f"<b>Symbol:</b> {item.get('symbol', 'NA')}",
        f"<b>Quarter:</b> {item.get('quarter_label', item.get('period_end', 'NA'))}",
        f"<b>Basis:</b> {item.get('basis', 'NA')}",
        f"<b>Filing time:</b> {item.get('filing_time', 'NA')}",
        f"<b>Score:</b> {scored['score']}"
    ]
    if scored["reasons"]:
        lines.append("\n<b>What qualified:</b>")
        lines += [f"  â€¢ {r}" for r in scored["reasons"]]
    if scored["penalties"]:
        lines.append("\n<b>Penalties applied:</b>")
        lines += [f"  âš  {p}" for p in scored["penalties"]]
    if item.get("source_url"):
        lines.append(f"\n<a href='{item['source_url']}'>View Filing</a>")
    return "\n".join(lines)
