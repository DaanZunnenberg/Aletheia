from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_CLEAR_SCREEN = "\x1b[2J\x1b[H"  # kept for the plain-text fallback renderer only

_VOL_REGIME_STYLE = {"CALM": "green", "NORMAL": "white", "ACTIVE": "yellow", "VOLATILE": "bold red", "UNKNOWN": "dim"}
_TREND_REGIME_STYLE = {"BULL": "green", "BEAR": "red", "EVEN": "white"}
_CHANGE_STYLE = "bold black on yellow"
_HEADER_STYLE = "bold white on grey15"
_UTILIZATION_STYLE = {"ok": "green", "elevated": "yellow", "breach": "bold white on red"}


@dataclass(frozen=True)
class InstrumentSnapshot:
    instrument: str
    exchange: str
    kind: str          # 'perp-quoted' | 'option-quoted' | 'reference-spot' | 'reference-perpetual'
    mid: float
    our_bid: float | None
    our_ask: float | None
    position_qty: float
    unrealized_pnl: float
    pnl_ccy: str        # 'USD' or 'BTC'/'ETH' -- option P&L is coin-denominated, see paper/option_quoting.py
    n_fills: int
    bid_levels: tuple[tuple[float, float], ...] | None = None  # ladder detail (perps): ((price, size), ...)
    ask_levels: tuple[tuple[float, float], ...] | None = None
    best_bid_size: float | None = None
    best_ask_size: float | None = None
    sigma: float | None = None


@dataclass(frozen=True)
class RiskSnapshot:
    position: float
    max_position: float
    gross_notional_usd: float
    max_gross_notional_usd: float
    daily_loss_usd: float
    max_daily_loss_usd: float
    portfolio_delta: float
    max_abs_delta: float


def utilization(value: float, limit: float) -> float:
    """Fraction of a hard limit consumed, in [0, +inf) -- >= 1.0 means breached."""
    return abs(value) / limit if limit > 0.0 else 0.0


def utilization_tier(u: float) -> str:
    if u >= 1.0:
        return "breach"
    if u >= 0.7:
        return "elevated"
    return "ok"


def spread_bps(bid: float | None, ask: float | None, mid: float) -> float | None:
    if bid is None or ask is None or mid <= 0.0:
        return None
    return (ask - bid) / mid * 1e4


def _fmt_price(x: float | None) -> str:
    if x is None:
        return "--"
    if abs(x) >= 1.0:
        return f"{x:,.2f}"
    return f"{x:.6f}"


def _fmt_size(x: float | None) -> str:
    return "--" if x is None else f"{x:,.3f}"


