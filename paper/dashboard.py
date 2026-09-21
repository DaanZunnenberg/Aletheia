from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_CLEAR_SCREEN = "\x1b[2J\x1b[H"  # kept for the plain-text fallback renderer only

# Plain white terminal text. Green/red is reserved strictly for buy-vs-sell
# (bid/ask) and profit-vs-loss -- not used as decoration elsewhere.
_GREEN = "green"
_RED = "red"
_VOL_REGIME_STYLE = {"CALM": "", "NORMAL": "", "ACTIVE": "bold yellow", "VOLATILE": "bold red", "UNKNOWN": "dim"}
_TREND_REGIME_STYLE = {"BULL": _GREEN, "BEAR": _RED, "EVEN": ""}
_UTILIZATION_STYLE = {"ok": "", "elevated": "bold yellow", "breach": "bold white on red"}
_BLOTTER_ROWS_SHOWN = 40


@dataclass(frozen=True)
class BlotterRow:
    """
    One line of the dashboard's blotter -- every event type (quote, fill,
    hedge) fills the same fixed set of columns, leaving a field blank
    (None) rather than inventing a differently-shaped row.

    A "quote" row is a single per-tick snapshot combining the real exchange
    order book (Book Bid/Ask, the market as it actually is) with our own
    resting quote (Our Bid/Ask) -- these used to be two separate log lines
    (a "book" event and a "quote" event) for the same tick; merged into one
    row here. Side/Price/Size/Fee/Slippage describe a single order-level
    trade (a fill or hedge). Note carries whatever doesn't fit those (ladder
    level count, delta before/after a hedge).
    """
    timestamp: float
    instrument: str
    event_type: str
    side: str | None = None   # 'bid' | 'ask' | 'buy' | 'sell'
    price: float | None = None
    size: float | None = None
    fee: float | None = None        # exchange fee, USD, positive = cost (negative = maker rebate)
    slippage: float | None = None   # execution price minus reference mid at trade time, USD
    book_bid: float | None = None
    book_ask: float | None = None
    book_bid_size: float | None = None
    book_ask_size: float | None = None
    our_bid: float | None = None
    our_ask: float | None = None
    note: str = ""


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
    bid_levels: tuple[tuple[float, float], ...] | None = None  # our own ladder detail (perps): ((price, size), ...)
    ask_levels: tuple[tuple[float, float], ...] | None = None
    best_bid_size: float | None = None
    best_ask_size: float | None = None
    sigma: float | None = None
    book_bids: tuple[tuple[float, float], ...] = ()  # real exchange order book depth, top N levels
    book_asks: tuple[tuple[float, float], ...] = ()
    # Option pricing/stat-arb detail (option-quoted instruments only):
    realized_vol: float | None = None   # RV fed into the quote, core.models.volatility.ewma_volatility
    fair_vol: float | None = None       # IV we actually quote at -- realized_vol * VRP_MULTIPLIER (paper/option_quoting.py)
    theo_price: float | None = None     # Black-76 mid at fair_vol, coin-denominated (comparable to `mid`)


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
    return "--" if x is None else f"{x:,.4f}"


