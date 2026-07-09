"""
Live order book printer — perpetual and spot side by side.

Connects to Deribit and streams two books concurrently:
  • BTC-PERPETUAL (or the configured symbol)
  • The matching spot instrument (BTC_USDC for BTC)

For perpetuals the header also shows mark/index price, open interest,
funding rate, and DVOL. Spread is displayed both absolutely and in basis points.

Usage:
    python -m examples.print_orderbook
"""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


import asyncio
import sys
from datetime import datetime, timezone
from typing import Optional

from config.settings import Settings
from data.feed import DeribitFeed
from data.orderbook import OrderBook
from deribit import DeribitConnector
from deribit.types import OrderBookSnapshot, Ticker, VolatilityIndex

LEVELS = 15   # book depth per side (reduced for side-by-side layout)

# ── column layout ─────────────────────────────────────────────────────────────
# Each book column: 2 indent + 12 price + 3 gap + 12 qty = 29 chars
# Separator: " │ " = 3 chars  → total = 61 chars
_CP = 12   # price col width
_CQ = 12   # qty col width
_LW = 2 + _CP + 3 + _CQ      # left column  (29)
_RW = _CP + 3 + _CQ           # right column (27)
W   = _LW + 3 + _RW           # total display width (59)

_RESET = "\033[0m"
_RED   = "\033[31m"
_GREEN = "\033[32m"
_CYAN  = "\033[36m"
_BOLD  = "\033[1m"
_DIM   = "\033[2m"
_CLEAR = "\033[H\033[J"


# ── helpers ───────────────────────────────────────────────────────────────────

def _hr() -> str:
    return f"{_DIM}  {'─' * W}{_RESET}"

def _fmt_f(v: Optional[float], fmt: str = ",.2f", fallback: str = "—") -> str:
    return format(v, fmt) if v is not None else fallback

def _fmt_pct(v: Optional[float], decimals: int = 4) -> str:
    return f"{v * 100:+.{decimals}f}%" if v is not None else "—"

def _fmt_oi(v: float) -> str:
    if v >= 1e9:
        return f"{v / 1e9:.3f}B"
    if v >= 1e6:
        return f"{v / 1e6:.3f}M"
    return f"{v:,.0f}"

def _fmt_qty(qty: float) -> str:
    """Integers as whole numbers, small decimals with 4dp."""
    if qty >= 1 and qty == int(qty):
        return f"{qty:>{_CQ},.0f}"
    return f"{qty:>{_CQ},.4f}"

def _book_stats(book: OrderBook) -> tuple[str, str, str]:
    """Three fixed-width stat strings that each fit within _LW-2 / _RW chars."""
    bps = (book.spread / book.mid) * 10_000 if book.mid else 0.0
    mid_s = f"mid {book.mid:>12,.2f}"
    spr_s = f"spr {book.spread:>8,.2f}   {bps:>6.2f} bp"
    imb_s = f"imb {book.imbalance:>+8.3f}"
    return mid_s, spr_s, imb_s


# ── render ────────────────────────────────────────────────────────────────────

