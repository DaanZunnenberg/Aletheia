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


@dataclass
class Settings:
    # Runtime parameters — edit here, not in .env
    dry_run: bool = True
    symbol: str = "BTC-PERPETUAL"
    ob_depth: int = 20
    # Populated by load()
    testnet: bool = True
    api_key: str = ""
    api_secret: str = ""

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

        return cls(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret,
        )
