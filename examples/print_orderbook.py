"""
Live order book printer — BTC, ETH, and SOL perpetual + spot side by side.

Connects to Deribit mainnet and streams six books concurrently:
  • BTC-PERPETUAL       │ basis │  BTC_USDC
  • ETH-PERPETUAL       │ basis │  ETH_USDC
  • SOL_USDC-PERPETUAL  │ basis │  SOL_USDC

The three currency pairs are shown side by side (~169 chars wide). For each
perpetual the header shows mark/index price, open interest, funding, and DVOL.
Spread is displayed in USD and basis points. The basis column shows
(perp price) − (spot price) at each level; green = contango, red = backwardation.

Usage:
    python -m examples.print_orderbook
"""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio
from datetime import datetime, timezone
from typing import Optional

from data.orderbook import OrderBook
from deribit import DeribitConnector
from deribit.types import Ticker, VolatilityIndex

LEVELS = 25

# ── compact column layout — three pairs side by side ──────────────────────────
# Left col:   2 indent + 10 price + 3 gap + 6 qty  = 21 chars
# Centre:     3 sep    +  7 basis + 3 sep           = 13 chars
# Right col:  10 price + 3 gap + 6 qty              = 19 chars
# One pair total                                     = 53 chars
# Three pairs + two "  ║  " separators (5 each)     = 169 chars
_CP    = 10   # price column width  ("100,000.00" = 10 chars)
_CQ    = 6    # qty column width    (large values abbreviated: 316K, 1.00M)
_CB    = 7    # basis column width  ("+999.99"    = 7 chars)
_LW    = 2 + _CP + 3 + _CQ   # left  column incl. 2-char indent = 21
_RW    = _CP + 3 + _CQ        # right column                     = 19
PAIR_W = _LW + 3 + _CB + 3 + _RW  # per-pair display width       = 53

PAIR_SEP = "  ║  "   # 5-char separator between the two pairs

PAIRS = [
    ("BTC-PERPETUAL", "BTC_USDC"),
    ("ETH-PERPETUAL", "ETH_USDC"),
    ("SOL_USDC-PERPETUAL", "SOL_USDC"),
]

_RESET = "\033[0m"
_RED   = "\033[31m"
_GREEN = "\033[32m"
_BOLD  = "\033[1m"
_DIM   = "\033[2m"
_CLEAR = "\033[H\033[J"


# ── formatting helpers ─────────────────────────────────────────────────────────

def _pair_hr() -> str:
    return f"{_DIM}{'─' * PAIR_W}{_RESET}"

def _fmt_pct(v: Optional[float], decimals: int = 4) -> str:
    return f"{v * 100:+.{decimals}f}%" if v is not None else "—"

def _fmt_oi(v: float) -> str:
    if v >= 1e9: return f"{v / 1e9:.3f}B"
    if v >= 1e6: return f"{v / 1e6:.3f}M"
    return f"{v:,.0f}"

def _fmt_qty(qty: float) -> str:
    W = _CQ  # 6 chars; large values are abbreviated so they always fit
    if qty >= 1e9:
        return f"{qty/1e9:>{W-1}.2f}B"
    if qty >= 1e6:
        v = qty / 1e6
        raw = f"{v:.2f}M" if v < 10 else f"{v:.1f}M"
        return f"{raw:>{W}}"
    if qty >= 1 and qty == int(qty):
        s = f"{qty:,.0f}"
        if len(s) <= W:
            return f"{s:>{W}}"
        k = qty / 1e3
        if round(k, 1) >= 1000:   # would print "1000.0K"; use M instead
            return f"{qty/1e6:>{W-1}.2f}M"
        return f"{k:>{W-1}.1f}K"
    for dp in (4, 3, 2, 1):
        s = f"{qty:,.{dp}f}"
        if len(s) <= W:
            return f"{s:>{W}}"
    return f"{qty/1e3:>{W-1}.1f}K" if qty >= 1e3 else f"{qty:>{W},.0f}"


def _currency(spot_sym: str) -> str:
    """Extract base currency label from spot symbol: 'BTC_USDC' → 'BTC'."""
    return spot_sym.replace("_USDC", "")

def _fmt_basis(val: float) -> str:
    color = _GREEN if val >= 0 else _RED
    return f"{color}{val:>+{_CB}.2f}{_RESET}"


# ── per-pair renderer ──────────────────────────────────────────────────────────

