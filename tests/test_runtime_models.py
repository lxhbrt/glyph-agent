#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for runtime model hot-apply."""
import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure key so provider can construct (no network in apply_models)
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")
os.environ.setdefault("AGENT_PRIMARY_PROVIDER", "openrouter")
os.environ.setdefault("MODE", "agent")

from core.providers import factory
from core import config
import core.runtime_models as runtime_models


def test_apply_shared_and_clear_fallback():
    factory.reset_provider()
    importlib.reload(config)
    importlib.reload(factory)
    importlib.reload(runtime_models)

    snap = runtime_models.apply_models(
        {
            "shared": {
                "primary": "deepseek/deepseek-v4-flash-0731",
                "fallback": "inclusionai/ling-3.0-tiny:free",
            }
        }
    )
    assert snap["shared"]["primary"] == "deepseek/deepseek-v4-flash-0731"
    assert snap["shared"]["fallback"] == "inclusionai/ling-3.0-tiny:free"
    assert snap["code"]["primary"] == "deepseek/deepseek-v4-flash-0731"

    snap2 = runtime_models.apply_models(
        {
            "shared": {
                "primary": "deepseek/deepseek-v4-flash-0731",
                "fallback": "",
            }
        }
    )
    assert snap2["shared"]["fallback"] is None
    p = factory.get_provider()
    assert p.model == "deepseek/deepseek-v4-flash-0731"
    assert not p.fallback_model


def test_code_override():
    factory.reset_provider()
    snap = runtime_models.apply_models(
        {
            "shared": {"primary": "a/primary", "fallback": "a/fb"},
            "code": {"primary": "b/code", "fallback": ""},
        }
    )
    assert snap["shared"]["primary"] == "a/primary"
    assert snap["code"]["primary"] == "b/code"
    assert snap["code"]["fallback"] is None
    assert snap["code"]["override"] is True
    assert config.CODE_OPENROUTER_MODEL == "b/code"


if __name__ == "__main__":
    test_apply_shared_and_clear_fallback()
    test_code_override()
    print("ok")
