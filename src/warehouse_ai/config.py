"""Configuration loader for warehouse_ai.

Reads ``configs/default.yaml`` (or a path supplied at runtime) and exposes
its values through a validated Pydantic model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PathsConfig(BaseModel):
    data_raw: str = "data/raw"
    data_processed: str = "data/processed"
    configs: str = "configs"
    outputs: str = "outputs"


class WarehouseConfig(BaseModel):
    trolley_capacity: int = 27
    io_depot_node: str = "CC-08"
    num_aisles: int = 17
    num_racks: int = 25
    num_locations: int = 2293
    slots_per_location: int = 18
    pick_levels: list[int] = Field(default_factory=lambda: [0, 1, 2])
    reserve_levels: list[int] = Field(default_factory=lambda: [3, 4])


class LaborConfig(BaseModel):
    walk_speed_mps: float = 1.0
    setup_per_wave_s: float = 60.0
    per_location_stop_s: float = 10.0
    per_unit_handling_s: float = 6.0
    level_penalty_s: float = 5.0
    shift_hours: float = 7.5
    m_per_unit_along: float = 0.0732
    m_per_unit_cross: float = 0.03222


class LLMConfig(BaseModel):
    provider: str = "mock"
    model: str = "gemini-2.0-flash"
    temperature: float = 0.1
    max_tokens: int = 4096


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    random_seed: int = 42
    warehouse: WarehouseConfig = Field(default_factory=WarehouseConfig)
    labor: LaborConfig = Field(default_factory=LaborConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # src/warehouse_ai/config.py → project root


def _find_project_root() -> Path:
    """Walk up from CWD or this file to locate the project root (contains pyproject.toml)."""
    # Try from the module location first
    candidate = _PROJECT_ROOT
    if (candidate / "pyproject.toml").exists():
        return candidate
    # Fallback: walk up from cwd
    candidate = Path.cwd()
    for _ in range(10):
        if (candidate / "pyproject.toml").exists():
            return candidate
        candidate = candidate.parent
    return Path.cwd()


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load and validate the YAML configuration.

    Parameters
    ----------
    config_path : str | Path | None
        Explicit path to a YAML file.  When *None* the loader searches for
        ``configs/default.yaml`` relative to the project root.

    Returns
    -------
    AppConfig
        Validated configuration object.
    """
    if config_path is None:
        root = _find_project_root()
        config_path = root / "configs" / "default.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        # Return defaults when no file is present (e.g. in CI)
        return AppConfig()

    with open(config_path, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    return AppConfig(**raw)


# Module-level singleton (lazy)
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the cached application config (loaded once on first call)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config

