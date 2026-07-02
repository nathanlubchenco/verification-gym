"""Configuration loading: config.yaml + GYM_* env var overrides (DECISIONS D2-D4)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RepoSpec:
    name: str
    url: str
    pin: str | None = None


@dataclass
class Targets:
    n_per_class: int
    floor_per_class: int
    clean_fraction: float


@dataclass
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


@dataclass
class Config:
    seed: int
    generator_model: str
    verifier_model: str
    spend_cap_usd: float
    data_dir: Path
    events_dir: Path
    reports_dir: Path
    payload_budget_chars: int
    targets: Targets
    pricing: dict[str, ModelPrice]
    repos: list[RepoSpec]
    root: Path = field(default_factory=Path.cwd)

    @property
    def db_path(self) -> Path:
        return self.root / self.data_dir / "gym.db"


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text())

    seed = int(os.environ.get("GYM_SEED", raw["seed"]))
    generator_model = os.environ.get("GYM_GENERATOR_MODEL", raw["generator_model"])
    verifier_model = os.environ.get("GYM_VERIFIER_MODEL", raw["verifier_model"])
    spend_cap_usd = float(os.environ.get("GYM_SPEND_CAP_USD", raw["spend_cap_usd"]))

    return Config(
        seed=seed,
        generator_model=generator_model,
        verifier_model=verifier_model,
        spend_cap_usd=spend_cap_usd,
        data_dir=Path(raw["data_dir"]),
        events_dir=Path(raw["events_dir"]),
        reports_dir=Path(raw["reports_dir"]),
        payload_budget_chars=int(raw["payload_budget_chars"]),
        targets=Targets(**raw["targets"]),
        pricing={k: ModelPrice(**v) for k, v in raw["pricing"].items()},
        repos=[RepoSpec(**r) for r in raw["repos"]],
        root=path.resolve().parent,
    )
