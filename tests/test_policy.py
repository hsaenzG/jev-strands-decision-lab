"""Tests del motor de políticas determinista y las pruebas de aceptación."""

from __future__ import annotations

from decision_lab.models import DecisionSignals, DecisionState
from decision_lab.policy import evaluate_policy


def _state(**kw: object) -> DecisionState:
    base: dict[str, object] = dict(
        request_id="req_test",
        tool_name="restart_service",
        arguments={"service": "payments", "environment": "production"},
        environment="production",
        actor_role="operator",
        approval_granted=False,
    )
    base.update(kw)
    return DecisionState(**base)  # type: ignore[arg-type]


def _signals(route: str = "execute", score: float | None = 0.1) -> DecisionSignals:
    return DecisionSignals(
        suggested_route=route,  # type: ignore[arg-type]
        human_review_score=score,
        risk_label="test",
        provider="mock",
    )


def test_unknown_tool_denied() -> None:
    out = evaluate_policy(_state(tool_name="delete_db"), _signals())
    assert out.action == "deny"
    assert out.reason_code == "unknown_tool"


def test_invalid_arguments_denied() -> None:
    out = evaluate_policy(_state(arguments={"service": "payments"}), _signals())
    assert out.action == "deny"
    assert out.reason_code == "invalid_arguments"


def test_wrong_argument_type_denied() -> None:
    out = evaluate_policy(_state(arguments={"service": 1, "environment": "production"}), _signals())
    assert out.action == "deny"
    assert out.reason_code == "invalid_arguments"


def test_insufficient_role_denied() -> None:
    out = evaluate_policy(_state(actor_role="developer"), _signals())
    assert out.action == "deny"
    assert out.reason_code == "unauthorized_role"


def test_empty_role_denied() -> None:
    out = evaluate_policy(_state(tool_name="inspect_service", actor_role=""), _signals())
    assert out.action == "deny"


# --- Pruebas de aceptación NO negociables ----------------------------------


def test_unauthorized_restart_never_executes_even_if_jev_says_execute() -> None:
    """Aun si Jev recomienda execute, un rol sin permiso -> deny."""
    out = evaluate_policy(_state(actor_role="developer"), _signals(route="execute"))
    assert out.action == "deny"


def test_production_restart_without_approval_enters_review() -> None:
    out = evaluate_policy(_state(approval_granted=False), _signals(route="execute"))
    assert out.action == "review"
    assert out.reason_code == "production_requires_approval"


def test_production_write_review_dominates_provider_execute() -> None:
    """La regla de aprobación en prod domina sobre un execute del proveedor."""
    out = evaluate_policy(_state(approval_granted=False), _signals(route="execute", score=0.0))
    assert out.action == "review"


def test_provider_failure_fails_closed() -> None:
    """signals=None (proveedor caído) -> deny (fail-closed)."""
    out = evaluate_policy(_state(actor_role="operator"), None)
    assert out.action == "deny"
    assert out.reason_code == "provider_unavailable"


def test_provider_reject_denies() -> None:
    out = evaluate_policy(
        _state(environment="staging", approval_granted=True),
        _signals(route="reject"),
    )
    assert out.action == "deny"
    assert out.reason_code == "provider_reject"


def test_provider_review_reviews_in_non_prod() -> None:
    out = evaluate_policy(
        _state(tool_name="inspect_service", environment="staging", actor_role="viewer"),
        _signals(route="review"),
    )
    assert out.action == "review"


def test_risk_threshold_forces_review() -> None:
    out = evaluate_policy(
        _state(tool_name="inspect_service", environment="staging", actor_role="viewer"),
        _signals(route="execute", score=0.9),
    )
    assert out.action == "review"
    assert out.reason_code == "risk_threshold_exceeded"


def test_prod_restart_with_matching_approval_allows() -> None:
    out = evaluate_policy(_state(approval_granted=True), _signals(route="execute", score=0.1))
    assert out.action == "allow"


def test_staging_restart_allows() -> None:
    out = evaluate_policy(
        _state(environment="staging", arguments={"service": "checkout", "environment": "staging"}),
        _signals(route="execute", score=0.1),
    )
    assert out.action == "allow"


def test_readonly_inspect_allows() -> None:
    out = evaluate_policy(
        _state(
            tool_name="inspect_service",
            environment="staging",
            actor_role="viewer",
            arguments={"service": "payments", "environment": "staging"},
        ),
        _signals(route="execute", score=0.05),
    )
    assert out.action == "allow"
