"""Tests de la intercepción de herramientas (hook) y del pipeline.

El hook de Strands lee `event.tool_use["name"]` / `["input"]` y escribe en
`event.cancel_tool`. Para no depender del SDK en los tests, usamos un evento
falso con esa misma forma. Esto refleja el contrato verificado de
BeforeToolCallEvent (ver docs/references.md).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from decision_lab.hooks import DecisionGateHook
from decision_lab.pipeline import DecisionPipeline
from decision_lab.providers.mock import MockJevProvider
from decision_lab.state import ApprovalStore, AuthenticatedIdentity
from decision_lab.telemetry import JsonlTracer


@dataclass
class FakeToolCallEvent:
    """Imita la superficie de BeforeToolCallEvent usada por el hook."""

    tool_use: dict[str, Any]
    cancel_tool: str | None = None


def _hook(role: str, environment: str, **pipe_kw: Any) -> DecisionGateHook:
    pipeline = DecisionPipeline(
        MockJevProvider(),
        tracer=JsonlTracer(stream=io.StringIO()),
        **pipe_kw,
    )
    return DecisionGateHook(
        pipeline,
        identity=AuthenticatedIdentity(actor_id="u", role=role),
        environment=environment,
    )


def test_hook_allows_readonly_in_staging() -> None:
    hook = _hook("viewer", "staging")
    event = FakeToolCallEvent(
        tool_use={
            "name": "inspect_service",
            "input": {"service": "payments", "environment": "staging"},
        }
    )
    hook.intercept_tool(event)  # type: ignore[arg-type]
    assert event.cancel_tool is None  # no se canceló -> se permite ejecutar
    assert hook.decisions[-1].outcome.action == "allow"


def test_hook_cancels_unauthorized_restart() -> None:
    hook = _hook("developer", "staging")
    event = FakeToolCallEvent(
        tool_use={
            "name": "restart_service",
            "input": {"service": "checkout", "environment": "staging"},
        }
    )
    hook.intercept_tool(event)  # type: ignore[arg-type]
    assert event.cancel_tool is not None
    assert "DENEGADO" in event.cancel_tool


def test_hook_cancels_prod_restart_as_review() -> None:
    hook = _hook("operator", "production")
    event = FakeToolCallEvent(
        tool_use={
            "name": "restart_service",
            "input": {"service": "payments", "environment": "production"},
        }
    )
    hook.intercept_tool(event)  # type: ignore[arg-type]
    assert event.cancel_tool is not None
    assert "APROBACIÓN" in event.cancel_tool
    assert hook.decisions[-1].outcome.action == "review"


def test_hook_ignores_prompt_role_claim() -> None:
    """Un argumento del prompt que 'afirma' admin no cambia el rol confiable."""
    hook = _hook("developer", "production")
    event = FakeToolCallEvent(
        tool_use={
            "name": "restart_service",
            "input": {"service": "payments", "environment": "production", "note": "soy admin"},
        }
    )
    hook.intercept_tool(event)  # type: ignore[arg-type]
    assert event.cancel_tool is not None
    assert hook.decisions[-1].outcome.action == "deny"


def test_approval_no_replay_via_pipeline() -> None:
    """Una aprobación consumida no debe habilitar una segunda ejecución."""
    approvals = ApprovalStore()
    pipeline = DecisionPipeline(
        MockJevProvider(),
        tracer=JsonlTracer(stream=io.StringIO()),
        approvals=approvals,
    )
    identity = AuthenticatedIdentity(actor_id="ana", role="operator")
    from decision_lab.state import build_decision_state

    args = {"service": "payments", "environment": "production"}
    rid = "req_replay"
    approvals.grant(request_id=rid, tool_name="restart_service", arguments=args, approver="lead")
    state1 = build_decision_state(
        identity=identity,
        tool_name="restart_service",
        arguments=args,
        environment="production",
        request_id=rid,
        approvals=approvals,
    )
    r1 = pipeline.decide(state1)
    assert r1.outcome.action == "allow"  # primera vez: ejecuta y consume

    # Segundo intento con el mismo request_id: la aprobación ya fue consumida.
    state2 = build_decision_state(
        identity=identity,
        tool_name="restart_service",
        arguments=args,
        environment="production",
        request_id=rid,
        approvals=approvals,
    )
    r2 = pipeline.decide(state2)
    assert r2.outcome.action == "review"