class MarketDashboard:
    """
    `rich`-based live terminal view, focused on the primary currency
    (BTC): a compact one-line status strip (status/regime/Greeks in words)
    plus a one-line ETH reference strip (dimmer, awareness only, no full
    breakdown), a per-instrument "Book" table (perp + option side by side
    by row, including option pricing detail -- realized vol, the IV we
    actually quote at, the VRP edge between them, and our theoretical
    price vs. the market's), and one scrolling blotter table (one row per
    discrete event -- a merged book+quote snapshot, a fill, or a hard
    hedge -- newest at the bottom). Tight panel/table padding throughout.
    Plain white text; green/red appear only for buy-vs-sell (bid/ask) and
    profit-vs-loss, never as decoration.
    """

    _PRIMARY_CCY = "BTC"

    def _render_status_line(
        self, ccy: str, regime, warmup_status: tuple[str, int, int, float] | None, greeks, dim: bool = False,
    ) -> Text:
        base = "dim" if dim else ""
        text = Text()
        text.append(f"{ccy}  ", style="bold" if not dim else "bold dim")

        stage, collected, needed, eta = warmup_status or ("ready", 0, 0, 0.0)
        if stage == "ready":
            text.append("READY", style="bold green" if not dim else "dim")
        else:
            text.append(f"warmup:{stage} {collected}/{needed} ~{eta:.0f}s", style="bold yellow" if not dim else "dim")

        vol_regime = regime.vol_regime if regime else "--"
        trend_regime = regime.trend_regime if regime else "--"
        text.append("  ")
        text.append(vol_regime, style=(_VOL_REGIME_STYLE.get(vol_regime, "dim") if not dim else "dim"))
        text.append("/")
        text.append(trend_regime, style=(_TREND_REGIME_STYLE.get(trend_regime, "dim") if not dim else "dim"))

        if greeks is not None:
            delta_style = ("" if dim else (_GREEN if greeks.delta > 0 else (_RED if greeks.delta < 0 else "")))
            text.append("  Delta ")
            text.append(f"{greeks.delta:+.4f}", style=delta_style)
            text.append(f"  Gamma {greeks.gamma:.6f}  Vega {greeks.vega:.4f}  Theta {greeks.theta:.4f}", style=base)
        else:
            text.append("  Delta --  Gamma --  Vega --  Theta --", style=base)
        return text

    def _render_book_table(
        self,
        ccy: str,
        snapshots: list[InstrumentSnapshot],
        risk_snapshots: dict,
    ) -> Table:
        # A real Table, not hand-padded text -- rich sizes every column to its
        # widest cell and aligns the whole grid for us. One row per
        # instrument (perp + option), not per currency, so option pricing
        # detail (RV/IV/edge/theo) has somewhere to live without inventing a
        # second table -- perp rows simply leave those columns blank.
        table = Table(title=f"{ccy} Book", expand=True, box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
        for col, justify in [
            ("Instrument", "left"), ("Kind", "left"), ("Our Bid", "right"), ("Our Ask", "right"),
            ("Mkt Mid", "right"), ("Position", "right"), ("Fills", "right"), ("Unrealized P&L", "right"),
            ("Realized Vol", "right"), ("Fair Vol (IV)", "right"), ("VRP Edge", "right"), ("Theo Px", "right"),
        ]:
            table.add_column(col, justify=justify)

        rows = [s for s in snapshots if s.instrument.startswith(ccy) and s.kind in ("perp-quoted", "option-quoted")]
        if not rows:
            table.add_row("--", "warming up", *([""] * 10))
            return table

        r = risk_snapshots.get(ccy)
        breach_style = lambda u: _UTILIZATION_STYLE[utilization_tier(u)]  # noqa: E731

        for s in rows:
            kind_label = "perp" if s.kind == "perp-quoted" else "option"
            if s.kind == "perp-quoted" and r is not None:
                pos_style = _GREEN if r.position > 0 else (_RED if r.position < 0 else "")
                position = Text(f"{r.position:+.4f}", style=pos_style or breach_style(utilization(r.position, r.max_position)))
            else:
                pos_style = _GREEN if s.position_qty > 0 else (_RED if s.position_qty < 0 else "")
                position = Text(f"{s.position_qty:+.4f}", style=pos_style)

            pnl_style = _GREEN if s.unrealized_pnl > 0 else (_RED if s.unrealized_pnl < 0 else "")
            pnl = Text(f"{s.unrealized_pnl:+.4f}{s.pnl_ccy}", style=pnl_style)

            if s.fair_vol is not None and s.realized_vol is not None:
                vrp_edge = s.fair_vol - s.realized_vol
                edge_text = Text(f"{vrp_edge:+.4f}", style=_GREEN if vrp_edge > 0 else (_RED if vrp_edge < 0 else ""))
                realized_vol_cell, fair_vol_cell = f"{s.realized_vol:.4f}", f"{s.fair_vol:.4f}"
            else:
                edge_text = realized_vol_cell = fair_vol_cell = "--"

            if s.theo_price is not None:
                # theo vs. real market mid -- positive means our model thinks the
                # option is cheap relative to where the market itself trades.
                theo_edge = s.theo_price - s.mid
                theo_cell = Text(f"{s.theo_price:.6f}", style=_GREEN if theo_edge > 0 else (_RED if theo_edge < 0 else ""))
            else:
                theo_cell = "--"

            table.add_row(
                s.instrument, kind_label,
                Text(_fmt_price(s.our_bid), style=_GREEN if s.our_bid is not None else ""),
                Text(_fmt_price(s.our_ask), style=_RED if s.our_ask is not None else ""),
                _fmt_price(s.mid), position, str(s.n_fills), pnl,
                realized_vol_cell, fair_vol_cell, edge_text, theo_cell,
            )
        return table

    def _render_blotter(self, ccy: str, event_log: list[BlotterRow]) -> Table:
        table = Table(title=f"{ccy} Blotter", expand=True, box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
        table.add_column("Time", justify="right", width=7, no_wrap=True)
        table.add_column("Instrument", justify="left", width=18, no_wrap=True, overflow="ellipsis")
        table.add_column("Type", justify="left", width=5, no_wrap=True)
        table.add_column("Side", justify="left", width=4, no_wrap=True)
        table.add_column("Price", justify="right", width=11, no_wrap=True)
        table.add_column("Size", justify="right", width=9, no_wrap=True)
        table.add_column("Fee", justify="right", width=8, no_wrap=True)
        table.add_column("Slip", justify="right", width=8, no_wrap=True)
        table.add_column("BookBid", justify="right", width=11, no_wrap=True)
        table.add_column("BookAsk", justify="right", width=11, no_wrap=True)
        table.add_column("OurBid", justify="right", width=11, no_wrap=True)
        table.add_column("OurAsk", justify="right", width=11, no_wrap=True)
        table.add_column("Note", justify="left", ratio=1, no_wrap=True, overflow="ellipsis")

        for row in event_log[-_BLOTTER_ROWS_SHOWN:]:
            side_style = _GREEN if row.side in ("bid", "buy") else (_RED if row.side in ("ask", "sell") else "")
            fee_style = _RED if (row.fee or 0.0) > 0 else (_GREEN if (row.fee or 0.0) < 0 else "")
            table.add_row(
                f"{row.timestamp:.2f}", row.instrument, row.event_type,
                Text(row.side or "", style=side_style),
                Text(_fmt_price(row.price), style=side_style),
                Text(_fmt_size(row.size), style=side_style),
                Text(_fmt_price(row.fee), style=fee_style),
                Text(_fmt_price(row.slippage), style=_RED if (row.slippage or 0.0) != 0.0 else ""),
                Text(_fmt_price(row.book_bid), style=_GREEN if row.book_bid is not None else ""),
                Text(_fmt_price(row.book_ask), style=_RED if row.book_ask is not None else ""),
                Text(_fmt_price(row.our_bid), style=_GREEN if row.our_bid is not None else ""),
                Text(_fmt_price(row.our_ask), style=_RED if row.our_ask is not None else ""),
                row.note,
            )
        return table

    def render(
        self,
        snapshots: list[InstrumentSnapshot],
        elapsed_seconds: float,
        n_total_fills: int,
        n_hard_hedges: int = 0,
        portfolio_greeks: dict | None = None,
        regimes: dict | None = None,
        warmup_statuses: dict[str, tuple[str, int, int, float]] | None = None,
        risk_snapshots: dict | None = None,
        event_log: list[BlotterRow] | None = None,
    ) -> Group:
        portfolio_greeks, regimes, warmup_statuses, risk_snapshots = (
            portfolio_greeks or {}, regimes or {}, warmup_statuses or {}, risk_snapshots or {}
        )
        ccy = self._PRIMARY_CCY
        other_ccys = sorted((set(risk_snapshots) | set(regimes) | set(warmup_statuses) | set(portfolio_greeks)) - {ccy})

        title = Text.assemble(
            ("ALETHEIA PAPER TRADING FLOOR", "bold"), ("  --  DRY RUN, NO REAL ORDERS  ", "bold red"),
            (f"  elapsed {elapsed_seconds:7.1f}s", ""),
            (f"  fills {n_total_fills}", ""),
            (f"  hard hedges {n_hard_hedges}", "bold yellow" if n_hard_hedges else "dim"),
            "\n",
            self._render_status_line(ccy, regimes.get(ccy), warmup_statuses.get(ccy), portfolio_greeks.get(ccy)),
        )
        for other in other_ccys:
            title.append("\n")
            title.append(self._render_status_line(other, regimes.get(other), warmup_statuses.get(other), portfolio_greeks.get(other), dim=True))

        header = Panel(title, box=box.HEAVY, border_style="dim", padding=(0, 1))
        book_table = self._render_book_table(ccy, snapshots, risk_snapshots)
        blotter = self._render_blotter(ccy, [row for row in (event_log or []) if row.instrument.startswith(ccy)])

        return Group(header, book_table, blotter)


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
