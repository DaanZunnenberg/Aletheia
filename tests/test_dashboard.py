from __future__ import annotations

from rich.console import Console
from rich.table import Table

from core.models.greeks_aggregator import PortfolioGreeks
from core.models.regime_monitor import RegimeState
from paper.dashboard import (
    BlotterRow,
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


def _risk(**overrides) -> RiskSnapshot:
    defaults = dict(
        position=0.1, max_position=1.0, gross_notional_usd=1_000.0, max_gross_notional_usd=50_000.0,
        daily_loss_usd=0.0, max_daily_loss_usd=2_000.0, portfolio_delta=0.05, max_abs_delta=0.5,
    )
    defaults.update(overrides)
    return RiskSnapshot(**defaults)


def _row(**overrides) -> BlotterRow:
    defaults = dict(timestamp=1.0, instrument="BTC-PERPETUAL", event_type="fill")
    defaults.update(overrides)
    return BlotterRow(**defaults)


def _rendered_text(renderable, width: int = 220) -> str:
    console = Console(width=width, record=True, force_terminal=True)
    console.print(renderable)
    return console.export_text()


# -- plain-text fallback renderer (render_dashboard) --------------------------------------

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
    output = render_dashboard([_snap()], 1.0, 0, portfolio_greeks={"BTC": PortfolioGreeks(delta=0.5, gamma=0.01)})
    assert "PORTFOLIO GREEKS" in output
    assert "BTC" in output


def test_render_includes_hard_hedge_count():
    output = render_dashboard([_snap()], 1.0, 0, n_hard_hedges=3)
    assert "hard hedges: 3" in output


# -- utilization helpers -------------------------------------------------------------------

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


def test_spread_bps_none_when_missing_a_side():
    assert spread_bps(None, 100.0, 100.0) is None
    assert spread_bps(99.0, None, 100.0) is None


def test_spread_bps_computes_relative_to_mid():
    assert spread_bps(99.0, 101.0, 100.0) == 200.0


# -- MarketDashboard (rich: BTC status header + BTC book table + BTC blotter) -----------------

def _renderables(group):
    return list(group.renderables)


def _book_tables(group):
    # Perp OB and Option OB sit side by side in a single-row Table.grid
    # (title=None distinguishes the grid from the two titled tables inside it).
    grid = next(r for r in _renderables(group) if isinstance(r, Table) and r.title is None)
    return [column._cells[0] for column in grid.columns]


def test_market_dashboard_renders_separate_perp_and_option_tables_plus_one_blotter_focused_on_btc():
    dashboard = MarketDashboard()
    group = dashboard.render(
        [_snap(instrument="BTC-PERPETUAL"), _snap(instrument="ETH-PERPETUAL")], 1.0, 0,
    )
    titled_tables = [r for r in _renderables(group) if isinstance(r, Table) and r.title is not None]
    assert [t.title for t in titled_tables] == ["BTC Blotter"]
    perp_table, option_table = _book_tables(group)
    assert perp_table.title == "BTC Perp OB"
    assert option_table.title == "BTC Option OB"


def test_market_dashboard_perp_and_option_are_separate_tables_each_with_only_their_own_instrument():
    dashboard = MarketDashboard()
    group = dashboard.render(
        [_snap(instrument="BTC-PERPETUAL", kind="perp-quoted"), _snap(instrument="BTC-21SEP26-80000-C", kind="option-quoted", pnl_ccy="BTC")],
        1.0, 0,
    )
    perp_table, option_table = _book_tables(group)
    assert perp_table.row_count == 1
    assert option_table.row_count == 1
    assert [c.header for c in perp_table.columns] == [
        "Instrument", "OurBid", "OurAsk", "BookBid", "BookAsk", "Spread",
        "Mid", "Position", "Fills", "uPnL",
    ]
    assert [c.header for c in option_table.columns] == [
        "Instrument", "OurBid", "OurAsk", "Mid", "Position", "Fills",
        "uPnL", "RVol", "IVol", "VRP", "Theo",
    ]


def test_market_dashboard_option_table_unaffected_by_perp_only_snapshot():
    """Each table reflects only its own instrument -- an option row never appears in the perp table or vice versa."""
    dashboard = MarketDashboard()
    group = dashboard.render([_snap(instrument="BTC-PERPETUAL", kind="perp-quoted")], 1.0, 0)
    perp_table, option_table = _book_tables(group)
    assert perp_table.row_count == 1
    assert option_table.row_count == 1  # placeholder "warming up" row, no option snapshot yet
    assert "BTC-PERPETUAL" not in [str(option_table.columns[0]._cells[0])]


def test_market_dashboard_option_table_shows_option_pricing_and_vrp_edge():
    dashboard = MarketDashboard()
    option_snap = _snap(
        instrument="BTC-21SEP26-80000-C", kind="option-quoted", pnl_ccy="BTC",
        realized_vol=0.5, fair_vol=0.6, theo_price=0.021, mid=0.02,
    )
    group = dashboard.render([option_snap], 1.0, 0)
    _, option_table = _book_tables(group)
    row_texts = [str(cell) for cell in [option_table.columns[c]._cells[0] for c in range(len(option_table.columns))]]
    assert "0.5000" in row_texts  # realized vol
    assert "0.6000" in row_texts  # fair (implied) vol
    assert "+0.1000" in row_texts  # VRP edge = fair - realized


def test_market_dashboard_blotter_only_includes_btc_events():
    dashboard = MarketDashboard()
    event_log = [
        _row(instrument="BTC-PERPETUAL", event_type="fill", side="bid", price=81_000.0, size=0.1),
        _row(instrument="ETH-PERPETUAL", event_type="fill", side="ask", price=3_000.0, size=1.0),
    ]
    group = dashboard.render([_snap()], 1.0, 2, event_log=event_log)
    blotter = next(t for t in _renderables(group) if isinstance(t, Table) and t.title == "BTC Blotter")
    assert blotter.row_count == 1


def test_market_dashboard_blotter_caps_to_recent_rows():
    dashboard = MarketDashboard()
    event_log = [_row(timestamp=float(i), note=f"tick {i}") for i in range(60)]
    text = _rendered_text(dashboard.render([_snap()], 1.0, 0, event_log=event_log))
    assert "tick 59" in text
    assert "tick 0" not in text  # older than the blotter window, scrolled off


def test_market_dashboard_blotter_colors_bid_green_and_ask_red():
    dashboard = MarketDashboard()
    event_log = [_row(event_type="fill", side="bid", price=81_000.0, size=0.1)]
    group = dashboard.render([_snap()], 1.0, 0, event_log=event_log)
    blotter = next(t for t in _renderables(group) if isinstance(t, Table) and t.title == "BTC Blotter")
    assert blotter.columns[3]._cells[0].style == "green"

    event_log_ask = [_row(event_type="fill", side="ask", price=81_000.0, size=0.1)]
    group_ask = dashboard.render([_snap()], 1.0, 0, event_log=event_log_ask)
    blotter_ask = next(t for t in _renderables(group_ask) if isinstance(t, Table) and t.title == "BTC Blotter")
    assert blotter_ask.columns[3]._cells[0].style == "red"


def test_market_dashboard_blotter_shows_book_and_quote_on_one_merged_row():
    dashboard = MarketDashboard()
    event_log = [_row(event_type="quote", book_bid=80_998.0, book_ask=81_003.0, our_bid=80_999.0, our_ask=81_002.0)]
    group = dashboard.render([_snap()], 1.0, 0, event_log=event_log)
    blotter = next(t for t in _renderables(group) if isinstance(t, Table) and t.title == "BTC Blotter")
    assert blotter.row_count == 1  # book + our quote in a single row, not two separate lines


def test_market_dashboard_header_uses_full_words_for_greeks_not_symbols():
    dashboard = MarketDashboard()
    text = _rendered_text(dashboard.render(
        [_snap()], 1.0, 0, portfolio_greeks={"BTC": PortfolioGreeks(delta=0.5, gamma=0.01, vega=1.2, theta=-0.3)},
        warmup_statuses={"BTC": ("ready", 300, 300, 0.0)},
    ))
    assert "Delta" in text and "Gamma" in text and "Vega" in text and "Theta" in text
    assert "Δ" not in text and "Γ" not in text


def test_market_dashboard_header_shows_warmup_and_regime():
    dashboard = MarketDashboard()
    regimes = {"BTC": RegimeState(vol_regime="VOLATILE", trend_regime="BULL", sigma_fast=0.9, sigma_slow=0.5, drift=0.2)}
    text = _rendered_text(dashboard.render(
        [_snap()], 1.0, 0, regimes=regimes, warmup_statuses={"BTC": ("fast_vol", 5, 20, 15.0)},
    ))
    assert "VOLATILE" in text
    assert "BULL" in text
    assert "warmup" in text


def test_market_dashboard_header_shows_ready_when_warmed_up():
    dashboard = MarketDashboard()
    text = _rendered_text(dashboard.render([_snap()], 1.0, 0, warmup_statuses={"BTC": ("ready", 300, 300, 0.0)}))
    assert "READY" in text


def test_market_dashboard_header_includes_a_dim_eth_reference_line():
    dashboard = MarketDashboard()
    regimes = {"BTC": RegimeState(vol_regime="CALM", trend_regime="EVEN", sigma_fast=0.1, sigma_slow=0.1, drift=0.0),
               "ETH": RegimeState(vol_regime="ACTIVE", trend_regime="BEAR", sigma_fast=0.2, sigma_slow=0.1, drift=-0.2)}
    text = _rendered_text(dashboard.render(
        [_snap()], 1.0, 0, regimes=regimes,
        warmup_statuses={"BTC": ("ready", 300, 300, 0.0), "ETH": ("ready", 300, 300, 0.0)},
    ))
    assert "ETH" in text
    assert "ACTIVE" in text
    assert "BEAR" in text


def test_market_dashboard_book_table_position_from_risk_snapshot_for_perp():
    dashboard = MarketDashboard()
    text = _rendered_text(dashboard.render(
        [_snap(n_fills=7)], 1.0, 0,
        risk_snapshots={"BTC": _risk(position=0.3, max_position=1.5)},
        warmup_statuses={"BTC": ("ready", 300, 300, 0.0)},
    ))
    assert "0.3000" in text
    assert "7" in text  # fill count


def test_market_dashboard_perp_table_pnl_colored_green_when_positive_red_when_negative():
    dashboard = MarketDashboard()
    positive = dashboard._render_perp_table("BTC", [_snap(unrealized_pnl=5.0)], {})
    negative = dashboard._render_perp_table("BTC", [_snap(unrealized_pnl=-5.0)], {})
    pnl_col = [c.header for c in positive.columns].index("uPnL")
    assert positive.columns[pnl_col]._cells[0].style == "green"
    assert negative.columns[pnl_col]._cells[0].style == "red"
