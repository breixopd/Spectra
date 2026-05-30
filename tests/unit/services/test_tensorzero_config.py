"""Guards that keep the AI router's tier maps in sync with the gateway TOML.

The router (`spectra_ai.router`) attributes cost/observability using an in-code
task->tier->model map. TensorZero routes the same tasks via `config/tensorzero.toml`.
If the two drift, cost attribution silently lies and the wrong model may serve a tier
(e.g. the historical bug where the "capable" tier used a flash-aliased model). These
tests fail loudly on any mismatch.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from spectra_ai.router import DEFAULT_TIER, TASK_TIERS, TIER_MODELS

# Only these explicit V4 model IDs are valid — the legacy deepseek-chat/deepseek-reasoner
# aliases are deprecated by DeepSeek (2026-07-24) and both alias to v4-flash.
ALLOWED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


def _load_config() -> dict:
    root = Path(__file__).resolve()
    for parent in root.parents:
        candidate = parent / "config" / "tensorzero.toml"
        if candidate.is_file():
            return tomllib.loads(candidate.read_text())
    raise AssertionError("config/tensorzero.toml not found walking up from test file")


def test_tier_models_match_gateway_toml():
    config = _load_config()
    models = config["models"]
    for tier, expected_model in TIER_MODELS.items():
        primary = models[tier]["providers"]["primary"]
        assert primary["model_name"] == expected_model, (
            f"tier '{tier}' is '{primary['model_name']}' in tensorzero.toml "
            f"but '{expected_model}' in router.TIER_MODELS"
        )


def test_task_tiers_match_gateway_functions():
    config = _load_config()
    functions = config["functions"]
    for task, expected_tier in TASK_TIERS.items():
        variant = functions[task]["variants"]["default"]
        assert variant["model"] == expected_tier, (
            f"function '{task}' routes to tier '{variant['model']}' in tensorzero.toml "
            f"but '{expected_tier}' in router.TASK_TIERS"
        )


def test_default_function_tier_matches():
    config = _load_config()
    default_variant = config["functions"]["default"]["variants"]["default"]
    assert default_variant["model"] == DEFAULT_TIER


def test_only_non_deprecated_models_used():
    config = _load_config()
    for tier, conf in config["models"].items():
        model_name = conf["providers"]["primary"]["model_name"]
        assert model_name in ALLOWED_MODELS, (
            f"tier '{tier}' uses '{model_name}', which is not an allowed non-deprecated "
            f"DeepSeek V4 model {sorted(ALLOWED_MODELS)}"
        )


def test_tier_models_are_priced():
    from spectra_ai_core.cost_tracker import MODEL_PRICING

    for model in TIER_MODELS.values():
        assert model in MODEL_PRICING, f"{model} is routed but has no cost_tracker pricing"
