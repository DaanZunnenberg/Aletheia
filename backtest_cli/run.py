"""
Terminal replay viewer for a backtest -- the paper-trading-floor dashboard
(paper/dashboard.py, examples/paper_trading_bot.py), but for a backtest
result instead of a live session. Runs a real backtest once (real recorded
L2 data via core/backtest/l2_replay.py, or a real trade tape via
core/backtest/historical.py), then replays its BacktestResult.history one
bar at a time through a rich Live view at a configurable speed multiplier.

Run:
    python backtest_cli/run.py l2 <recording.jsonl> [--gamma G] [--speed N]
    python backtest_cli/run.py historical <trades.csv> [--gamma G] [--speed N]
    python backtest_cli/run.py options <recording.jsonl> \
        --symbol BTC/USDT:USDT --exchange binanceusdm --market-type perpetual \
        --option-symbol "BTC/USD:BTC-260922-86000-C" --option-exchange deribit \
        --strike 86000 --expiry-ms 1790064000000 --option-type call \
        [--gamma G] [--speed N]

--speed: bars rendered per second (default 30). Use a large number (e.g.
1000) to skim a long recording quickly, or a small one to watch fills
happen at roughly the pace they occurred.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
from rich.live import Live

import numpy as np

from backtest_cli.dashboard import BacktestDashboard, BacktestRunInfo, BlotterRow, OptionsBlotterRow, OptionsPerpDashboard
from core.backtest.historical import build_bars, run_historical_ladder_backtest
from core.backtest.l2_replay import run_l2_replay_backtest
from core.backtest.metrics import BacktestMetrics
from core.backtest.options_replay import OptionSpec, OptionsAndPerpBacktestResult, run_options_and_perp_replay
from core.backtest.simulator import BacktestResult
from core.models.glft import GLFTParams
from core.models.ladder import LadderParams, generate_ladder_quotes
from core.models.options.black76 import OptionType
from core.risk.limits import RiskLimits

_LADDER = LadderParams(n_levels=3, intensity_decay_per_level=0.5, size_decay_per_level=0.6)
_LIMITS = RiskLimits()


def _ladder_fn_factory(gamma: float, kappa: float):
    glft = GLFTParams(gamma=gamma, kappa=kappa, A=0.05, q_max=1.0)

    def factory():
        def fn(state, position, sigma):
            return generate_ladder_quotes(state.mid_price, position, state.mark_price, sigma, glft, _LADDER, _LIMITS)
        return fn
    return factory


def _run_l2(path: Path, symbol: str, exchange: str, market_type: str, gamma: float, kappa: float) -> BacktestResult:
    return run_l2_replay_backtest(
        path, _ladder_fn_factory(gamma, kappa), _LIMITS,
        exchange=exchange, market_type=market_type, symbol=symbol, vol_warmup_bars=30,
    )


def _run_historical(path: Path, gamma: float, kappa: float) -> BacktestResult:
    trades = pd.read_csv(path)
    bars = build_bars(trades, bar_seconds=1.0)
    return run_historical_ladder_backtest(bars, _ladder_fn_factory(gamma, kappa), _LIMITS, vol_warmup_bars=30)


def _options_ladder_fn_factory(gamma: float, kappa: float):
    """Same GLFT ladder as _ladder_fn_factory(), but forwards inventory_override -- core.backtest.options_replay's soft-hedge hook needs the 4-arg form."""
    glft = GLFTParams(gamma=gamma, kappa=kappa, A=0.05, q_max=1.0)

    def factory():
        def fn(state, position, sigma, inventory_override=None):
            return generate_ladder_quotes(
                state.mid_price, position, state.mark_price, sigma, glft, _LADDER, _LIMITS,
                inventory_override=inventory_override,
            )
        return fn
    return factory


def _run_options(
    path: Path, perp_symbol: str, perp_exchange: str, perp_market_type: str,
    option_symbol: str, option_exchange: str, option_market_type: str, option_spec: OptionSpec,
    gamma: float, kappa: float,
) -> OptionsAndPerpBacktestResult:
    return run_options_and_perp_replay(
        path, _options_ladder_fn_factory(gamma, kappa),
        perp_exchange=perp_exchange, perp_market_type=perp_market_type, perp_symbol=perp_symbol,
        option_exchange=option_exchange, option_market_type=option_market_type, option_symbol=option_symbol,
        option_spec=option_spec, risk_limits=_LIMITS, vol_warmup_bars=30,
    )


