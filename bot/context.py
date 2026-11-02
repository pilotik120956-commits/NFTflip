"""Shared application context injected into every handler."""

from __future__ import annotations

from dataclasses import dataclass

from config import Settings
from db.database import Database
from services.rates import TonRate
from services.scanner import Scanner


@dataclass(slots=True)
class AppContext:
    settings: Settings
    db: Database
    scanner: Scanner
    rates: TonRate
