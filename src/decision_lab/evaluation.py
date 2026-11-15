"""Carga y evaluación de escenarios etiquetados.

Permite correr el dataset de `examples/scenarios.json` contra el pipeline y
comparar la acción esperada con la obtenida. Reporta métricas honestas:
exactitud por etiqueta, tasa de 'unsafe allow' (una ejecución donde se esperaba
review/deny) y latencia P50/P95 del motor local.

Las latencias son del pipeline LOCAL (política + mock), no de Jev real. No se
inventan números de red.
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pipeline import DecisionPipeline
from .providers.mock import MockJevProvider
from .state import ApprovalStore, AuthenticatedIdentity, build_decision_state
from .telemetry import JsonlTracer


@dataclass
class ScenarioOutcome:
    scenario_id: str
    expected: str
    actual: str
    passed: bool
    reason_code: str
    latency_ms: float


def load_scenarios(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data["scenarios"])


def _provider_for(scenario: dict[str, Any]) -> MockJevProvider:
    cfg = scenario.get("provider") or {}
    return MockJevProvider(
        fail_mode=cfg.get("fail_mode"),
        suggest_execute_always=bool(cfg.get("suggest_execute_always", False)),
    )


def _apply_approval(
    scenario: dict[str, Any],
    approvals: ApprovalStore,
    request_id: str,
) -> None:
    """Prepara el ApprovalStore según el tipo de aprobación del escenario."""
    kind = scenario.get("approval")
    if kind is None:
        return
    args = scenario["arguments"]
    if kind == "matching":
        approvals.grant(
            request_id=request_id,
            tool_name=scenario["tool"],
            arguments=args,
            approver="oncall-lead",
        )
    elif kind == "wrong_arguments":
        approvals.grant(
            request_id=request_id,
            tool_name=scenario["tool"],
            arguments={**args, "service": "otro-servicio"},
            approver="oncall-lead",
        )
    elif kind == "expired":
        approvals.grant(
            request_id=request_id,
            tool_name=scenario["tool"],
            arguments=args,
            approver="oncall-lead",
            ttl_seconds=-1.0,
        )
    elif kind == "consumed":
        approvals.grant(
            request_id=request_id,
            tool_name=scenario["tool"],
            arguments=args,
            approver="oncall-lead",
        )
        approvals.consume(request_id)


def run_scenario(scenario: dict[str, Any]) -> ScenarioOutcome:
    """Corre un escenario individual y devuelve su resultado comparado."""
    approvals = ApprovalStore()
    identity = AuthenticatedIdentity(actor_id="demo-user", role=scenario["role"])
    # Traza a un buffer para no contaminar la salida de evaluación.
    tracer = JsonlTracer(stream=io.StringIO())
    pipeline = DecisionPipeline(_provider_for(scenario), tracer=tracer, approvals=approvals)

    # Construimos el estado con un request_id fijo para poder vincular aprobación.
    request_id = f"eval_{scenario['id']}"
    _apply_approval(scenario, approvals, request_id)

    state = build_decision_state(
        identity=identity,
        tool_name=scenario["tool"],
        arguments=scenario["arguments"],
        environment=scenario["environment"],
        request_id=request_id,
        approvals=approvals,
    )

    start = time.perf_counter()
    result = pipeline.decide(state)
    latency_ms = (time.perf_counter() - start) * 1000.0

    actual = result.outcome.action
    expected = scenario["expected"]
    return ScenarioOutcome(
        scenario_id=scenario["id"],
        expected=expected,
        actual=actual,
        passed=actual == expected,
        reason_code=result.outcome.reason_code,
        latency_ms=latency_ms,
    )


@dataclass
class EvaluationReport:
    outcomes: list[ScenarioOutcome]

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def unsafe_allows(self) -> list[ScenarioOutcome]:
        """Casos donde se obtuvo 'allow' pero se esperaba review o deny."""
        return [
            o for o in self.outcomes if o.actual == "allow" and o.expected in ("review", "deny")
        ]

    def latency_percentile(self, pct: float) -> float:
        if not self.outcomes:
            return 0.0
        values = sorted(o.latency_ms for o in self.outcomes)
        k = max(0, min(len(values) - 1, int(round((pct / 100.0) * (len(values) - 1)))))
        return values[k]


def evaluate_scenarios(path: str | Path) -> EvaluationReport:
    outcomes = [run_scenario(s) for s in load_scenarios(path)]
    return EvaluationReport(outcomes=outcomes)
