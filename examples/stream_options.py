"""
Live options chain printer.

Subscribes to the markprice.options.{index} channel and streams mark prices and
implied volatility for all listed options. Displays a calls-and-puts side-by-side
table filtered to the nearest strikes around the current index price.

Controls
--------
N_EXPIRIES  — number of nearest expiries to display (default 2)
N_STRIKES   — strikes per side of ATM; auto-scales to terminal height (default 5)

Usage:
    python -m examples.stream_options              # BTC
    python -m examples.stream_options eth          # ETH
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

from deribit import DeribitConnector, DeribitREST
from deribit.types import OptionMarkPrice

N_EXPIRIES = 2   # nearest expiries to show
N_STRIKES  = 5   # strikes per side of ATM

# Scale N_STRIKES to fill the available terminal height
try:
    _term_rows = os.get_terminal_size().lines
    _budget = _term_rows - 6  # subtract header + footer rows
    _strikes_budget = _budget // N_EXPIRIES - 2  # 2 header rows per expiry block
    if _strikes_budget > 2:
        N_STRIKES = _strikes_budget // 2
except OSError:
    pass

_CLEAR = "\033[H\033[J"
_DIM   = "\033[2m"
_RESET = "\033[0m"
_CYAN  = "\033[36m"
_YELLOW = "\033[33m"
_BOLD  = "\033[1m"
_RED   = "\033[31m"
_GREEN = "\033[32m"

# Column widths
_WIV = 7   # IV column  (e.g. " 89.1%")
_WMK = 9   # mark column (e.g. "0.008100")
_WST = 9   # strike column (e.g. " 100,000")
_W = 2 + _WIV + 1 + _WMK + 2 + _WST + 2 + _WMK + 1 + _WIV + 2  # ≈ 46 chars


def _parse_name(name: str) -> tuple[str, int, str]:
    """Return (expiry, strike_int, option_type) from instrument name."""
    parts = name.split("-")
    if len(parts) < 4:
        return "", 0, ""
    return parts[1], int(parts[2]), parts[3]  # e.g. '26DEC25', 75000, 'C'


def _expiry_sort_key(expiry: str) -> int:
    """Convert expiry string to a sortable integer (YYYYMMDD)."""
    months = {
        "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
        "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
        "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
    }
    # e.g. '26DEC25' → day=26, mon='DEC', yr=25
    try:
        day = expiry[:2]
        mon = months.get(expiry[2:5], "00")
        yr  = "20" + expiry[5:]
        return int(f"{yr}{mon}{day}")
    except (ValueError, KeyError):
        return 0


def _hr(width: int = _W) -> str:
    return f"{_DIM}  {'─' * width}{_RESET}"


def render(
    prices: list[OptionMarkPrice],
    currency: str,
    index_price: float,
    update_count: int,
) -> None:
    # ── build lookup: expiry → strike → {C: OptionMarkPrice, P: OptionMarkPrice}
    chain: dict[str, dict[int, dict[str, OptionMarkPrice]]] = {}
    for p in prices:
        expiry, strike, otype = _parse_name(p["instrument_name"])
        if not expiry or not otype:
            continue
        chain.setdefault(expiry, {}).setdefault(strike, {})[otype] = p

    # ── pick nearest expiries
    expiries = sorted(chain, key=_expiry_sort_key)[:N_EXPIRIES]

    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    W = _W
    lines: list[str] = []

    # ── header
    lines.append(_hr(W))
    hdr = f"  {_BOLD}{_CYAN}{currency}_USD{_RESET}  idx {index_price:>12,.2f}  │  {len(prices):>4} options  │  {now}"
    lines.append(hdr)
    lines.append(_hr(W))

    col_hdr = (
        f"  {_DIM}{'IV%':>{_WIV}} {'CALL':>{_WMK}}  {'STRIKE':>{_WST}}  {'PUT':>{_WMK}} {'IV%':>{_WIV}}{_RESET}"
    )

    for expiry in expiries:
        strikes_map = chain[expiry]
        all_strikes = sorted(strikes_map.keys(), reverse=True)

        # find ATM: strike closest to index_price
        atm = min(all_strikes, key=lambda s: abs(s - index_price))
        atm_idx = all_strikes.index(atm)

        # Fixed-size window: always 2·N_STRIKES + 1 rows, centred on ATM.
        # Slots that fall outside the available strikes are left blank so the
        # table height never changes as the index moves between updates.
        n_rows = 2 * N_STRIKES + 1
        slots: list[int | None] = [None] * n_rows
        for slot_i in range(n_rows):
            s_idx = atm_idx - N_STRIKES + slot_i
            if 0 <= s_idx < len(all_strikes):
                slots[slot_i] = all_strikes[s_idx]

        lines.append(
            f"  {_YELLOW}── {expiry} {'─' * (W - len(expiry) - 5)}{_RESET}"
        )
        lines.append(col_hdr)

        blank_cell = " " * (_WIV + 1 + _WMK)
        for slot_i, strike in enumerate(slots):
            if strike is None:
                lines.append(f"  {blank_cell}  {' ' * (_WST + 2)}  {blank_cell}")
                continue

            sides = strikes_map.get(strike, {})
            c = sides.get("C")
            p = sides.get("P")

            c_iv   = f"{c['mark_iv']:>{_WIV}.1f}%" if c else " " * (_WIV + 1)
            c_mark = f"{c['mark_price']:>{_WMK}.5f}" if c else " " * _WMK
            p_iv   = f"{p['mark_iv']:>{_WIV}.1f}%" if p else " " * (_WIV + 1)
            p_mark = f"{p['mark_price']:>{_WMK}.5f}" if p else " " * _WMK

            strike_str = f"{strike:>{_WST},}"
            if strike == atm:
                strike_fmt = f"{_BOLD}▶{strike_str}◀{_RESET}"
            else:
                strike_fmt = f" {strike_str} "

            lines.append(
                f"  {_GREEN}{c_iv} {c_mark}{_RESET}  {strike_fmt}  "
                f"{_RED}{p_mark} {p_iv}{_RESET}"
            )

    lines.append(_hr(W))

    sys.stdout.write(_CLEAR + "\n".join(lines) + "\n")
    sys.stdout.flush()


RENDER_HZ = 1.0   # maximum renders per second; set higher for faster refresh


async def main() -> None:
    currency   = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC"
    index_name = f"{currency.lower()}_usd"

    # Public market data always reads from mainnet.
    rest      = DeribitREST(testnet=False)
    connector = DeribitConnector(testnet=False)

    idx = await rest.get_index_price(index_name)
    state = {"index_price": idx["price"], "update_count": 0}

    async def track_index() -> None:
        async for tick in connector.watch_index(index_name):
            state["index_price"] = tick["price"]

    async def stream_marks() -> None:
        min_interval = 1.0 / RENDER_HZ
        last = 0.0
        async for prices in connector.watch_mark_prices(index_name):
            state["update_count"] += 1
            now = time.monotonic()
            if now - last >= min_interval:
                render(prices, currency, state["index_price"], state["update_count"])
                last = now

    try:
        await asyncio.gather(track_index(), stream_marks())
    finally:
        await rest.close()


if __name__ == "__main__":
    asyncio.run(main())
