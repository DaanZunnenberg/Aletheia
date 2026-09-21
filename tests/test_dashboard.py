from __future__ import annotations

from rich.console import Console

from core.models.regime_monitor import RegimeState
from paper.dashboard import (
    InstrumentSnapshot,
    MarketDashboard,
    RiskSnapshot,
    render_dashboard,
    spread_bps,
    utilization,
    utilization_tier,
)


def _snap(**overrides) -> InstrumentSnapshot:
    defaults = dict(
        instrument="BTC-PERPETUAL", exchange="deribit", kind="perp-quoted",
        mid=81_000.0, our_bid=80_999.0, our_ask=81_002.0,
        position_qty=0.05, unrealized_pnl=1.23, pnl_ccy="USD", n_fills=3,
    )
    defaults.update(overrides)
    return InstrumentSnapshot(**defaults)


def test_render_includes_every_instrument_name():
    output = render_dashboard([_snap(instrument="BTC-PERPETUAL"), _snap(instrument="ETH-PERPETUAL")], 10.0, 5)
    assert "BTC-PERPETUAL" in output
    assert "ETH-PERPETUAL" in output


def test_render_shows_dashes_for_unquoted_reference_rows():
    output = render_dashboard([_snap(our_bid=None, our_ask=None, kind="reference")], 10.0, 0)
    lines = [l for l in output.splitlines() if "BTC-PERPETUAL" in l]
    assert len(lines) == 1
    assert "--" in lines[0]


def test_render_does_not_use_scientific_notation_for_large_prices():
    output = render_dashboard([_snap(mid=81_234.5)], 1.0, 0)
    assert "e+" not in output.lower()


def test_render_shows_coin_denominated_pnl_for_options():
    output = render_dashboard([_snap(kind="option-quoted", unrealized_pnl=-0.0002, pnl_ccy="BTC")], 1.0, 0)
    assert "BTC" in output


def test_render_includes_elapsed_time_and_fill_count():
    output = render_dashboard([_snap()], 123.4, 7)
    assert "123.4" in output
    assert "7" in output


def test_render_omits_greeks_section_when_not_provided():
    output = render_dashboard([_snap()], 1.0, 0)
    assert "PORTFOLIO GREEKS" not in output


def test_render_includes_greeks_section_when_provided():
    from core.models.greeks_aggregator import PortfolioGreeks

    output = render_dashboard([_snap()], 1.0, 0, portfolio_greeks={"BTC": PortfolioGreeks(delta=0.5, gamma=0.01)})
    assert "PORTFOLIO GREEKS" in output
    assert "BTC" in output


def test_render_includes_hard_hedge_count():
    output = render_dashboard([_snap()], 1.0, 0, n_hard_hedges=3)
    assert "hard hedges: 3" in output


def _rendered_text(renderable) -> str:
    console = Console(width=200, record=True, force_terminal=True)
    console.print(renderable)
    return console.export_text()


def test_spread_bps_none_when_missing_a_side():
    assert spread_bps(None, 100.0, 100.0) is None
    assert spread_bps(99.0, None, 100.0) is None


def test_spread_bps_computes_relative_to_mid():
    assert spread_bps(99.0, 101.0, 100.0) == 200.0


def test_market_dashboard_render_includes_instrument_and_ladder_levels():
    dashboard = MarketDashboard()
    snap = _snap(bid_levels=((80_999.0, 0.1), (80_995.0, 0.05)), ask_levels=((81_002.0, 0.1), (81_006.0, 0.05)))
    text = _rendered_text(dashboard.render([snap], 10.0, 5))
    assert "BTC-PERPETUAL" in text
    assert "80,995.00" in text  # second ladder level rendered as its own row


def test_market_dashboard_flags_changed_cell_on_second_render():
    dashboard = MarketDashboard()
    dashboard.render([_snap(our_bid=100.0)], 1.0, 0)
    group = dashboard.render([_snap(our_bid=200.0)], 2.0, 0)
    market_table = group.renderables[1]
    bid_cell = market_table.columns[8]._cells[0]
    assert bid_cell.style == "bold black on yellow"


def test_market_dashboard_does_not_flag_unchanged_cell():
    dashboard = MarketDashboard()
    dashboard.render([_snap(our_bid=100.0)], 1.0, 0)
    group = dashboard.render([_snap(our_bid=100.0)], 2.0, 0)
    market_table = group.renderables[1]
    bid_cell = market_table.columns[8]._cells[0]
    assert bid_cell.style == "green"


def test_market_dashboard_renders_regime_table():
    dashboard = MarketDashboard()
    regimes = {"BTC": RegimeState(vol_regime="VOLATILE", trend_regime="BULL", sigma_fast=0.9, sigma_slow=0.5, drift=0.2)}
    text = _rendered_text(dashboard.render([_snap()], 1.0, 0, regimes=regimes))
    assert "VOLATILE" in text
    assert "BULL" in text


def test_market_dashboard_renders_warmup_panel_only_when_not_ready():
    dashboard = MarketDashboard()
    text = _rendered_text(dashboard.render([_snap()], 1.0, 0, warmup_statuses={"BTC": ("fast_vol", 5, 20, 15.0)}))
    assert "Warming Up" in text

    text_ready = _rendered_text(dashboard.render([_snap()], 1.0, 0, warmup_statuses={"BTC": ("ready", 300, 300, 0.0)}))
    assert "Warming Up" not in text_ready


def test_market_dashboard_renders_recent_fills():
    dashboard = MarketDashboard()
    text = _rendered_text(dashboard.render([_snap()], 1.0, 1, recent_fills=[(1.0, "BTC-PERPETUAL", "bid", 81_000.0, 0.01)]))
    assert "Recent Fills" in text
    assert "BID" in text


def test_utilization_zero_limit_is_zero_not_a_crash():
    assert utilization(0.5, 0.0) == 0.0


def test_utilization_tier_breach_at_or_above_limit():
    assert utilization_tier(1.0) == "breach"
    assert utilization_tier(1.5) == "breach"


def test_utilization_tier_elevated_between_bands():
    assert utilization_tier(0.7) == "elevated"
    assert utilization_tier(0.99) == "elevated"


def test_utilization_tier_ok_below_elevated_band():
    assert utilization_tier(0.1) == "ok"


def _risk(**overrides) -> RiskSnapshot:
    defaults = dict(
        position=0.1, max_position=1.0, gross_notional_usd=1_000.0, max_gross_notional_usd=50_000.0,
        daily_loss_usd=0.0, max_daily_loss_usd=2_000.0, portfolio_delta=0.05, max_abs_delta=0.5,
    )
    defaults.update(overrides)
    return RiskSnapshot(**defaults)


def test_market_dashboard_renders_risk_table():
    dashboard = MarketDashboard()
    text = _rendered_text(dashboard.render([_snap()], 1.0, 0, risk_snapshots={"BTC": _risk()}))
    assert "Risk" in text
    assert "BTC" in text


def test_market_dashboard_flags_risk_breach_in_red():
    dashboard = MarketDashboard()
    group = dashboard.render([_snap()], 1.0, 0, risk_snapshots={"BTC": _risk(position=1.2, max_position=1.0)})
    risk_table = next(r for r in group.renderables if getattr(r, "title", None) == "Risk")
    position_cell = risk_table.columns[1]._cells[0]
    assert position_cell.style == "bold white on red"
