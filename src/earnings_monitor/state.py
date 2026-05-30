import json
from pathlib import Path

def load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"processed": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"processed": []}

def save_state(path: str, state: dict):
    Path(path).write_text(json.dumps(state, indent=2), encoding="utf-8")
