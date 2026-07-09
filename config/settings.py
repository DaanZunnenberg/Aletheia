from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV = Path(__file__).parent / ".env"


@dataclass
class Settings:
    # Strategy / runtime parameters — edit here, not in .env
    dry_run: bool = True
    symbol: str = "BTC-PERPETUAL"
    ob_depth: int = 20
    testnet: bool = False
    # Credentials — loaded from config/.env, never hardcoded
    api_key: str = ""
    api_secret: str = ""

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(_ENV)
        return cls(
            testnet=os.getenv("TESTNET", "false").lower() == "true",
            api_key=os.getenv("DERIBIT_API_KEY", ""),
            api_secret=os.getenv("DERIBIT_API_SECRET", ""),
        )
