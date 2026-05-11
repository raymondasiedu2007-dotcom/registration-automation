from __future__ import annotations

import yaml  # type: ignore


def safe_load(text: str):
    return yaml.safe_load(text)
