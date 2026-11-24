"""Architectural guard: the Central AI Gateway is the only way out to a provider.

Phase 1 requires a single choke point so every AI call is routed, quota-checked,
and audited. These tests fail the build the moment a second exit appears.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
GATEWAY = APP_DIR / "services" / "ai_gateway.py"
LLM_CLIENT = APP_DIR / "core" / "llm_client.py"

# Modules allowed to import the raw provider wrapper, and *why*.
ALLOWED_LLM_CLIENT_IMPORTS = {
    LLM_CLIENT.name: "the wrapper itself",
    GATEWAY.name: "the gateway is the choke point",
    "runtime_config.py": "closes cached client pools when settings change",
    "main.py": "closes client pools on application shutdown",
}

# Minting an AI client (or hitting a model endpoint over raw HTTP) outside these
# files would bypass routing, auditing, and quotas.
PROVIDER_SDK_NAMES = {"AsyncOpenAI", "OpenAI", "AsyncAnthropic", "Anthropic"}
PROVIDER_HTTP_PATTERN = re.compile(
    r"chat/completions|/embeddings\b|/audio/transcriptions|/audio/speech", re.IGNORECASE
)

# `llm_client` helpers that are pure bookkeeping, not inference.
BOOKKEEPING_EXPORTS = {"track_token_usage", "close_llm_clients"}


def _python_files() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def test_no_provider_sdk_is_imported_outside_the_llm_client():
    offenders = []
    for path in _python_files():
        if path == LLM_CLIENT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in {"openai", "anthropic"}:
                        offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in {"openai", "anthropic"}:
                    offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    assert offenders == [], f"provider SDK imported outside app/core/llm_client.py: {offenders}"


def test_no_provider_client_is_constructed_outside_the_llm_client():
    offenders = []
    for path in _python_files():
        if path == LLM_CLIENT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in PROVIDER_SDK_NAMES:
                offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    assert offenders == [], f"AI client constructed outside the wrapper: {offenders}"


def test_only_the_gateway_makes_raw_model_http_calls():
    offenders = []
    for path in _python_files():
        if path == GATEWAY:
            continue
        source = path.read_text(encoding="utf-8")
        for match in PROVIDER_HTTP_PATTERN.finditer(source):
            line = source[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(APP_DIR.parent)}:{line} -> {match.group(0)}")
    assert offenders == [], (
        "raw model-endpoint HTTP outside app/services/ai_gateway.py: " + "; ".join(offenders)
    )


def test_llm_client_importers_are_an_allowlist():
    """Any new importer of the raw wrapper must be a deliberate, reviewed decision."""
    offenders = []
    for path in _python_files():
        if path.name in ALLOWED_LLM_CLIENT_IMPORTS or path == LLM_CLIENT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.core.llm_client":
                imported = {alias.name for alias in node.names}
                stray = imported - BOOKKEEPING_EXPORTS
                if stray:
                    offenders.append(
                        f"{path.relative_to(APP_DIR.parent)}:{node.lineno} imports {sorted(stray)}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.core.llm_client":
                        offenders.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    assert offenders == [], (
        "app.core.llm_client imported outside the allowlist (route it through "
        f"app.services.ai_gateway instead): {offenders}"
    )


def test_every_gateway_feature_exposes_a_via_gateway_helper():
    """Each capability the pack names must have one audited entry point."""
    source = GATEWAY.read_text(encoding="utf-8")
    for helper in (
        "complete_text_via_gateway",
        "complete_json_via_gateway",
        "vision_json_via_gateway",
        "transcribe_audio_via_gateway",
        "embed_via_gateway",
        "probe_endpoint",
    ):
        assert f"async def {helper}(" in source, f"missing gateway helper: {helper}"
