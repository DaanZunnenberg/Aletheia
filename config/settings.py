from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class VenueCredentials:
    api_key: str
    api_secret: str


@dataclass
class Settings:
    dry_run: bool
    venue: str
    symbol: str
    ob_depth: int
    testnet: bool
    credentials: dict[str, VenueCredentials] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Settings:
        load_dotenv(Path(__file__).parent / ".env")

        venue = os.getenv("VENUE", "deribit")
        return cls(
            dry_run=os.getenv("DRY_RUN", "true").lower() != "false",
            venue=venue,
            symbol=os.getenv("SYMBOL", "BTC-PERPETUAL"),
            ob_depth=int(os.getenv("OB_DEPTH", "20")),
            testnet=os.getenv("TESTNET", "false").lower() == "true",
            credentials={
                venue: VenueCredentials(
                    api_key=os.getenv(f"{venue.upper()}_API_KEY", ""),
                    api_secret=os.getenv(f"{venue.upper()}_API_SECRET", ""),
                )
            },
        )
