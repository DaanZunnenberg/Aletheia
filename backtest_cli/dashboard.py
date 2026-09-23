from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Same convention as paper/dashboard.py: plain white text, green/red
# reserved strictly for buy-vs-sell and profit-vs-loss.
_GREEN = "green"
_RED = "red"
_BLOTTER_ROWS_SHOWN = 40


@dataclass(frozen=True)
class BacktestRunInfo:
    """Static metadata about the run, shown once in the header -- not re-derived from history every frame."""
    source: str          # recording filename or trade-tape CSV name
    symbol: str
    engine: str           # 'l2_replay' | 'historical'
    params: dict[str, float]
    n_bars_total: int


@dataclass(frozen=True)
class BlotterRow:
    """One bar where inventory changed -- a fill happened, derived from consecutive history rows (no per-fill log in BacktestResult.history)."""
    elapsed_seconds: float
    mid_price: float
    inventory_before: float
    inventory_after: float
    net_pnl_usd: float


def _fmt_price(x: float | None) -> str:
    if x is None:
        return "--"
    return f"{x:,.2f}" if abs(x) >= 1.0 else f"{x:.6f}"


def _fmt_usd(x: float) -> str:
    return f"{x:+,.2f}"


class BacktestDashboard:
    """
    `rich`-based replay viewer for a BacktestResult.history DataFrame --
    same visual language as paper/dashboard.py's MarketDashboard (plain
    white text, green/red reserved for buy/sell and profit/loss, tight
    padding) so a backtest replay looks like the same "trading floor" the
    live paper engine renders, not a different tool.

    Post-hoc replay, not a live-updating engine: core.backtest.l2_replay
    and core.backtest.historical both compute the full BacktestResult
    before returning (there's no way to interrupt mid-replay for a
    genuinely live view without restructuring the replay loop into a
    generator), so backtest_cli/run.py runs the backtest once, then feeds
    this dashboard one history row at a time at a configurable playback
    speed. What's on screen at any moment is real backtest state as of
    that bar, just replayed rather than computed live.
    """

    def _render_header(
        self, info: BacktestRunInfo, bar_index: int, elapsed_seconds: float, cumulative_metrics,
    ) -> Panel:
        progress = bar_index / info.n_bars_total if info.n_bars_total else 0.0
        params_str = " ".join(f"{k}={v}" for k, v in info.params.items())

        title = Text()
        title.append("ALETHEIA BACKTEST REPLAY", style="bold")
        title.append(f"  --  {info.engine}  ", style="bold cyan")
        title.append(f"  {info.symbol}  ", style="bold")
        title.append(f"  bar {bar_index:,}/{info.n_bars_total:,} ({progress:.1%})", style="")
        title.append(f"  t={elapsed_seconds:,.1f}s", style="dim")
        title.append("\n")
        title.append(f"source: {info.source}", style="dim")
        title.append(f"   params: {params_str}", style="dim")
        title.append("\n")

        pnl_style = _GREEN if cumulative_metrics.net_pnl_usd > 0 else (_RED if cumulative_metrics.net_pnl_usd < 0 else "")
        title.append("running: ")
        title.append(f"net {_fmt_usd(cumulative_metrics.net_pnl_usd)}", style=pnl_style)
        title.append(
            f"  sharpe {cumulative_metrics.sharpe:.2f}  maxDD {cumulative_metrics.max_drawdown_usd:,.2f}"
            f"  turnover {cumulative_metrics.turnover:,.2f}  breach {cumulative_metrics.breach_rate:.1%}"
        )
        return Panel(title, box=box.HEAVY, border_style="dim", padding=(0, 1))

    def _render_state_table(self, row) -> Table:
        table = Table(expand=True, box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False, padding=(0, 0))
        for col, justify, width in [
            ("Mid", "right", 12), ("OurBid", "right", 12), ("OurAsk", "right", 12), ("Inventory", "right", 10),
            ("Sigma", "right", 9), ("RlzdPnL", "right", 11), ("uPnL", "right", 11),
            ("Fees", "right", 9), ("Funding", "right", 9), ("NetPnL", "right", 11), ("Breach", "right", 7),
        ]:
            table.add_column(col, justify=justify, width=width, no_wrap=True)

        net_style = _GREEN if row.net_pnl_usd > 0 else (_RED if row.net_pnl_usd < 0 else "")
        inv_style = _GREEN if row.inventory > 0 else (_RED if row.inventory < 0 else "")
        breach_style = "bold white on red" if row.breach else ""
        table.add_row(
            _fmt_price(row.mid_price),
            Text(_fmt_price(row.bid_price), style=_GREEN),
            Text(_fmt_price(row.ask_price), style=_RED),
            Text(f"{row.inventory:+.4f}", style=inv_style),
            f"{row.sigma:.4f}",
            _fmt_usd(row.realized_pnl_usd),
            _fmt_usd(row.unrealized_pnl_usd),
            f"{row.fees_usd:,.2f}",
            _fmt_usd(row.funding_paid_usd),
            Text(_fmt_usd(row.net_pnl_usd), style=net_style),
            Text("BREACH" if row.breach else "ok", style=breach_style),
        )
        return table

    def _render_blotter(self, blotter: list[BlotterRow]) -> Table:
        table = Table(title="Fills (inventory changes)", expand=True, box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
        table.add_column("t", justify="right", width=10, no_wrap=True)
        table.add_column("Mid", justify="right", width=12, no_wrap=True)
        table.add_column("Inventory", justify="right", width=22, no_wrap=True)
        table.add_column("NetPnL", justify="right", width=12, no_wrap=True)

        for b in blotter[-_BLOTTER_ROWS_SHOWN:]:
            delta = b.inventory_after - b.inventory_before
            side_style = _GREEN if delta > 0 else _RED
            table.add_row(
                f"{b.elapsed_seconds:,.1f}",
                _fmt_price(b.mid_price),
                Text(f"{b.inventory_before:+.4f} -> {b.inventory_after:+.4f} ({delta:+.4f})", style=side_style),
                _fmt_usd(b.net_pnl_usd),
            )
        return table

    def render(
        self, info: BacktestRunInfo, bar_index: int, row, cumulative_metrics, blotter: list[BlotterRow],
    ) -> Group:
        header = self._render_header(info, bar_index, row.elapsed_seconds, cumulative_metrics)
        state = self._render_state_table(row)
        blotter_table = self._render_blotter(blotter)
        return Group(header, state, blotter_table)


@dataclass(frozen=True)
class OptionsBlotterRow:
    """One bar where either leg's inventory changed -- see BlotterRow's docstring, same derivation, two legs."""
    elapsed_seconds: float
    leg: str            # 'perp' | 'option'
    mid_price: float
    inventory_before: float
    inventory_after: float
    net_pnl_usd: float


class OptionsPerpDashboard:
    """
    Replay viewer for core.backtest.options_replay's
    OptionsAndPerpBacktestResult -- two-leg analogue of BacktestDashboard:
    a state table with one row per leg (option + perp hedge) instead of
    one row for a single instrument, and a blotter tagging which leg each
    fill belongs to. Same visual convention throughout.
    """

    def _render_header(self, info: BacktestRunInfo, bar_index: int, elapsed_seconds: float, net_pnl_usd: float, breach_rate: float) -> Panel:
        progress = bar_index / info.n_bars_total if info.n_bars_total else 0.0
        params_str = " ".join(f"{k}={v}" for k, v in info.params.items())

        title = Text()
        title.append("ALETHEIA BACKTEST REPLAY", style="bold")
        title.append("  --  options+perp  ", style="bold cyan")
        title.append(f"  {info.symbol}  ", style="bold")
        title.append(f"  bar {bar_index:,}/{info.n_bars_total:,} ({progress:.1%})", style="")
        title.append(f"  t={elapsed_seconds:,.1f}s", style="dim")
        title.append("\n")
        title.append(f"source: {info.source}", style="dim")
        title.append(f"   params: {params_str}", style="dim")
        title.append("\n")

        pnl_style = _GREEN if net_pnl_usd > 0 else (_RED if net_pnl_usd < 0 else "")
        title.append("running: ")
        title.append(f"net {_fmt_usd(net_pnl_usd)} (both legs, USD)", style=pnl_style)
        title.append(f"   perp breach {breach_rate:.1%}")
        return Panel(title, box=box.HEAVY, border_style="dim", padding=(0, 1))

    def _render_state_table(self, row) -> Table:
        table = Table(expand=True, box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False, padding=(0, 0))
        for col, justify, width in [
            ("Leg", "left", 8), ("Mid", "right", 12), ("OurBid", "right", 12), ("OurAsk", "right", 12),
            ("Inventory", "right", 12), ("NetPnL (USD)", "right", 14),
        ]:
            table.add_column(col, justify=justify, width=width, no_wrap=True)

        perp_inv_style = _GREEN if row.perp_inventory > 0 else (_RED if row.perp_inventory < 0 else "")
        perp_pnl_style = _GREEN if row.perp_net_pnl_usd > 0 else (_RED if row.perp_net_pnl_usd < 0 else "")
        table.add_row(
            "perp", _fmt_price(row.perp_mid),
            Text(_fmt_price(row.perp_bid), style=_GREEN), Text(_fmt_price(row.perp_ask), style=_RED),
            Text(f"{row.perp_inventory:+.4f}", style=perp_inv_style), Text(_fmt_usd(row.perp_net_pnl_usd), style=perp_pnl_style),
        )
        opt_inv_style = _GREEN if row.option_inventory > 0 else (_RED if row.option_inventory < 0 else "")
        opt_pnl_style = _GREEN if row.option_net_pnl_usd > 0 else (_RED if row.option_net_pnl_usd < 0 else "")
        table.add_row(
            "option", _fmt_price(row.option_mid),
            Text(_fmt_price(row.option_bid), style=_GREEN), Text(_fmt_price(row.option_ask), style=_RED),
            Text(f"{row.option_inventory:+.4f}", style=opt_inv_style), Text(_fmt_usd(row.option_net_pnl_usd), style=opt_pnl_style),
        )
        return table

    def _render_blotter(self, blotter: list[OptionsBlotterRow]) -> Table:
        table = Table(title="Fills (inventory changes, either leg)", expand=True, box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
        table.add_column("t", justify="right", width=10, no_wrap=True)
        table.add_column("Leg", justify="left", width=8, no_wrap=True)
        table.add_column("Mid", justify="right", width=12, no_wrap=True)
        table.add_column("Inventory", justify="right", width=26, no_wrap=True)
        table.add_column("NetPnL", justify="right", width=12, no_wrap=True)

        for b in blotter[-_BLOTTER_ROWS_SHOWN:]:
            delta = b.inventory_after - b.inventory_before
            side_style = _GREEN if delta > 0 else _RED
            table.add_row(
                f"{b.elapsed_seconds:,.1f}", b.leg, _fmt_price(b.mid_price),
                Text(f"{b.inventory_before:+.4f} -> {b.inventory_after:+.4f} ({delta:+.4f})", style=side_style),
                _fmt_usd(b.net_pnl_usd),
            )
        return table

    def render(
        self, info: BacktestRunInfo, bar_index: int, row, net_pnl_usd: float, breach_rate: float, blotter: list[OptionsBlotterRow],
    ) -> Group:
        header = self._render_header(info, bar_index, row.elapsed_seconds, net_pnl_usd, breach_rate)
        state = self._render_state_table(row)
        blotter_table = self._render_blotter(blotter)
        return Group(header, state, blotter_table)