class MarketDashboard:
    """
    Stateful renderer: remembers each cell's previous value so changed
    cells can be highlighted for one frame (the classic ticker "flash"),
    on top of the standing bid=green/ask=red convention. Built on `rich`
    (Table/Panel/Group) rather than manually padded strings -- proper
    column alignment, real color, and composable panels instead of one
    flat block of text.
    """

    def __init__(self) -> None:
        self._previous: dict[tuple[str, str], object] = {}

    def _cell(self, row_key: str, field: str, value: object, text: str, base_style: str = "") -> Text:
        key = (row_key, field)
        changed = key in self._previous and self._previous[key] != value
        self._previous[key] = value
        return Text(text, style=_CHANGE_STYLE if changed else base_style)

    def render(
        self,
        snapshots: list[InstrumentSnapshot],
        elapsed_seconds: float,
        n_total_fills: int,
        n_hard_hedges: int = 0,
        portfolio_greeks: dict | None = None,
        regimes: dict | None = None,
        warmup_statuses: dict[str, tuple[str, int, int, float]] | None = None,
        recent_fills: list | None = None,
        risk_snapshots: dict | None = None,
    ) -> Group:
        header = Text.assemble(
            ("  ALETHEIA  ", "bold white on dark_green"), ("  PAPER TRADING FLOOR  ", "bold white on grey23"),
            ("  DRY RUN -- NO REAL ORDERS  \n", "bold white on dark_red"),
            (f"elapsed {elapsed_seconds:7.1f}s   ", ""),
            (f"fills {n_total_fills}   ", ""),
            (f"hard hedges {n_hard_hedges}", "bold yellow" if n_hard_hedges else "dim"),
        )

        panels = [Panel(header, box=box.HEAVY, border_style="grey50"), self._render_market_table(snapshots)]

        if risk_snapshots:
            panels.append(self._render_risk_table(risk_snapshots))

        if warmup_statuses:
            not_ready = {ccy: s for ccy, s in warmup_statuses.items() if s[0] != "ready"}
            if not_ready:
                panels.append(self._render_warmup_panel(not_ready))

        if regimes:
            panels.append(self._render_regime_table(regimes))

        if portfolio_greeks:
            panels.append(self._render_greeks_table(portfolio_greeks))

        if recent_fills:
            panels.append(self._render_fills_table(recent_fills))

        return Group(*panels)

    def _render_risk_table(self, risk_snapshots: dict) -> Table:
        table = Table(title="Risk", expand=False, box=box.SIMPLE_HEAVY, header_style=_HEADER_STYLE)
        for col in ("Ccy", "Position", "Notional", "Daily Loss", "|Delta|"):
            table.add_column(col, justify="left" if col == "Ccy" else "right")
        for ccy, r in risk_snapshots.items():
            pos_u = utilization(r.position, r.max_position)
            notional_u = utilization(r.gross_notional_usd, r.max_gross_notional_usd)
            loss_u = utilization(r.daily_loss_usd, r.max_daily_loss_usd)
            delta_u = utilization(r.portfolio_delta, r.max_abs_delta)
            table.add_row(
                ccy,
                Text(f"{r.position:+.4f} / {r.max_position:.2f} ({pos_u:.0%})", style=_UTILIZATION_STYLE[utilization_tier(pos_u)]),
                Text(f"${r.gross_notional_usd:,.0f} / ${r.max_gross_notional_usd:,.0f} ({notional_u:.0%})", style=_UTILIZATION_STYLE[utilization_tier(notional_u)]),
                Text(f"${r.daily_loss_usd:,.0f} / ${r.max_daily_loss_usd:,.0f} ({loss_u:.0%})", style=_UTILIZATION_STYLE[utilization_tier(loss_u)]),
                Text(f"{r.portfolio_delta:+.4f} / {r.max_abs_delta:.2f} ({delta_u:.0%})", style=_UTILIZATION_STYLE[utilization_tier(delta_u)]),
            )
        return table

    def _render_market_table(self, snapshots: list[InstrumentSnapshot]) -> Table:
        table = Table(title="Market", expand=False, box=box.SIMPLE_HEAVY, header_style=_HEADER_STYLE)
        for col, justify in [
            ("Instrument", "left"), ("Exch", "left"), ("Kind", "left"), ("Mid", "right"),
            ("Spread", "right"), ("Spread(bps)", "right"), ("Bid Sz", "right"), ("Ask Sz", "right"),
            ("Our Bid", "right"), ("Our Ask", "right"), ("Position", "right"), ("uPnL", "right"), ("Fills", "right"),
        ]:
            table.add_column(col, justify=justify)

        for s in snapshots:
            spread = None if (s.our_bid is None or s.our_ask is None) else s.our_ask - s.our_bid
            bps = spread_bps(s.our_bid, s.our_ask, s.mid)
            pnl_style = "green" if s.unrealized_pnl > 0 else ("red" if s.unrealized_pnl < 0 else "")

            table.add_row(
                s.instrument, s.exchange, s.kind,
                self._cell(s.instrument, "mid", s.mid, _fmt_price(s.mid)),
                _fmt_price(spread), "--" if bps is None else f"{bps:,.1f}",
                _fmt_size(s.best_bid_size), _fmt_size(s.best_ask_size),
                self._cell(s.instrument, "bid", s.our_bid, _fmt_price(s.our_bid), "green"),
                self._cell(s.instrument, "ask", s.our_ask, _fmt_price(s.our_ask), "red"),
                self._cell(s.instrument, "pos", s.position_qty, f"{s.position_qty:,.4f}"),
                self._cell(s.instrument, "pnl", s.unrealized_pnl, f"{s.unrealized_pnl:+.4f} {s.pnl_ccy}", pnl_style),
                str(s.n_fills),
            )
            if s.bid_levels or s.ask_levels:
                n = max(len(s.bid_levels or ()), len(s.ask_levels or ()))
                for i in range(1, n):  # level 0 already shown as "Our Bid"/"Our Ask" above
                    bid_lvl = s.bid_levels[i] if s.bid_levels and i < len(s.bid_levels) else (None, None)
                    ask_lvl = s.ask_levels[i] if s.ask_levels and i < len(s.ask_levels) else (None, None)
                    table.add_row(
                        f"  L{i}", "", "", "", "", "", _fmt_size(bid_lvl[1]), _fmt_size(ask_lvl[1]),
                        Text(_fmt_price(bid_lvl[0]), style="green"), Text(_fmt_price(ask_lvl[0]), style="red"), "", "", "",
                    )
        return table

    def _render_warmup_panel(self, not_ready: dict[str, tuple[str, int, int, float]]) -> Panel:
        lines = []
        for ccy, (stage, collected, needed, eta) in not_ready.items():
            what = {
                "fast_vol": "collecting price history for the volatility estimate",
                "regime": "volatility ready; building the slower macro-trend baseline for regime detection",
            }.get(stage, stage)
            lines.append(f"{ccy}: {what} -- {collected}/{needed} bars, ~{eta:.0f}s remaining")
        return Panel("\n".join(lines), title="Warming Up", border_style="yellow")

    def _render_regime_table(self, regimes: dict) -> Table:
        table = Table(title="Market Regime", expand=False, box=box.SIMPLE_HEAVY, header_style=_HEADER_STYLE)
        for col in ("Ccy", "HFT Regime", "Macro Trend", "sigma (fast)", "sigma (slow)", "drift"):
            table.add_column(col, justify="right" if col not in ("Ccy", "HFT Regime", "Macro Trend") else "left")
        for ccy, regime in regimes.items():
            table.add_row(
                ccy,
                Text(regime.vol_regime, style=_VOL_REGIME_STYLE.get(regime.vol_regime, "")),
                Text(regime.trend_regime, style=_TREND_REGIME_STYLE.get(regime.trend_regime, "")),
                f"{regime.sigma_fast:.4f}", f"{regime.sigma_slow:.4f}", f"{regime.drift:+.4f}",
            )
        return table

    def _render_greeks_table(self, portfolio_greeks: dict) -> Table:
        table = Table(title="Portfolio Greeks", expand=False, box=box.SIMPLE_HEAVY, header_style=_HEADER_STYLE)
        for col in ("Ccy", "Delta", "Gamma", "Vega", "Theta", "Vanna", "Volga", "Charm"):
            table.add_column(col, justify="left" if col == "Ccy" else "right")
        for ccy, g in portfolio_greeks.items():
            delta_style = "yellow" if abs(g.delta) > 0.3 else ""
            table.add_row(
                ccy, Text(f"{g.delta:+.4f}", style=delta_style), f"{g.gamma:.6f}", f"{g.vega:.4f}",
                f"{g.theta:.4f}", f"{g.vanna:.6f}", f"{g.volga:.6f}", f"{g.charm:.6f}",
            )
        return table

    def _render_fills_table(self, recent_fills: list) -> Table:
        table = Table(title="Recent Fills", expand=False, box=box.SIMPLE_HEAVY, header_style=_HEADER_STYLE)
        for col in ("Time", "Instrument", "Side", "Price", "Size"):
            table.add_column(col, justify="left" if col in ("Time", "Instrument", "Side") else "right")
        for ts, instrument, side, price, size in recent_fills[-8:]:
            side_style = "green" if side == "bid" else "red"
            table.add_row(f"{ts:.1f}s", instrument, Text(side.upper(), style=side_style), _fmt_price(price), _fmt_size(size))
        return table