def render(
    perp: OrderBook,
    spot: Optional[OrderBook],
    ticker: Optional[Ticker],
    dvol: Optional[VolatilityIndex],
    perp_symbol: str,
    spot_symbol: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    lines: list[str] = []

    # ── header (full width) ───────────────────────────────────────────────────
    lines.append(_hr())
    title = f"{_BOLD}  {perp_symbol}{_RESET}"
    pad = W - len(perp_symbol) - len(now)
    lines.append(f"{title}{' ' * pad}{_DIM}{now}{_RESET}")
    lines.append(_hr())

    if ticker is not None:
        mark  = _fmt_f(ticker.get("mark_price"),  ",.2f")
        idx   = _fmt_f(ticker.get("index_price"), ",.2f")
        last  = _fmt_f(ticker.get("last_price"),  ",.2f")
        oi    = _fmt_oi(ticker.get("open_interest") or 0.0)
        lines.append(f"  Mark {mark:>12}   Index {idx:>12}   Last {last:>12}")
        if ticker.get("current_funding") is not None:
            fund_c = _fmt_pct(ticker.get("current_funding"))
            fund_8 = _fmt_pct(ticker.get("funding_8h"))
            lines.append(f"  OI   {oi:>12}   Funding  {fund_c:>9}   8h {fund_8:>10}")
        else:
            lines.append(f"  OI   {oi:>12}")
        if ticker.get("mark_iv") is not None:
            mark_iv = _fmt_f(ticker.get("mark_iv"), ".2f")
            bid_iv  = _fmt_f(ticker.get("bid_iv"),  ".2f")
            ask_iv  = _fmt_f(ticker.get("ask_iv"),  ".2f")
            lines.append(f"  IV   mark {mark_iv:>6}%   bid {bid_iv:>6}%   ask {ask_iv:>6}%")
            delta = _fmt_f(ticker.get("delta"), ".4f")
            gamma = _fmt_f(ticker.get("gamma"), ".6f")
            vega  = _fmt_f(ticker.get("vega"),  ".4f")
            theta = _fmt_f(ticker.get("theta"), ".4f")
            lines.append(f"  Δ {delta:>9}   Γ {gamma:>10}   ν {vega:>9}   Θ {theta:>9}")
        if dvol is not None:
            lines.append(f"  DVOL {dvol['volatility']:>7.2f}%  (30-day forward IV)")
        lines.append(_hr())
    else:
        lines.append(f"  {_DIM}waiting for ticker…{_RESET}")
        lines.append(_hr())

    # ── column headers ────────────────────────────────────────────────────────
    spot_rdy = spot is not None and spot.ready
    l_hdr = f"{_BOLD}{perp_symbol}{_RESET}"
    r_hdr = f"{_BOLD}{spot_symbol}{_RESET}" if spot_rdy else f"{_DIM}{spot_symbol} — waiting…{_RESET}"
    lines.append(f"  {l_hdr}{' ' * (_LW - 2 - len(perp_symbol))} │ {r_hdr}")
    lines.append(_hr())

    # ── book stats — three rows, each fits within column width ────────────────
    pm, ps, pi = _book_stats(perp)
    if spot_rdy:
        sm, ss, si = _book_stats(spot)
    else:
        sm = ss = si = "—"
    lines.append(f"  {pm:<{_LW - 2}} │ {sm:<{_RW}}")
    lines.append(f"  {ps:<{_LW - 2}} │ {ss:<{_RW}}")
    lines.append(f"  {pi:<{_LW - 2}} │ {si:<{_RW}}")
    lines.append(_hr())

    # ── price/qty column headers ───────────────────────────────────────────────
    lines.append(
        f"  {_DIM}{'PRICE':>{_CP}}   {'SIZE':>{_CQ}}{_RESET}"
        f" │ "
        f"{_DIM}{'PRICE':>{_CP}}   {'SIZE':>{_CQ}}{_RESET}"
    )
    lines.append(_hr())

    # ── asks (reverse so lowest ask is nearest to mid) ────────────────────────
    perp_asks = perp.asks[:LEVELS]
    spot_asks = (spot.asks[:LEVELS] if spot_rdy else [])

    for i, (price, qty) in enumerate(reversed(perp_asks)):
        left = f"{_RED}  {price:>{_CP},.2f}   {_fmt_qty(qty)}{_RESET}"
        if i < len(spot_asks):
            sp, sq = list(reversed(spot_asks))[i]
            right = f"{_RED}{sp:>{_CP},.2f}   {_fmt_qty(sq)}{_RESET}"
        else:
            right = ""
        lines.append(f"{left} │ {right}")

    # ── mid line ──────────────────────────────────────────────────────────────
    perp_mid = f"── mid {perp.mid:,.2f} ──"
    spot_mid = f"── mid {spot.mid:,.2f} ──" if spot_rdy else "──"
    lines.append(
        f"  {_DIM}{perp_mid:>{_LW - 2}}{_RESET}"
        f" │ "
        f"{_DIM}{spot_mid:>{_RW}}{_RESET}"
    )

    # ── bids ──────────────────────────────────────────────────────────────────
    perp_bids = perp.bids[:LEVELS]
    spot_bids = (spot.bids[:LEVELS] if spot_rdy else [])

    for i, (price, qty) in enumerate(perp_bids):
        left = f"{_GREEN}  {price:>{_CP},.2f}   {_fmt_qty(qty)}{_RESET}"
        if i < len(spot_bids):
            sp, sq = spot_bids[i]
            right = f"{_GREEN}{sp:>{_CP},.2f}   {_fmt_qty(sq)}{_RESET}"
        else:
            right = ""
        lines.append(f"{left} │ {right}")

    lines.append(_hr())

    sys.stdout.write(_CLEAR + "\n".join(lines) + "\n")
    sys.stdout.flush()


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    settings    = Settings.load()
    perp_symbol = settings.symbol                          # e.g. BTC-PERPETUAL
    currency    = perp_symbol.split("-")[0]                # e.g. BTC
    spot_symbol = f"{currency}_USDC"                      # e.g. BTC_USDC
    dvol_ch     = f"{currency.lower()}_usd"               # e.g. btc_usd

    connector = DeribitConnector(testnet=False)
    perp_book = OrderBook()
    spot_book = OrderBook()
    feed      = DeribitFeed(connector)
    state: dict = {}

    def on_perp(snap: OrderBookSnapshot) -> None:
        perp_book.update(snap)
        if perp_book.ready:
            render(
                perp_book,
                spot_book if spot_book.ready else None,
                state.get("ticker"),
                state.get("dvol"),
                perp_symbol,
                spot_symbol,
            )

    async def run_spot() -> None:
        async for snap in connector.watch_order_book(spot_symbol, depth=LEVELS):
            spot_book.update(snap)

    def on_ticker(t: Ticker) -> None:
        state["ticker"] = t

    def on_dvol(d: VolatilityIndex) -> None:
        state["dvol"] = d

    feed.on_order_book(on_perp)
    feed.on_ticker(on_ticker)
    feed.on_volatility_index(on_dvol)

    depth = max(LEVELS, settings.ob_depth)
    await asyncio.gather(
        feed.run_order_book(perp_symbol, depth=depth),
        feed.run_ticker(perp_symbol),
        feed.run_volatility_index(dvol_ch),
        run_spot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