def _render_pair(
    perp: OrderBook,
    spot: Optional[OrderBook],
    ticker: Optional[Ticker],
    dvol: Optional[VolatilityIndex],
    perp_sym: str,
    spot_sym: str,
    show_time: bool = False,
) -> list[str]:
    """Return a list of strings each exactly PAIR_W visual characters wide."""
    lines: list[str] = []
    spot_rdy = spot is not None and spot.ready
    _B  = " " * _CB   # blank basis placeholder (7 spaces)
    col = _LW - 2      # stat content width = _RW = 22 chars

    # ── hr ────────────────────────────────────────────────────────────────────
    lines.append(_pair_hr())

    # ── instrument name (+ UTC clock on the right pair only) ──────────────────
    if show_time:
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        pad = PAIR_W - len(perp_sym) - len(now)
        lines.append(f"{_BOLD}{perp_sym}{_RESET}{' ' * pad}{_DIM}{now}{_RESET}")
    else:
        lines.append(f"{_BOLD}{perp_sym}{_RESET}{' ' * (PAIR_W - len(perp_sym))}")

    lines.append(_pair_hr())

    # ── ticker rows (always 3 rows; padded when absent) ────────────────────────
    if ticker is not None:
        mark = ticker.get("mark_price") or 0.0
        idx  = ticker.get("index_price") or 0.0
        last = ticker.get("last_price") or 0.0
        oi   = _fmt_oi(ticker.get("open_interest") or 0.0)
        row1 = f"  mk {mark:>{_CP},.2f}  ix {idx:>{_CP},.2f}  ls {last:>{_CP},.2f}"
        lines.append(f"{row1:<{PAIR_W}}")
        if ticker.get("current_funding") is not None:
            fc   = _fmt_pct(ticker["current_funding"])
            f8   = _fmt_pct(ticker["funding_8h"])
            row2 = f"  OI {oi:>8}  fund {fc:>9}  8h {f8:>9}"
        else:
            row2 = f"  OI {oi:>8}"
        lines.append(f"{row2:<{PAIR_W}}")
        row3 = f"  DVOL {dvol['volatility']:>6.2f}%  (30d forward IV)" if dvol else ""
        lines.append(f"{row3:<{PAIR_W}}")
    else:
        msg = "waiting for ticker…"   # unicode ellipsis = 1 char
        lines.append(f"  {_DIM}{msg}{_RESET}{' ' * (PAIR_W - 2 - len(msg))}")
        lines.append(" " * PAIR_W)
        lines.append(" " * PAIR_W)

    lines.append(_pair_hr())

    # ── column sub-headers: perp_sym │ BASIS │ spot_sym ───────────────────────
    basis_hdr = f"{'BASIS':^{_CB}}"
    l_pad  = col - len(perp_sym)
    r_name = spot_sym if spot_rdy else f"{spot_sym} …"
    subhdr = (
        f"  {_BOLD}{perp_sym}{_RESET}{' ' * l_pad}"
        f" │ {_DIM}{basis_hdr}{_RESET} │ "
        f"{_BOLD}{r_name}{_RESET}"
    )
    vis_len = 2 + len(perp_sym) + l_pad + 3 + _CB + 3 + len(r_name)
    lines.append(subhdr + " " * (PAIR_W - vis_len))

    lines.append(_pair_hr())

    # ── book stats (3 rows) ───────────────────────────────────────────────────
    if perp.ready:
        bps_p = (perp.spread / perp.mid) * 10_000
        pm = f"mid {perp.mid:>10,.2f}"
        ps = f"spr {perp.spread:>7,.2f} {bps_p:>5.2f}bp"
        pi = f"imb {perp.imbalance:>+7.3f}"
        mid_basis = _fmt_basis(perp.mid - spot.mid) if spot_rdy else _B
    else:
        pm = ps = pi = "—"   # em dash
        mid_basis = _B

    if spot_rdy:
        bps_s = (spot.spread / spot.mid) * 10_000
        sm = f"mid {spot.mid:>10,.2f}"
        ss = f"spr {spot.spread:>7,.2f} {bps_s:>5.2f}bp"
        si = f"imb {spot.imbalance:>+7.3f}"
    else:
        sm = ss = si = "—"

    lines.append(f"  {pm:<{col}} │ {mid_basis} │ {sm:<{_RW}}")
    lines.append(f"  {ps:<{col}} │ {_B} │ {ss:<{_RW}}")
    lines.append(f"  {pi:<{col}} │ {_B} │ {si:<{_RW}}")

    lines.append(_pair_hr())

    # ── PRICE / SIZE column headers ───────────────────────────────────────────
    ph = f"{'PRICE':>{_CP}}   {'SIZE':>{_CQ}}"   # 22 chars
    lines.append(
        f"  {_DIM}{ph}{_RESET} │ {_DIM}{'p - s':^{_CB}}{_RESET} │ {_DIM}{ph}{_RESET}"
    )
    lines.append(_pair_hr())

    # ── asks: highest first (top) → lowest (nearest mid, bottom) ─────────────
    perp_asks     = perp.asks[:LEVELS].tolist() if perp.ready else []
    spot_asks_rev = list(reversed(spot.asks[:LEVELS].tolist())) if spot_rdy else []

    for i in range(LEVELS):
        if i < len(perp_asks):
            price, qty = perp_asks[len(perp_asks) - 1 - i]  # reversed
            lc = f"  {price:>{_CP},.2f}   {_fmt_qty(qty)}"
            if i < len(spot_asks_rev):
                sp, sq = spot_asks_rev[i]
                rc = f"{sp:>{_CP},.2f}   {_fmt_qty(sq)}"
                b  = _fmt_basis(price - sp)
            else:
                rc = " " * _RW
                b  = _B
            lines.append(f"{_RED}{lc}{_RESET} │ {b} │ {_RED}{rc}{_RESET}")
        else:
            lines.append(f"{' ' * _LW} │ {_B} │ {' ' * _RW}")

    # ── mid line ──────────────────────────────────────────────────────────────
    pm_s = f"── mid {perp.mid:,.2f} ──" if perp.ready else "──"
    sm_s = f"── mid {spot.mid:,.2f} ──" if spot_rdy else "──"
    lines.append(
        f"  {_DIM}{pm_s:>{col}}{_RESET}"
        f" │ {mid_basis} │ "
        f"{_DIM}{sm_s:<{_RW}}{_RESET}"
    )

    # ── bids: best bid (nearest mid, top) → deeper ────────────────────────────
    perp_bids = perp.bids[:LEVELS].tolist() if perp.ready else []
    spot_bids = spot.bids[:LEVELS].tolist() if spot_rdy else []

    for i in range(LEVELS):
        if i < len(perp_bids):
            price, qty = perp_bids[i]
            lc = f"  {price:>{_CP},.2f}   {_fmt_qty(qty)}"
            if i < len(spot_bids):
                sp, sq = spot_bids[i]
                rc = f"{sp:>{_CP},.2f}   {_fmt_qty(sq)}"
                b  = _fmt_basis(price - sp)
            else:
                rc = " " * _RW
                b  = _B
            lines.append(f"{_GREEN}{lc}{_RESET} │ {b} │ {_GREEN}{rc}{_RESET}")
        else:
            lines.append(f"{' ' * _LW} │ {_B} │ {' ' * _RW}")

    lines.append(_pair_hr())

    return lines


