from __future__ import annotations

from paper.dashboard import InstrumentSnapshot, render_dashboard


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
