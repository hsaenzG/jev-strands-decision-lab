"""Pipeline de decisión, independiente de Strands.

Reúne los pasos: construir estado -> consultar proveedor -> aplicar política ->
(si allow) ejecutar herramienta simulada -> registrar traza. Es lógica pura y
testeable sin el SDK de Strands ni red.

Este pipeline es también lo que usa el hook de Strands: el hook solo traduce el
evento del SDK a una llamada a `decide` y aplica el resultado al evento.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DecisionSignals, DecisionState, ExecutionResult, PolicyOutcome
from .policy import PolicyConfig, evaluate_policy
from .providers.base import DecisionProvider, ProviderError
from .state import ApprovalStore
from .telemetry import JsonlTracer, TraceRecord, now_ms
from .tools import execute_simulated


@dataclass
class DecisionResult:
    """Resultado completo de una decisión, para la demo, la CLI y los tests."""

    state: DecisionState
    signals: DecisionSignals | None
    outcome: PolicyOutcome
    execution: ExecutionResult | None
    trace: TraceRecord


class DecisionPipeline:
    """Orquesta proveedor + política + ejecución simulada + traza."""

    def __init__(
        self,
        provider: DecisionProvider,
        *,
        config: PolicyConfig | None = None,
        tracer: JsonlTracer | None = None,
        approvals: ApprovalStore | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or PolicyConfig()
        self.tracer = tracer or JsonlTracer()
        self.approvals = approvals

    def decide(self, state: DecisionState) -> DecisionResult:
        """Evalúa una acción propuesta y la ejecuta solo si la política lo permite."""
        start = now_ms()

        # 1. Consultar al proveedor. Un fallo -> señal None -> fail-closed en política.
        signals: DecisionSignals | None
        try:
            signals = self.provider.evaluate(state)
        except ProviderError:
            signals = None

        # 2. Aplicar la política determinista (única autoridad para autorizar).
        outcome = evaluate_policy(state, signals, self.config)

        # 3. Ejecutar solo si la acción es 'allow'.
        execution: ExecutionResult | None = None
        if outcome.action == "allow":
            execution = execute_simulated(state.tool_name, state.arguments)
            # Si la aprobación habilitó la ejecución, consúmela (no-replay).
            if self.approvals is not None and state.approval_granted:
                self.approvals.consume(state.request_id)

        latency_ms = now_ms() - start

        # 4. Registrar la traza.
        trace = self.tracer.record(
            state=state,
            signals=signals,
            outcome=outcome,
            result=execution,
            latency_ms=latency_ms,
        )

        return DecisionResult(
            state=state,
            signals=signals,
            outcome=outcome,
            execution=execution,
            trace=trace,
        )
