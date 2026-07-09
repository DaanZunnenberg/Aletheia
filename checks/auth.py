"""
Verify that the configured API keys authenticate successfully and can reach
a private Deribit endpoint.

Usage:
    python3 -m checks.auth
"""

import asyncio
import time

import orjson
import websockets
from websockets.exceptions import WebSocketException

from config.settings import Settings

_WS_URL = "wss://www.deribit.com/ws/api/v2"
_WS_TEST_URL = "wss://test.deribit.com/ws/api/v2"


async def _send_recv(ws, payload: dict) -> dict:
    await ws.send(orjson.dumps(payload).decode())
    return orjson.loads(await asyncio.wait_for(ws.recv(), timeout=10))


async def main() -> None:
    settings = Settings.load()
    url = _WS_TEST_URL if settings.testnet else _WS_URL
    host = url.split("/")[2]

    if not settings.api_key or not settings.api_secret:
        print("ERROR: DERIBIT_API_KEY / DERIBIT_API_SECRET not set in config/.env")
        return

    print(f"Authenticating against {host} …\n")

    w = 52
    error: str | None = None

    try:
        async with websockets.connect(url, ping_interval=None, open_timeout=20) as ws:

            # --- authentication -------------------------------------------
            t0 = time.perf_counter()
            auth_msg = await _send_recv(ws, {
                "jsonrpc": "2.0", "id": 1,
                "method": "public/auth",
                "params": {
                    "grant_type": "client_credentials",
                    "client_id": settings.api_key,
                    "client_secret": settings.api_secret,
                },
            })
            auth_ms = (time.perf_counter() - t0) * 1000

            print("━" * w)

            if "error" in auth_msg:
                err = auth_msg["error"]
                print(f"  Authentication — FAILED")
                print("━" * w)
                print(f"  {'code':<18} {err['code']}")
                print(f"  {'message':<18} {err['message']}")
                print("━" * w)
                return

            result = auth_msg["result"]
            print(f"  Authentication — OK  ({auth_ms:.0f} ms)")
            print("━" * w)
            print(f"  {'client_id':<18} {settings.api_key}")
            print(f"  {'testnet':<18} {settings.testnet}")
            print(f"  {'token_type':<18} {result.get('token_type', '?')}")
            print(f"  {'expires_in':<18} {result.get('expires_in', 0):,} s")
            print(f"  {'scope':<18} {result.get('scope', '?')}")

            # --- private endpoint probe -----------------------------------
            t1 = time.perf_counter()
            acct_msg = await _send_recv(ws, {
                "jsonrpc": "2.0", "id": 2,
                "method": "private/get_account_summary",
                "params": {"currency": "BTC"},
            })
            priv_ms = (time.perf_counter() - t1) * 1000

            print()
            if "result" in acct_msg:
                acct = acct_msg["result"]
                print(f"  private/get_account_summary  ({priv_ms:.0f} ms)")
                print("━" * w)
                print(f"  {'account_type':<18} {acct.get('type', '?')}")
                print(f"  {'equity (BTC)':<18} {acct.get('equity', '?')}")
                print(f"  {'available (BTC)':<18} {acct.get('available_funds', '?')}")
                print(f"  {'margin (BTC)':<18} {acct.get('margin_balance', '?')}")
            else:
                err = acct_msg.get("error", {})
                print(f"  private/get_account_summary — FAILED")
                print("━" * w)
                print(f"  {'code':<18} {err.get('code', '?')}")
                print(f"  {'message':<18} {err.get('message', '?')}")

            print("━" * w)

    except (WebSocketException, OSError, TimeoutError) as exc:
        error = str(exc)

    if error:
        print("━" * w)
        print(f"  CONNECTION FAILED  {error}")
        print("━" * w)


if __name__ == "__main__":
    asyncio.run(main())
