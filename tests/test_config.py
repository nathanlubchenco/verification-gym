"""Tests for gym.config — yaml loading and env-var overrides."""

import textwrap

import pytest

from gym.config import Config, load_config

MINIMAL_YAML = textwrap.dedent("""\
    seed: 123
    generator_model: claude-opus-4-8
    verifier_model: claude-opus-4-8
    spend_cap_usd: 125.0
    data_dir: data
    events_dir: events
    reports_dir: reports
    payload_budget_chars: 110000
    targets:
      n_per_class: 50
      floor_per_class: 30
      clean_fraction: 0.40
    pricing:
      claude-opus-4-8: {input_per_mtok: 5.0, output_per_mtok: 25.0}
    repos:
      - name: click
        url: https://github.com/pallets/click
        pin: null
""")


@pytest.fixture()
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(MINIMAL_YAML)
    return p


def test_load_defaults(cfg_file, monkeypatch):
    for var in ("GYM_SEED", "GYM_GENERATOR_MODEL", "GYM_VERIFIER_MODEL", "GYM_SPEND_CAP_USD"):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config(cfg_file)
    assert isinstance(cfg, Config)
    assert cfg.seed == 123
    assert cfg.generator_model == "claude-opus-4-8"
    assert cfg.spend_cap_usd == 125.0
    assert cfg.targets.n_per_class == 50
    assert cfg.targets.floor_per_class == 30
    assert cfg.repos[0].name == "click"
    assert cfg.repos[0].pin is None
    assert cfg.pricing["claude-opus-4-8"].input_per_mtok == 5.0


def test_env_overrides(cfg_file, monkeypatch):
    monkeypatch.setenv("GYM_SEED", "999")
    monkeypatch.setenv("GYM_GENERATOR_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("GYM_VERIFIER_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("GYM_SPEND_CAP_USD", "10.5")
    cfg = load_config(cfg_file)
    assert cfg.seed == 999
    assert cfg.generator_model == "claude-sonnet-5"
    assert cfg.verifier_model == "claude-haiku-4-5"
    assert cfg.spend_cap_usd == 10.5


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")
