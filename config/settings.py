from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Settings:
    dry_run: bool
    symbol: str
    ob_depth: int
    testnet: bool
    api_key: str
    api_secret: str

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(Path(__file__).parent / ".env")
        return cls(
            dry_run=os.getenv("DRY_RUN", "true").lower() != "false",
            symbol=os.getenv("SYMBOL", "BTC-PERPETUAL"),
            ob_depth=int(os.getenv("OB_DEPTH", "20")),
            testnet=os.getenv("TESTNET", "false").lower() == "true",
            api_key=os.getenv("DERIBIT_API_KEY", ""),
            api_secret=os.getenv("DERIBIT_API_SECRET", ""),
        )