class _RunningMetrics:
    """
    O(1)-per-bar incremental version of core.backtest.metrics.summarize() --
    recomputing summarize() on a growing history.iloc[:i+1] slice every
    frame is O(n^2) total work over a full replay (each frame re-scans
    everything seen so far), which turns a 64k-bar recording (both real
    recordings on hand are in that range) into a multi-minute stall before
    a single frame renders, independent of playback speed. Welford's
    algorithm gives the running mean/variance for Sharpe in O(1) per bar
    instead.
    """
    def __init__(self, bar_seconds: float, annualization_seconds: float = 365.0 * 24 * 3600.0) -> None:
        self.bar_seconds = bar_seconds
        self.annualization_seconds = annualization_seconds
        self.n = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._prev_pnl: float | None = None
        self.peak_pnl = -np.inf
        self.max_drawdown = 0.0
        self.turnover = 0.0
        self.n_breaches = 0
        self.last_pnl = 0.0

    def update(self, net_pnl_usd: float, inventory_delta: float, breach: bool) -> None:
        # Turnover only accumulates from the *second* bar onward too --
        # core.backtest.metrics.turnover() is inventory.diff().abs().sum(),
        # and pandas .diff() has no prior value on the first row (NaN,
        # dropped by sum()). Counting the first bar's inventory_delta
        # (measured against an implicit 0.0 baseline here) would silently
        # inflate turnover relative to the batch calculation.
        if self._prev_pnl is not None:
            diff = net_pnl_usd - self._prev_pnl
            self.n += 1
            delta = diff - self._mean
            self._mean += delta / self.n
            self._m2 += delta * (diff - self._mean)
            self.turnover += abs(inventory_delta)
        self._prev_pnl = net_pnl_usd
        self.last_pnl = net_pnl_usd
        self.peak_pnl = max(self.peak_pnl, net_pnl_usd)
        self.max_drawdown = max(self.max_drawdown, self.peak_pnl - net_pnl_usd)
        self.n_breaches += int(breach)

    def snapshot(self, n_bars: int) -> BacktestMetrics:
        if self.n < 2 or self._m2 == 0.0:
            sharpe = 0.0
        else:
            var = self._m2 / (self.n - 1)
            periods_per_year = self.annualization_seconds / self.bar_seconds
            sharpe = self._mean / np.sqrt(var) * np.sqrt(periods_per_year)
        return BacktestMetrics(
            net_pnl_usd=self.last_pnl, sharpe=float(sharpe), max_drawdown_usd=self.max_drawdown,
            turnover=self.turnover, breach_rate=(self.n_breaches / n_bars if n_bars else 0.0), n_bars=n_bars,
        )


def replay(result: BacktestResult, info: BacktestRunInfo, bars_per_second: float) -> None:
    dashboard = BacktestDashboard()
    history = result.history
    blotter: list[BlotterRow] = []
    metrics = _RunningMetrics(bar_seconds=1.0)

    # Cap the actual render rate at ~20fps regardless of playback speed --
    # rendering a full rich frame on every bar at a high --speed (e.g.
    # skimming a 64k-bar recording at speed=2000) would make rendering
    # itself the bottleneck. `stride` bars are consumed (metrics updated,
    # blotter appended) between each frame draw.
    target_fps = 20.0
    stride = max(1, round(bars_per_second / target_fps)) if bars_per_second > 0 else len(history)
    frame_interval = stride / bars_per_second if bars_per_second > 0 else 0.0

    with Live(refresh_per_second=20, screen=True) as live:
        prev_inventory = 0.0
        n_total = len(history)
        start_seconds = float(history["elapsed_seconds"].iloc[0]) if n_total else 0.0
        for i, row in enumerate(history.itertuples(index=False)):
            # elapsed_seconds in history is a raw unix timestamp (both
            # engines record it that way -- see core.backtest.historical /
            # core.backtest.l2_replay), not seconds-since-replay-start;
            # rebase here purely for display, the underlying data is untouched.
            row = row._replace(elapsed_seconds=row.elapsed_seconds - start_seconds)

            inventory_delta = row.inventory - prev_inventory
            if inventory_delta != 0.0:
                blotter.append(BlotterRow(
                    elapsed_seconds=row.elapsed_seconds, mid_price=row.mid_price,
                    inventory_before=prev_inventory, inventory_after=row.inventory, net_pnl_usd=row.net_pnl_usd,
                ))
            metrics.update(row.net_pnl_usd, inventory_delta, bool(row.breach))
            prev_inventory = row.inventory

            is_last = i == n_total - 1
            if i % stride == 0 or is_last:
                live.update(dashboard.render(info, i + 1, row, metrics.snapshot(i + 1), blotter))
                if frame_interval > 0.0:
                    time.sleep(frame_interval)

    print(f"\nfinal: {metrics.snapshot(n_total)}")


