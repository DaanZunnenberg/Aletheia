from __future__ import annotations

from dataclasses import dataclass, field

from core.risk.exposure import Position
from paper.fill_simulator import PaperFill


@dataclass
class PositionBook:
    """
    Per-instrument Position tracking (core.risk.exposure.Position is generic
    contract math -- quantity/avg-price/realized-P&L -- so it applies
    identically whether the instrument is a perp or an option; nothing
    options-specific belongs in this class).

    Beyond the raw Position, this tracks what the dashboard needs for a firm
    P&L/position picture that isn't recoverable from Position alone:
    maker/taker fill attribution (was the fee/slippage profile what the
    strategy intended?), and how long the current directional stance has
    been held (stale inventory is a different risk than fresh inventory,
    even at the same net quantity).
    """
    positions: dict[str, Position] = field(default_factory=dict)
    fill_log: list[tuple[float, str, PaperFill]] = field(default_factory=list)
    maker_fill_count: dict[str, int] = field(default_factory=dict)
    taker_fill_count: dict[str, int] = field(default_factory=dict)
    maker_notional_usd: dict[str, float] = field(default_factory=dict)
    taker_notional_usd: dict[str, float] = field(default_factory=dict)
    # timestamp the current directional stance (sign of quantity) began --
    # None while flat. Reset whenever quantity crosses through zero or flips sign.
    position_since: dict[str, float | None] = field(default_factory=dict)

    def position_for(self, instrument: str) -> Position:
        if instrument not in self.positions:
            self.positions[instrument] = Position()
        return self.positions[instrument]

    def apply_fill(self, instrument: str, timestamp: float, fill: PaperFill) -> None:
        position = self.position_for(instrument)
        qty_before = position.quantity
        signed_qty = fill.size if fill.side == "bid" else -fill.size
        position.apply_fill(signed_qty, fill.price)
        self.fill_log.append((timestamp, instrument, fill))

        sign_before = (qty_before > 0.0) - (qty_before < 0.0)
        sign_after = (position.quantity > 0.0) - (position.quantity < 0.0)
        if sign_after == 0:
            self.position_since[instrument] = None
        elif sign_before != sign_after:
            self.position_since[instrument] = timestamp

        notional = fill.price * fill.size
        if fill.liquidity == "maker":
            self.maker_fill_count[instrument] = self.maker_fill_count.get(instrument, 0) + 1
            self.maker_notional_usd[instrument] = self.maker_notional_usd.get(instrument, 0.0) + notional
        else:
            self.taker_fill_count[instrument] = self.taker_fill_count.get(instrument, 0) + 1
            self.taker_notional_usd[instrument] = self.taker_notional_usd.get(instrument, 0.0) + notional

    def accrue_funding(self, instrument: str, funding_payment_usd: float) -> None:
        """funding_payment_usd > 0 is a cost (we pay), < 0 is a credit (we receive)."""
        self.position_for(instrument).apply_funding(funding_payment_usd)

    def position_age_seconds(self, instrument: str, now: float) -> float | None:
        since = self.position_since.get(instrument)
        return None if since is None else max(now - since, 0.0)

    def unrealized_pnl(self, instrument: str, mark_price: float) -> float:
        return self.position_for(instrument).unrealized_pnl_usd(mark_price)

    def net_pnl(self, instrument: str, mark_price: float) -> float:
        return self.position_for(instrument).net_pnl_usd(mark_price)

    def total_net_pnl(self, mark_prices: dict[str, float]) -> float:
        return sum(
            self.position_for(instrument).net_pnl_usd(mark_prices.get(instrument, 0.0))
            for instrument in self.positions
        )
