from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def chart_data_revision_key_v1(prefix: str, identity: str, payload: Mapping[str, Any]) -> str:
    """Remount a retained Streamlit v2 chart only when its visible data changes.

    ``as_of`` is a calculation clock and may advance without another plotted point.
    Excluding it prevents an unnecessary redraw on every page refresh.
    """
    plotted = {key: value for key, value in payload.items() if key != "as_of"}
    encoded = json.dumps(
        {"identity": identity, "plotted": plotted}, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")
    digest = hashlib.blake2s(encoded, digest_size=16).hexdigest()
    return f"{prefix}-{digest}"