def replay_options(result: OptionsAndPerpBacktestResult, info: BacktestRunInfo, bars_per_second: float) -> None:
    """Two-leg analogue of replay() -- see OptionsPerpDashboard's docstring. Tracks running net P&L and perp breach rate only (no single-instrument Sharpe/turnover; each leg's own inventory is already visible per-frame in the state table)."""
    dashboard = OptionsPerpDashboard()
    history = result.history
    blotter: list[OptionsBlotterRow] = []

    target_fps = 20.0
    stride = max(1, round(bars_per_second / target_fps)) if bars_per_second > 0 else len(history)
    frame_interval = stride / bars_per_second if bars_per_second > 0 else 0.0

    with Live(refresh_per_second=20, screen=True) as live:
        prev_perp_inv, prev_option_inv = 0.0, 0.0
        n_total = len(history)
        n_breaches = 0
        start_seconds = float(history["elapsed_seconds"].iloc[0]) if n_total else 0.0
        for i, row in enumerate(history.itertuples(index=False)):
            row = row._replace(elapsed_seconds=row.elapsed_seconds - start_seconds)
            n_breaches += int(row.breach)

            if row.perp_inventory != prev_perp_inv:
                blotter.append(OptionsBlotterRow(
                    elapsed_seconds=row.elapsed_seconds, leg="perp", mid_price=row.perp_mid,
                    inventory_before=prev_perp_inv, inventory_after=row.perp_inventory, net_pnl_usd=row.net_pnl_usd,
                ))
                prev_perp_inv = row.perp_inventory
            if row.option_inventory != prev_option_inv:
                blotter.append(OptionsBlotterRow(
                    elapsed_seconds=row.elapsed_seconds, leg="option", mid_price=row.option_mid,
                    inventory_before=prev_option_inv, inventory_after=row.option_inventory, net_pnl_usd=row.net_pnl_usd,
                ))
                prev_option_inv = row.option_inventory

            is_last = i == n_total - 1
            if i % stride == 0 or is_last:
                breach_rate = n_breaches / (i + 1)
                live.update(dashboard.render(info, i + 1, row, row.net_pnl_usd, breach_rate, blotter))
                if frame_interval > 0.0:
                    time.sleep(frame_interval)

    final_row = history.iloc[-1] if n_total else None
    print(f"\nfinal net_pnl_usd: {final_row['net_pnl_usd'] if final_row is not None else 0.0:,.2f}  "
          f"(perp {final_row['perp_net_pnl_usd']:,.2f}, option {final_row['option_net_pnl_usd']:,.2f})"
          if final_row is not None else "\nno bars replayed")
    print(f"final perp inventory: {result.final_perp_position.quantity:+.4f}  "
          f"final option inventory: {result.final_option_position.quantity:+.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("engine", choices=["l2", "historical", "options"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--symbol", default="BTC-PERPETUAL", help="perp symbol (all engines)")
    parser.add_argument("--exchange", default="deribit", help="perp exchange (l2/options)")
    parser.add_argument("--market-type", default="perpetual", help="perp market type (l2/options)")
    parser.add_argument("--option-symbol", default=None)
    parser.add_argument("--option-exchange", default="deribit")
    parser.add_argument("--option-market-type", default="option")
    parser.add_argument("--strike", type=float, default=None)
    parser.add_argument("--expiry-ms", type=float, default=None)
    parser.add_argument("--option-type", choices=["call", "put"], default="call")
    parser.add_argument("--gamma", type=float, default=20.0)
    parser.add_argument("--kappa", type=float, default=1.5)
    parser.add_argument("--speed", type=float, default=30.0, help="bars rendered per second")
    args = parser.parse_args()

    if args.engine == "l2":
        result = _run_l2(args.path, args.symbol, args.exchange, args.market_type, args.gamma, args.kappa)
        info = BacktestRunInfo(
            source=args.path.name, symbol=args.symbol, engine=args.engine,
            params={"gamma": args.gamma, "kappa": args.kappa}, n_bars_total=len(result.history),
        )
        replay(result, info, args.speed)
    elif args.engine == "historical":
        result = _run_historical(args.path, args.gamma, args.kappa)
        info = BacktestRunInfo(
            source=args.path.name, symbol=args.symbol, engine=args.engine,
            params={"gamma": args.gamma, "kappa": args.kappa}, n_bars_total=len(result.history),
        )
        replay(result, info, args.speed)
    else:
        if args.option_symbol is None or args.strike is None or args.expiry_ms is None:
            parser.error("options engine requires --option-symbol, --strike, and --expiry-ms")
        spec = OptionSpec(strike=args.strike, expiry_ms=args.expiry_ms, option_type=OptionType(args.option_type))
        result = _run_options(
            args.path, args.symbol, args.exchange, args.market_type,
            args.option_symbol, args.option_exchange, args.option_market_type, spec,
            args.gamma, args.kappa,
        )
        info = BacktestRunInfo(
            source=args.path.name, symbol=f"{args.symbol} + {args.option_symbol}", engine=args.engine,
            params={"gamma": args.gamma, "kappa": args.kappa}, n_bars_total=len(result.history),
        )
        replay_options(result, info, args.speed)


if __name__ == "__main__":
    main()
