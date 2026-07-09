"""
Probe the Deribit REST API and report latency statistics.

Usage:
    python3 -m checks.rest
"""

import asyncio
import statistics
import time

import aiohttp
import orjson

from config.settings import Settings

_URL = "https://www.deribit.com/api/v2/public/test"
_TEST_URL = "https://test.deribit.com/api/v2/public/test"
N = 15


async def main() -> None:
    settings = Settings.load()
    url = _TEST_URL if settings.testnet else _URL
    host = url.split("/")[2]

    print(f"Probing {url}  ({N} requests) …\n")

    samples: list[float] = []
    version = "?"
    error: str | None = None

    try:
        async with aiohttp.ClientSession() as session:
            for i in range(N):
                t0 = time.perf_counter()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    body = orjson.loads(await resp.read())
                dt = (time.perf_counter() - t0) * 1000
                samples.append(dt)
                version = body.get("result", {}).get("version", "?")
                print(f"  [{i + 1:>2}]  {dt:6.1f} ms")
    except Exception as exc:
        error = str(exc)

    w = 46
    print()
    print("━" * w)
    print(f"  REST  ·  {host}")
    print("━" * w)

    if error or not samples:
        print(f"  FAILED  {error or 'no samples'}")
        print("━" * w)
        return

    print(f"  {'requests':<14} {len(samples)}")
    print(f"  {'min':<14} {min(samples):.1f} ms")
    print(f"  {'mean':<14} {statistics.mean(samples):.1f} ms")
    print(f"  {'median':<14} {statistics.median(samples):.1f} ms")
    print(f"  {'max':<14} {max(samples):.1f} ms")
    print(f"  {'stdev':<14} {statistics.stdev(samples):.1f} ms")
    print(f"  {'server':<14} {version}")
    print("━" * w)


if __name__ == "__main__":
    asyncio.run(main())
