from __future__ import annotations

import random

import pandas as pd
import pytest

from backtest_cli.dashboard import BacktestDashboard, BacktestRunInfo
from backtest_cli.run import _RunningMetrics
from core.backtest.metrics import summarize


def _synthetic_history(n: int, seed: int = 0) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    inventory = 0.0
    net_pnl = 0.0
    for i in range(n):
        if i % 7 == 0:
            inventory += rng.choice([-0.1, 0.1])
        net_pnl += rng.uniform(-2.0, 3.0)
        rows.append({
            "elapsed_seconds": float(i), "mid_price": 80_000.0 + i, "sigma": 0.5,
            "inventory": inventory, "bid_price": 79_999.0, "ask_price": 80_001.0,
            "breach": i % 5 == 0, "realized_pnl_usd": 0.0, "unrealized_pnl_usd": net_pnl,
            "funding_paid_usd": 0.0, "fees_usd": 0.0, "net_pnl_usd": net_pnl,
        })
    return pd.DataFrame.from_records(rows)


def test_running_metrics_matches_batch_summarize_at_every_bar():
    # _RunningMetrics exists purely as a fast O(1)-per-bar substitute for
    # calling summarize() on a growing slice every frame (see run.py's
    # docstring on why that's O(n^2) and too slow for a real recording) --
    # if it ever disagrees with the batch calculation, the dashboard is
    # silently showing wrong running stats during replay.
    history = _synthetic_history(50)
    tracker = _RunningMetrics(bar_seconds=1.0)
    prev_inventory = 0.0

    for i, row in enumerate(history.itertuples(index=False)):
        tracker.update(row.net_pnl_usd, row.inventory - prev_inventory, bool(row.breach))
        prev_inventory = row.inventory

        expected = summarize(history.iloc[:i + 1], bar_seconds=1.0)
        got = tracker.snapshot(i + 1)

        assert got.net_pnl_usd == pytest.approx(expected.net_pnl_usd)
        assert got.max_drawdown_usd == pytest.approx(expected.max_drawdown_usd)
        assert got.turnover == pytest.approx(expected.turnover)
        assert got.breach_rate == pytest.approx(expected.breach_rate)
        assert got.n_bars == expected.n_bars
        if i >= 1:  # sharpe needs >= 2 points; both sides handle < 2 the same way (0.0)
            assert got.sharpe == pytest.approx(expected.sharpe, rel=1e-6)


def test_backtest_dashboard_renders_without_error():
    history = _synthetic_history(5)
    info = BacktestRunInfo(source="test.jsonl", symbol="BTC-PERPETUAL", engine="l2", params={"gamma": 20.0}, n_bars_total=5)
    dashboard = BacktestDashboard()
    tracker = _RunningMetrics(bar_seconds=1.0)

    row = next(history.itertuples(index=False))
    tracker.update(row.net_pnl_usd, 0.0, bool(row.breach))
    group = dashboard.render(info, 1, row, tracker.snapshot(1), [])
    assert group is not None
