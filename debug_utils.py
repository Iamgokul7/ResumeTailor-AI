import json
from pathlib import Path
from typing import Any

DEBUG_DIR = Path("output") / "debug"


def ensure_debug_dir():
    """Create output/debug folder if it doesn't exist."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def save_json(filename: str, data: Any):
    """
    Save Python object as formatted JSON.
    """
    ensure_debug_dir()

    filepath = DEBUG_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def save_html(filename: str, html: str):
    """
    Save rendered HTML for debugging.
    """
    ensure_debug_dir()

    filepath = DEBUG_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)