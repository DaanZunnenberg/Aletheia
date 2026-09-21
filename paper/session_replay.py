from __future__ import annotations

from pathlib import Path

import orjson
import pandas as pd

from paper.session_log import SessionEvent


def load_session(path: Path) -> list[SessionEvent]:
    events = []
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = orjson.loads(line)
            events.append(SessionEvent(**raw))
    return events


def session_to_dataframe(path: Path) -> pd.DataFrame:
    """Flattened view for post-hoc analysis: one row per event, `data` fields as top-level columns."""
    events = load_session(path)
    rows = []
    for e in events:
        row = {"timestamp": e.timestamp, "event_type": e.event_type, "instrument": e.instrument}
        row.update(e.data)
        rows.append(row)
    return pd.DataFrame(rows)


def fills_only(path: Path) -> pd.DataFrame:
    df = session_to_dataframe(path)
    return df[df["event_type"] == "fill"].reset_index(drop=True)


def pnl_curve(path: Path) -> pd.DataFrame:
    """Timestamp + unrealized_pnl for every 'greeks' snapshot event that logged one, per instrument."""
    df = session_to_dataframe(path)
    snapshots = df[df["event_type"] == "greeks"]
    if "unrealized_pnl" not in snapshots.columns:
        return pd.DataFrame(columns=["timestamp", "instrument", "unrealized_pnl"])
    return snapshots[["timestamp", "instrument", "unrealized_pnl"]].reset_index(drop=True)
