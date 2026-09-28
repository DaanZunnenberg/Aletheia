from __future__ import annotations

from dataclasses import dataclass

import pytest

from ccxt_stream.connector import CCXTOrderBookConnector
from ccxt_stream.select_option import select_near_1dte_option
from ccxt_stream.trades import CCXTTradeStreamConnector


def test_requested_depth_rounds_up_to_a_valid_ccxt_depth():
    # 25 isn't a valid Binance futures depth limit (confirmed live: ccxt
    # raises "25 is not valid depth limit") -- the connector must request a
    # supported depth (50) and truncate down to the caller's 25 itself,
    # never request 25 directly.
    connector = CCXTOrderBookConnector("binanceusdm", "perpetual", depth=25)
    assert connector._request_depth == 50


def test_requested_depth_passes_through_when_already_valid():
    connector = CCXTOrderBookConnector("binanceusdm", "perpetual", depth=20)
    assert connector._request_depth == 20


@dataclass
class _FakeMarket:
    option: bool
    base: str
    optionType: str
    expiry: float
    strike: float
    symbol: str
    settle: str = None

    def __post_init__(self) -> None:
        if self.settle is None:
            self.settle = self.base

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


class _FakeDeribit:
    id = "deribit"

    def __init__(self, markets: dict[str, _FakeMarket]) -> None:
        self._markets = markets

    def load_markets(self):
        return self._markets


def test_select_near_1dte_option_prefers_expiry_closest_to_target_not_the_soonest():
    import time
    now_ms = time.time() * 1000.0
    hour = 3600_000.0
    markets = {
        "soon": _FakeMarket(True, "BTC", "call", now_ms + 2 * hour, 80_000.0, "BTC-soon-C"),
        "near_1dte": _FakeMarket(True, "BTC", "call", now_ms + 23 * hour, 80_000.0, "BTC-1dte-C"),
        "far": _FakeMarket(True, "BTC", "call", now_ms + 200 * hour, 80_000.0, "BTC-far-C"),
    }
    selected = select_near_1dte_option(_FakeDeribit(markets), "BTC", spot_price=80_000.0)
    assert selected.symbol == "BTC-1dte-C"


def test_select_near_1dte_option_picks_nearest_strike_at_the_chosen_expiry():
    import time
    now_ms = time.time() * 1000.0
    hour = 3600_000.0
    markets = {
        "otm_high": _FakeMarket(True, "BTC", "call", now_ms + 24 * hour, 90_000.0, "BTC-90k-C"),
        "atm": _FakeMarket(True, "BTC", "call", now_ms + 24 * hour, 80_500.0, "BTC-80.5k-C"),
        "otm_low": _FakeMarket(True, "BTC", "call", now_ms + 24 * hour, 70_000.0, "BTC-70k-C"),
    }
    selected = select_near_1dte_option(_FakeDeribit(markets), "BTC", spot_price=80_000.0)
    assert selected.symbol == "BTC-80.5k-C"


def test_select_near_1dte_option_raises_when_no_live_options_exist():
    with pytest.raises(ValueError):
        select_near_1dte_option(_FakeDeribit({}), "BTC", spot_price=80_000.0)


def test_select_near_1dte_option_ignores_usdc_settled_markets():
    # Deribit lists both coin-settled (settle=="BTC") and USDC-settled
    # options on the same strike/expiry -- picking up both would double
    # up "distinct" strikes with near-duplicate instruments. Only the
    # coin-settled market matches this project's inverse-option convention
    # (paper/option_quoting.py divides the Black-76 USD price by spot).
    import time
    now_ms = time.time() * 1000.0
    hour = 3600_000.0
    markets = {
        "usdc": _FakeMarket(True, "BTC", "call", now_ms + 24 * hour, 80_000.0, "BTC-80k-C-USDC", settle="USDC"),
        "coin": _FakeMarket(True, "BTC", "call", now_ms + 24 * hour, 80_000.0, "BTC-80k-C", settle="BTC"),
    }
    selected = select_near_1dte_option(_FakeDeribit(markets), "BTC", spot_price=80_000.0)
    assert selected.symbol == "BTC-80k-C"


def test_select_strikes_near_expiry_returns_n_nearest_sorted_by_moneyness():
    import time

    from ccxt_stream.select_option import select_strikes_near_expiry

    now_ms = time.time() * 1000.0
    hour = 3600_000.0
    markets = {
        f"k{k}": _FakeMarket(True, "BTC", "call", now_ms + 24 * hour, k, f"BTC-{k}-C")
        for k in (70_000.0, 78_000.0, 80_000.0, 82_000.0, 90_000.0)
    }
    selected = select_strikes_near_expiry(_FakeDeribit(markets), "BTC", spot_price=80_000.0, n_strikes=3)
    assert [o.strike for o in selected] == [80_000.0, 78_000.0, 82_000.0]


class _FakeCcxtProExchange:
    """Fake ccxt.pro exchange: one watch_trades_for_symbols call, then raises to end the stream cleanly in a test."""

    def __init__(self, batches: list[list[dict]]) -> None:
        self._batches = list(batches)

    async def watch_trades_for_symbols(self, symbols):
        if not self._batches:
            raise StopAsyncIteration
        return self._batches.pop(0)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_stream_trades_drops_zero_price_or_amount_phantom_trades(monkeypatch):
    # Observed live on Binance USDT-M via ccxt.pro: occasional phantom
    # trades with price=0.0/amount=0.0, a real trade_id, no index/mark
    # price -- not a real fill, and left unfiltered it corrupts every
    # downstream consumer (log(price) in vol/bar building) with a zero/NaN
    # cascade. See ccxt_stream/record.py's real recordings for the origin.
    real_trade = {"symbol": "BTC/USDT:USDT", "price": 90_000.0, "amount": 1.5, "side": "buy", "timestamp": 1_700_000_000_000, "id": "1"}
    phantom_price = {"symbol": "BTC/USDT:USDT", "price": 0.0, "amount": 0.0, "side": "buy", "timestamp": 1_700_000_000_001, "id": "2"}
    phantom_amount = {"symbol": "BTC/USDT:USDT", "price": 90_001.0, "amount": 0.0, "side": "sell", "timestamp": 1_700_000_000_002, "id": "3"}

    connector = CCXTTradeStreamConnector("binanceusdm")
    connector._exchange = _FakeCcxtProExchange([[real_trade, phantom_price, phantom_amount]])

    trades = []
    async for trade in connector.stream_trades(["BTC/USDT:USDT"]):
        trades.append(trade)
        if len(trades) >= 1:
            break

    assert len(trades) == 1
    assert trades[0]["trade_id"] == "1"
