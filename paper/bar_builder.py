from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LiveBarAggregator:
    """
    Buckets irregularly-arriving ticks into fixed-width, evenly-spaced bars
    (last price per bucket, forward-filled through empty buckets) -- what
    core.models.volatility.ewma_volatility actually requires (it assumes
    evenly-sampled input and scales annualisation by a fixed sampling_seconds).
    Feeding raw tick-by-tick updates into it directly, as paper/engine.py
    used to, silently distorts the vol estimate whenever ticks don't arrive
    exactly every sampling_seconds -- which live L2 updates never do.

    Same fixed-interval-bar approach core.backtest.historical.build_bars()
    uses for historical replay, just computed incrementally instead of
    vectorised over a whole trade tape (there's no "whole tape" yet live).
    """
    bar_seconds: float
    closes: list[float] = field(default_factory=list, init=False)
    _current_bar_start: float | None = field(default=None, init=False)
    _current_close: float | None = field(default=None, init=False)

    def update(self, timestamp_seconds: float, price: float) -> None:
        if self._current_bar_start is None:
            self._current_bar_start = self._bar_start(timestamp_seconds)
            self._current_close = price
            return

        bar_start = self._bar_start(timestamp_seconds)
        if bar_start == self._current_bar_start:
            self._current_close = price
            return

        # Close out the current bar and any empty bars in between (forward-fill).
        n_bars_elapsed = round((bar_start - self._current_bar_start) / self.bar_seconds)
        self.closes.extend([self._current_close] * n_bars_elapsed)
        self._current_bar_start = bar_start
        self._current_close = price

    def _bar_start(self, timestamp_seconds: float) -> float:
        return (timestamp_seconds // self.bar_seconds) * self.bar_seconds

    def closed_series(self, include_current: bool = True) -> list[float]:
        if include_current and self._current_close is not None:
            return self.closes + [self._current_close]
        return list(self.closes)
