import json
from collections.abc import Mapping
from typing import Any


def event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, **payload}


def encode_event(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"
