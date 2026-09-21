from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import orjson


@dataclass(frozen=True)
class SessionEvent:
    """One line of the session log. event_type: 'quote' | 'fill' | 'greeks' | 'hedge' | 'breach'."""
    timestamp: float
    event_type: str
    instrument: str
    data: dict[str, Any] = field(default_factory=dict)


class SessionLogger:
    """
    Append-only JSONL writer for a paper trading session -- every quote,
    fill, portfolio-Greeks snapshot, and hedge action, one line per event.

    Without this, a paper session's entire history vanished when the
    process exited: no way to reconstruct a P&L curve, diff one run against
    another, or debug why a specific quote/hedge fired after the fact.
    Flushed on every write (not buffered) -- a paper session that crashes
    mid-run should still have a usable log up to the crash point.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", buffering=1)

    def log(self, event: SessionEvent) -> None:
        # OPT_SERIALIZE_NUMPY: event.data commonly holds numpy scalars (np.float64
        # from ewma_volatility, black76_greeks, etc.), which orjson otherwise rejects.
        self._file.write(orjson.dumps(asdict(event), option=orjson.OPT_SERIALIZE_NUMPY).decode() + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