# ── multi-pair renderer ────────────────────────────────────────────────────────

def render(pair_states: dict) -> None:
    all_pair_lines: list[list[str]] = []
    for i, (perp_sym, spot_sym) in enumerate(PAIRS):
        currency = _currency(spot_sym)
        state    = pair_states[currency]
        pair_lines = _render_pair(
            state["perp"],
            state["spot"] if state["spot"].ready else None,
            state.get("ticker"),
            state.get("dvol"),
            perp_sym,
            spot_sym,
            show_time=(i == len(PAIRS) - 1),
        )
        all_pair_lines.append(pair_lines)

    n_rows = max(len(ls) for ls in all_pair_lines)
    output = [_CLEAR]
    for i in range(n_rows):
        parts = [
            ls[i] if i < len(ls) else " " * PAIR_W
            for ls in all_pair_lines
        ]
        output.append(PAIR_SEP.join(parts))
    sys.stdout.write("\n".join(output) + "\n")
    sys.stdout.flush()


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    connector = DeribitConnector(testnet=False)

    pair_states: dict = {
        _currency(spot_sym): {
            "perp":   OrderBook(),
            "spot":   OrderBook(),
            "ticker": None,
            "dvol":   None,
        }
        for _, spot_sym in PAIRS
    }

    async def run_perp(perp_sym: str, currency: str) -> None:
        async for snap in connector.watch_order_book(perp_sym, depth=LEVELS):
            pair_states[currency]["perp"].update(snap)
            if pair_states[currency]["perp"].ready:
                render(pair_states)

    async def run_spot(spot_sym: str, currency: str) -> None:
        async for snap in connector.watch_order_book(spot_sym, depth=LEVELS):
            pair_states[currency]["spot"].update(snap)

    async def run_ticker(perp_sym: str, currency: str) -> None:
        async for t in connector.watch_ticker(perp_sym):
            pair_states[currency]["ticker"] = t

    async def run_dvol(dvol_ch: str, currency: str) -> None:
        async for d in connector.watch_volatility_index(dvol_ch):
            pair_states[currency]["dvol"] = d

    tasks: list = []
    for perp_sym, spot_sym in PAIRS:
        currency = _currency(spot_sym)                    # "BTC", "ETH", "SOL"
        dvol_ch  = f"{currency.lower()}_usd"              # "btc_usd", "eth_usd", "sol_usd"
        tasks += [
            run_perp(perp_sym, currency),
            run_spot(spot_sym, currency),
            run_ticker(perp_sym, currency),
            run_dvol(dvol_ch, currency),
        ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
