from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")


def _id_set(value: str) -> frozenset[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            try:
                result.add(int(part))
            except ValueError as exc:
                raise ValueError(f"Expected Telegram numeric ID, got {part!r}") from exc
    return frozenset(result)


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    database_path: Path = Path(
        os.getenv("DATABASE_PATH", str(PROJECT_DIR / "data" / "dht_roleplay.sqlite3"))
    )
    admin_ids: frozenset[int] = _id_set(os.getenv("ADMIN_IDS", ""))
    owner_ids: frozenset[int] = _id_set(
        os.getenv("OWNER_IDS", os.getenv("ADMIN_IDS", ""))
    )
    start_balance: int = int(os.getenv("START_BALANCE", "5000"))
    work_cooldown_seconds: int = int(os.getenv("WORK_COOLDOWN_SECONDS", "3600"))
    business_payout_seconds: int = int(os.getenv("BUSINESS_PAYOUT_SECONDS", "86400"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    def validate(self) -> None:
        if self.start_balance < 0:
            raise ValueError("START_BALANCE must be zero or greater")
        if self.work_cooldown_seconds < 1:
            raise ValueError("WORK_COOLDOWN_SECONDS must be at least 1")
        if self.business_payout_seconds < 1:
            raise ValueError("BUSINESS_PAYOUT_SECONDS must be at least 1")
