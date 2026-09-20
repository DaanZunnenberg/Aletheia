from __future__ import annotations

from dataclasses import dataclass

_CLEAR_SCREEN = "\x1b[2J\x1b[H"


@dataclass(frozen=True)
class InstrumentSnapshot:
    instrument: str
    exchange: str
    kind: str          # 'perp-quoted' | 'option-quoted' | 'reference'
    mid: float
    our_bid: float | None
    our_ask: float | None
    position_qty: float
    unrealized_pnl: float
    pnl_ccy: str        # 'USD' or 'BTC'/'ETH' -- option P&L is coin-denominated, see paper/option_quoting.py
    n_fills: int


def _fmt_price(x: float | None) -> str:
    if x is None:
        return "--"
    if abs(x) >= 1.0:
        return f"{x:,.2f}"
    return f"{x:.6f}"


def render_dashboard(snapshots: list[InstrumentSnapshot], elapsed_seconds: float, n_total_fills: int) -> str:
    lines = [
        _CLEAR_SCREEN.rstrip("\n"),
        "ALETHEIA PAPER TRADING -- DRY RUN, NO REAL ORDERS",
        f"elapsed: {elapsed_seconds:7.1f}s   total fills: {n_total_fills}",
        "-" * 112,
        f"{'INSTRUMENT':<22}{'EXCH':<10}{'KIND':<14}{'MID':>16}{'OUR BID':>14}{'OUR ASK':>14}{'POSITION':>12}{'UPNL':>16}",
        "-" * 112,
    ]
    for s in snapshots:
        pnl_str = f"{s.unrealized_pnl:+.4f} {s.pnl_ccy}"
        lines.append(
            f"{s.instrument:<22}{s.exchange:<10}{s.kind:<14}{_fmt_price(s.mid):>16}"
            f"{_fmt_price(s.our_bid):>14}{_fmt_price(s.our_ask):>14}{s.position_qty:>12.4f}{pnl_str:>16}"
        )
    lines.append("-" * 112)
    return "\n".join(lines)
