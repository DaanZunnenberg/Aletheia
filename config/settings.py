from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV = Path(__file__).parent / ".env"

_PRODUCTION_WARNING = """\

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!                                                        !!
!!   WARNING — PRODUCTION MODE                           !!
!!   Connecting to deribit.com with REAL FUNDS           !!
!!   Set TESTNET=true in config/.env for paper trading   !!
!!                                                        !!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
"""


@dataclass(frozen=True)
class Settings:
    dry_run: bool = True
    testnet: bool = True
    api_key: str = ""
    api_secret: str = ""
    currencies: tuple[str, ...] = ("BTC", "ETH")   # underlying currencies to monitor

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(_ENV)
        testnet = os.getenv("TESTNET", "true").lower() == "true"

        if testnet:
            api_key = os.getenv("DERIBIT_TEST_API_KEY", "")
            api_secret = os.getenv("DERIBIT_TEST_API_SECRET", "")
        else:
            print(_PRODUCTION_WARNING, file=sys.stderr)
            api_key = os.getenv("DERIBIT_API_KEY", "")
            api_secret = os.getenv("DERIBIT_API_SECRET", "")

        currencies_env = os.getenv("CURRENCIES", "BTC,ETH")
        currencies = tuple(c.strip().upper() for c in currencies_env.split(","))

        return cls(
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret,
            currencies=currencies,
        )
