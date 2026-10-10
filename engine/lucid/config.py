import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
DATA = ENGINE / "data"
ASSETS = ENGINE / "assets"


def load_env() -> None:
    """Read KEY=VALUE lines from the repo's .env.local without overriding real env vars."""
    for path in (ROOT / ".env.local", ENGINE / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()
DATA.mkdir(parents=True, exist_ok=True)


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default
