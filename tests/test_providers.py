"""Tests del proveedor mock y de la semántica de fallo (fail-closed)."""

from __future__ import annotations

import pytest

from decision_lab.models import DecisionState
from decision_lab.providers.base import (
    ProviderError,
    ProviderSchemaError,
    ProviderTimeout,
)
from decision_lab.providers.mock import MockJevProvider


def _state(tool: str = "restart_service", env: str = "staging", **args: object) -> DecisionState:
    arguments = {"service": "payments", "environment": env}
    arguments.update(args)
    return DecisionState(
        request_id="req",
        tool_name=tool,
        arguments=arguments,
        environment=env,
        actor_role="operator",
        approval_granted=False,
    )


def test_mock_inspect_suggests_execute() -> None:
    sig = MockJevProvider().evaluate(_state(tool="inspect_service"))
    assert sig.suggested_route == "execute"
    assert sig.human_review_score is not None and sig.human_review_score < 0.5


def test_mock_prod_restart_suggests_review() -> None:
    sig = MockJevProvider().evaluate(_state(env="production"))
    assert sig.suggested_route == "review"


def test_mock_risky_argument_suggests_reject() -> None:
    sig = MockJevProvider().evaluate(_state(service="payments-force"))
    assert sig.suggested_route == "reject"


def test_mock_timeout_raises() -> None:
    with pytest.raises(ProviderTimeout):
        MockJevProvider(fail_mode="timeout").evaluate(_state())


def test_mock_schema_raises() -> None:
    with pytest.raises(ProviderSchemaError):
        MockJevProvider(fail_mode="schema").evaluate(_state())


def test_mock_error_raises() -> None:
    with pytest.raises(ProviderError):
        MockJevProvider(fail_mode="error").evaluate(_state())


def test_mock_force_execute() -> None:
    sig = MockJevProvider(suggest_execute_always=True).evaluate(_state(env="production"))
    assert sig.suggested_route == "execute"


def test_provider_protocol_runtime_check() -> None:
    from decision_lab.providers.base import DecisionProvider

    assert isinstance(MockJevProvider(), DecisionProvider)
