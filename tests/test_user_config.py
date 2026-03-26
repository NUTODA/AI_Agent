"""Tests for ~/.browser-agent/config.yaml helpers."""

from __future__ import annotations

import os

import pytest

from browser_agent.config import (
    UserHomeConfig,
    apply_home_config_to_environment,
    delete_home_config_file,
    home_config_path,
    load_home_config_file,
    save_home_config,
)


def test_save_load_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = UserHomeConfig(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="secret-key",
        model="openai/gpt-4o-mini",
    )
    save_home_config(cfg)
    path = home_config_path()
    assert path.is_file()
    loaded = load_home_config_file()
    assert loaded is not None
    assert loaded.provider == "openrouter"
    assert loaded.base_url == "https://openrouter.ai/api/v1"
    assert loaded.api_key == "secret-key"
    assert loaded.model == "openai/gpt-4o-mini"


def test_apply_respects_existing_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BROWSER_AGENT_PLANNER_MODEL", "already-set")
    save_home_config(
        UserHomeConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="k",
            model="gpt-4o",
        ),
    )
    apply_home_config_to_environment()
    assert os.environ.get("BROWSER_AGENT_PLANNER_MODEL") == "already-set"


def test_delete_home_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_home_config(
        UserHomeConfig(provider="openai", base_url="https://x", api_key="k", model="m"),
    )
    assert delete_home_config_file() is True
    assert not home_config_path().is_file()
    assert delete_home_config_file() is False
