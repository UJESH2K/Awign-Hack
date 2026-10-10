"""GPU-second ledger. Reactor bills every second a session is `ready`, idle or not.

Two layers of protection:
  1. This ledger refuses to open a session whose planned length would cross the cap.
  2. The token is minted with `max_session_duration_seconds`, so Reactor itself kills the
     session on schedule even if this process crashes mid-run.
"""
import functools
import json
import threading
import time
import urllib.request
from dataclasses import dataclass

from .config import DATA, env

LEDGER = DATA / "budget.json"

# USD per second, used when the public pricing endpoint is unreachable.
FALLBACK_RATES = {"lingbot-world-2": 0.007, "lingbot": 0.005, "helios": 0.017}

_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def _slug(model: str) -> str:
    return model.split("/", 1)[-1]


@functools.cache
def rate_per_second(model: str) -> float:
    """Live price, fetched once per process (it is a blocking call made from async code)."""
    slug = _slug(model)
    try:
        with urllib.request.urlopen("https://api.reactor.inc/pricing", timeout=5) as resp:
            pricing = json.load(resp)
        for entry in pricing.get("models", []):
            if entry["name"] == slug:
                rate = entry["rate"]
                if "amount_per_sec_usd" in rate:
                    return float(rate["amount_per_sec_usd"])
                per_dollar = pricing["settings"]["credits_per_dollar"]
                per_sec = rate.get("amount_per_sec", rate.get("amount_per_min", 0) / 60)
                return per_sec / per_dollar
    except Exception:
        pass
    return FALLBACK_RATES.get(slug, 0.02)


def _read() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"sessions": []}


def _write(data: dict) -> None:
    LEDGER.write_text(json.dumps(data, indent=2), encoding="utf-8")


def cap_usd() -> float:
    return float(env("LUCID_BUDGET_USD", "25"))


def reserve_usd() -> float:
    return float(env("LUCID_RESERVE_USD", "3"))


def spent_usd() -> float:
    with _lock:
        return round(sum(s["usd"] for s in _read()["sessions"]), 4)


def summary() -> dict:
    with _lock:
        sessions = _read()["sessions"]
    spent = sum(s["usd"] for s in sessions)
    return {
        "cap_usd": cap_usd(),
        "reserve_usd": reserve_usd(),
        "spent_usd": round(spent, 4),
        "spendable_usd": round(max(0.0, cap_usd() - reserve_usd() - spent), 4),
        "gpu_seconds": round(sum(s["seconds"] for s in sessions), 1),
        "sessions": sessions[-20:],
    }


@dataclass
class Grant:
    model: str
    seconds: int
    rate: float


def authorize(model: str, planned_seconds: float) -> Grant:
    """Approve a session of at most `planned_seconds`, or raise BudgetExceeded."""
    rate = rate_per_second(model)
    spendable = cap_usd() - reserve_usd() - spent_usd()
    cost = planned_seconds * rate
    if cost > spendable:
        raise BudgetExceeded(
            f"Planned {planned_seconds:.0f}s of {model} costs ${cost:.2f}, "
            f"but only ${spendable:.2f} is spendable (cap ${cap_usd():.2f}, reserve ${reserve_usd():.2f})."
        )
    return Grant(model=model, seconds=max(1, int(planned_seconds)), rate=rate)


def record(model: str, seconds: float, purpose: str, rate: float | None = None) -> dict:
    rate = rate if rate is not None else rate_per_second(model)
    entry = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "purpose": purpose,
        "seconds": round(seconds, 2),
        "usd": round(seconds * rate, 4),
    }
    with _lock:
        data = _read()
        data["sessions"].append(entry)
        _write(data)
    return entry