def render_dashboard(
    snapshots: list[InstrumentSnapshot],
    elapsed_seconds: float,
    n_total_fills: int,
    portfolio_greeks: dict | None = None,
    n_hard_hedges: int = 0,
) -> str:
    """
    Plain-text fallback (no rich dependency needed) -- kept for callers/tests
    that just want a diffable string, e.g. unit tests or a dumb terminal.
    MarketDashboard.render() above is the real, rich-formatted live view
    examples/paper_trading_bot.py actually uses.
    """
    lines = [
        _CLEAR_SCREEN.rstrip("\n"),
        "ALETHEIA PAPER TRADING -- DRY RUN, NO REAL ORDERS",
        f"elapsed: {elapsed_seconds:7.1f}s   total fills: {n_total_fills}   hard hedges: {n_hard_hedges}",
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

    if portfolio_greeks:
        lines.append("PORTFOLIO GREEKS (per underlying)")
        lines.append(f"{'CCY':<6}{'DELTA':>12}{'GAMMA':>12}{'VEGA':>12}{'THETA':>12}{'VANNA':>12}{'VOLGA':>12}{'CHARM':>12}")
        for ccy, g in portfolio_greeks.items():
            lines.append(
                f"{ccy:<6}{g.delta:>12.4f}{g.gamma:>12.6f}{g.vega:>12.4f}"
                f"{g.theta:>12.4f}{g.vanna:>12.6f}{g.volga:>12.6f}{g.charm:>12.6f}"
            )
        lines.append("-" * 112)
    return "\n".join(lines)
