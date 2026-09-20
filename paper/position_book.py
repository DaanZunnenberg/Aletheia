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
    options-specific belongs in this class). No funding accrual here yet
    (perp funding rate isn't wired into this paper engine).
    """
    positions: dict[str, Position] = field(default_factory=dict)
    fill_log: list[tuple[float, str, PaperFill]] = field(default_factory=list)

    def position_for(self, instrument: str) -> Position:
        if instrument not in self.positions:
            self.positions[instrument] = Position()
        return self.positions[instrument]

    def apply_fill(self, instrument: str, timestamp: float, fill: PaperFill) -> None:
        position = self.position_for(instrument)
        signed_qty = fill.size if fill.side == "bid" else -fill.size
        position.apply_fill(signed_qty, fill.price)
        self.fill_log.append((timestamp, instrument, fill))

    def unrealized_pnl(self, instrument: str, mark_price: float) -> float:
        return self.position_for(instrument).unrealized_pnl_usd(mark_price)

    def net_pnl(self, instrument: str, mark_price: float) -> float:
        return self.position_for(instrument).net_pnl_usd(mark_price)

    def total_net_pnl(self, mark_prices: dict[str, float]) -> float:
        return sum(
            self.position_for(instrument).net_pnl_usd(mark_prices.get(instrument, 0.0))
            for instrument in self.positions
        )
