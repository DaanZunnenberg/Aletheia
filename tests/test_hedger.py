from __future__ import annotations

import pytest

from core.models.greeks_aggregator import PortfolioGreeks
from paper.hedger import HardHedgeLimits, portfolio_delta_excluding, should_hard_hedge, soft_hedge_inventory


def test_soft_hedge_inventory_sums_perp_and_option_delta():
    assert soft_hedge_inventory(perp_position_quantity=0.2, portfolio_delta_excluding_perp=0.3) == pytest.approx(0.5)


def test_soft_hedge_inventory_with_zero_option_delta_equals_perp_only():
    assert soft_hedge_inventory(0.2, 0.0) == pytest.approx(0.2)


def test_should_hard_hedge_stays_quiet_within_the_band():
    should, qty = should_hard_hedge(portfolio_delta=0.3, limits=HardHedgeLimits(max_abs_delta=0.5))
    assert not should
    assert qty == 0.0


def test_should_hard_hedge_fires_when_delta_breaches_the_band():
    should, qty = should_hard_hedge(portfolio_delta=0.8, limits=HardHedgeLimits(max_abs_delta=0.5))
    assert should
    assert qty == pytest.approx(-0.8)


def test_should_hard_hedge_fires_symmetrically_for_negative_delta():
    should, qty = should_hard_hedge(portfolio_delta=-0.8, limits=HardHedgeLimits(max_abs_delta=0.5))
    assert should
    assert qty == pytest.approx(0.8)


def test_hard_hedge_quantity_flattens_delta_exactly_to_zero():
    portfolio_delta = 1.2
    should, qty = should_hard_hedge(portfolio_delta=portfolio_delta, limits=HardHedgeLimits(max_abs_delta=0.5))
    assert portfolio_delta + qty == pytest.approx(0.0)


def test_boundary_delta_exactly_at_limit_does_not_fire():
    should, qty = should_hard_hedge(portfolio_delta=0.5, limits=HardHedgeLimits(max_abs_delta=0.5))
    assert not should


def test_portfolio_delta_excluding_sums_all_but_the_excluded_index():
    components = [PortfolioGreeks(delta=0.2), PortfolioGreeks(delta=0.5), PortfolioGreeks(delta=-0.1)]
    assert portfolio_delta_excluding(components, exclude_index=0) == pytest.approx(0.4)
    assert portfolio_delta_excluding(components, exclude_index=1) == pytest.approx(0.1)


def test_portfolio_delta_excluding_single_component_list():
    components = [PortfolioGreeks(delta=0.7)]
    assert portfolio_delta_excluding(components, exclude_index=0) == 0.0
