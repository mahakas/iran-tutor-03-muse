"""Provide harmless defaults so unit tests never require a developer .env file."""

from __future__ import annotations

import os


# Settings are loaded while importing the application. These values are only
# placeholders: unit tests do not make network or database calls.
_TEST_SETTINGS = {
    "DEMO_MODE": "false",
    "REQUIRE_STUDENT_GRADE_PROFILE": "false",
    "LLM_BASE_URL": "https://example.invalid/v1",
    "LLM_API_KEY": "unit-test-key",
    "VISION_MODEL_A": "unit-test-model-a",
    "VISION_MODEL_B": "unit-test-model-b",
    "VISION_MODEL_PRIMARY": "unit-test-model-a",
    "DATABASE_URL": "postgresql+asyncpg://test:test@127.0.0.1:5432/test",
    # Shared IP counters would throttle admin logins across the whole suite. Rate-limit
    # behavior is covered explicitly in test_bugfix_hardening.py and test_phase1_governance.py.
    "RATE_LIMIT_ENABLED": "false",
}

for key, value in _TEST_SETTINGS.items():
    os.environ.setdefault(key, value)

# Tests log in with these exact admin credentials. Force them (not setdefault) so a developer's
# backend/.env cannot override them; environment variables take priority over .env values.
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "123"
