"""
Probe the Deribit WebSocket endpoint and report connect time and round-trip latency.

Usage:
    python3 -m checks.ws
"""

import asyncio
import statistics
import time

import orjson
import websockets
from websockets.exceptions import WebSocketException

from config.settings import Settings

_WS_URL = "wss://www.deribit.com/ws/api/v2"
_WS_TEST_URL = "wss://test.deribit.com/ws/api/v2"
N = 15


async def main() -> None:
    settings = Settings.load()
    url = _WS_TEST_URL if settings.testnet else _WS_URL
    host = url.split("/")[2]

    print(f"Connecting to {url} …\n")

    connect_ms: float = 0.0
    samples: list[float] = []
    error: str | None = None

    try:
        t_conn = time.perf_counter()
        async with websockets.connect(url, ping_interval=None, open_timeout=20) as ws:
            connect_ms = (time.perf_counter() - t_conn) * 1000
            print(f"  connected in {connect_ms:.1f} ms\n")
            print(f"  Sending {N} pings …\n")

            for i in range(N):
                t0 = time.perf_counter()
                await ws.send(orjson.dumps({
                    "jsonrpc": "2.0", "method": "public/test", "params": {}, "id": i,
                }).decode())
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                rtt = (time.perf_counter() - t0) * 1000
                msg = orjson.loads(raw)
                ok = "result" in msg
                samples.append(rtt)
                print(f"  [{i + 1:>2}]  {rtt:6.1f} ms  {'ok' if ok else 'ERR'}")

    except (WebSocketException, OSError, TimeoutError) as exc:
        error = str(exc)

    w = 46
    print()
    print("━" * w)
    print(f"  WebSocket  ·  {host}")
    print("━" * w)

    if error and not samples:
        print(f"  FAILED  {error}")
        print("━" * w)
        return

    print(f"  {'connect':<14} {connect_ms:.1f} ms")
    print(f"  {'pings':<14} {len(samples)}")
    print(f"  {'rtt min':<14} {min(samples):.1f} ms")
    print(f"  {'rtt mean':<14} {statistics.mean(samples):.1f} ms")
    print(f"  {'rtt median':<14} {statistics.median(samples):.1f} ms")
    print(f"  {'rtt max':<14} {max(samples):.1f} ms")
    print(f"  {'rtt stdev':<14} {statistics.stdev(samples):.1f} ms")
    if error:
        print(f"  {'note':<14} dropped mid-run: {error}")
    print("━" * w)


if __name__ == "__main__":
    asyncio.run(main())
