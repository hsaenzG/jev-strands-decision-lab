"""Ejecución del pipeline instrumentada por pasos, para visualización.

El frontend de aprendizaje necesita ver *cada etapa* del flujo de decisión con
su entrada y su salida, no solo el resultado final. Este módulo reejecuta la
misma lógica verificada (constructor de estado, proveedor, política, ejecución)
pero registrando una lista de `Step` con lo que entra y sale de cada caja del
diagrama de arquitectura.

No duplica reglas: delega en `evaluate_policy`, el proveedor y `execute_simulated`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .models import DecisionState
from .policy import PolicyConfig, evaluate_policy
from .providers.base import DecisionProvider, ProviderError
from .state import ApprovalStore, AuthenticatedIdentity, build_decision_state
from .telemetry import now_ms
from .tools import execute_simulated

StepStatus = Literal["ok", "warn", "block", "info"]


@dataclass
class Step:
    """Una etapa del flujo, lista para dibujar en el frontend."""

    key: str  # id estable de la etapa (coincide con el nodo del diagrama)
    title: str  # título legible en español
    status: StepStatus
    summary: str  # una línea explicando qué pasó
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepRun:
    """Resultado completo de una corrida instrumentada."""

    scenario_id: str
    final_action: str
    reason_code: str
    executed: bool
    latency_ms: float
    steps: list[Step]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "final_action": self.final_action,
            "reason_code": self.reason_code,
            "executed": self.executed,
            "latency_ms": round(self.latency_ms, 3),
            "steps": [asdict(s) for s in self.steps],
        }


def run_with_steps(
    *,
    scenario_id: str,
    identity: AuthenticatedIdentity,
    tool_name: str,
    arguments: dict[str, object],
    environment: str,
    provider: DecisionProvider,
    approvals: ApprovalStore | None = None,
    request_id: str | None = None,
    config: PolicyConfig | None = None,
    prompt_text: str | None = None,
) -> StepRun:
    """Corre el pipeline y devuelve cada etapa con su entrada/salida."""
    cfg = config or PolicyConfig()
    steps: list[Step] = []
    start = now_ms()

    # Etapa 0: el modelo razona (inicio del ciclo agéntico de Strands).
    steps.append(
        Step(
            key="model",
            title="0. El modelo razona (Bedrock / Nova)",
            status="info",
            summary=(
                "El modelo recibe el prompt y el historial, razona y decide "
                "llamar una herramienta. Aquí empieza el ciclo agéntico."
                + (f" Prompt: «{prompt_text}»" if prompt_text else "")
            ),
            data={"loop": "agentic", "model_decides_tool_call": True},
        )
    )

    # Etapa 1: el agente propone una llamada de herramienta.
    steps.append(
        Step(
            key="propose",
            title="1. El agente propone una herramienta",
            status="info",
            summary=(f"El modelo propone '{tool_name}' en '{environment}'."),
            data={"tool_name": tool_name, "arguments": arguments, "environment": environment},
        )
    )

    # Etapa 2: el hook intercepta antes de cualquier efecto.
    steps.append(
        Step(
            key="hook",
            title="2. El hook BeforeToolCallEvent intercepta",
            status="info",
            summary="Se captura la llamada propuesta antes de ejecutarla.",
            data={"event": "BeforeToolCallEvent", "intercepted": True},
        )
    )

    # Etapa 3: se construye el estado confiable (el prompt NO decide el rol).
    state: DecisionState = build_decision_state(
        identity=identity,
        tool_name=tool_name,
        arguments=arguments,
        environment=environment,
        request_id=request_id,
        approvals=approvals,
    )
    prompt_claims_authority = bool(
        prompt_text and any(w in prompt_text.lower() for w in ("admin", "autoriz", "root"))
    )
    steps.append(
        Step(
            key="state",
            title="3. Constructor de estado confiable",
            status="warn" if prompt_claims_authority else "ok",
            summary=(
                f"Rol confiable: '{identity.role}' (de la identidad autenticada, "
                "no del prompt). Aprobación vinculada: "
                f"{'sí' if state.approval_granted else 'no'}."
                + (
                    " El prompt afirma tener autoridad; se ignora."
                    if prompt_claims_authority
                    else ""
                )
            ),
            data={
                "request_id": state.request_id,
                "actor_role": state.actor_role,
                "approval_granted": state.approval_granted,
                "prompt_authority_claim_ignored": prompt_claims_authority,
            },
        )
    )

    # Etapa 4: el proveedor (Jev/mock) evalúa. Fallo -> fail-closed.
    signals = None
    provider_failed = False
    try:
        signals = provider.evaluate(state)
    except ProviderError as exc:
        provider_failed = True
        steps.append(
            Step(
                key="provider",
                title="4. Jev evalúa (adaptador de decisión)",
                status="block",
                summary=f"El proveedor falló ({exc.reason_code}). Fail-closed.",
                data={"provider": provider.name, "error": exc.reason_code},
            )
        )
    if not provider_failed and signals is not None:
        steps.append(
            Step(
                key="provider",
                title="4. Jev evalúa (adaptador de decisión)",
                status="ok" if signals.suggested_route == "execute" else "warn",
                summary=(
                    f"Señal consultiva: ruta '{signals.suggested_route}', "
                    f"riesgo {signals.human_review_score}. No autoriza por sí sola."
                ),
                data={
                    "provider": signals.provider,
                    "suggested_route": signals.suggested_route,
                    "human_review_score": signals.human_review_score,
                    "risk_label": signals.risk_label,
                    "confidence": signals.confidence,
                },
            )
        )

    # Etapa 5: el motor de políticas decide (única autoridad).
    outcome = evaluate_policy(state, signals, cfg)
    policy_status_map: dict[str, StepStatus] = {
        "allow": "ok",
        "review": "warn",
        "deny": "block",
    }
    policy_status: StepStatus = policy_status_map[outcome.action]
    steps.append(
        Step(
            key="policy",
            title="5. Motor de políticas determinista",
            status=policy_status,
            summary=f"Decisión: {outcome.action.upper()} [{outcome.reason_code}]. {outcome.detail}",
            data={
                "action": outcome.action,
                "reason_code": outcome.reason_code,
                "detail": outcome.detail,
            },
        )
    )

    # Etapa 6: ejecución simulada solo si allow; si no, review o deny.
    # En todos los casos, el resultado VUELVE al modelo (cierre del ciclo).
    execution = None
    if outcome.action == "allow":
        execution = execute_simulated(tool_name, arguments)
        if approvals is not None and state.approval_granted:
            approvals.consume(state.request_id)
        steps.append(
            Step(
                key="execute",
                title="6. Ejecución → el resultado vuelve al modelo",
                status="ok",
                summary=(
                    execution.output + "  → el resultado vuelve al modelo para la siguiente ronda."
                ),
                data={"executed": True, "output": execution.output, "returns_to_model": True},
            )
        )
    elif outcome.action == "review":
        steps.append(
            Step(
                key="review",
                title="6. Aprobación humana → vuelve al modelo",
                status="warn",
                summary=(
                    "La acción espera una aprobación humana vinculada. No se "
                    "ejecuta; el mensaje de bloqueo vuelve al modelo."
                ),
                data={"executed": False, "waiting_approval": True, "returns_to_model": True},
            )
        )
    else:
        steps.append(
            Step(
                key="deny",
                title="6. Cancelada → vuelve al modelo",
                status="block",
                summary="La política canceló la herramienta. No hubo efecto.",
                data={"executed": False},
            )
        )

    latency_ms = now_ms() - start
    return StepRun(
        scenario_id=scenario_id,
        final_action=outcome.action,
        reason_code=outcome.reason_code,
        executed=bool(execution and execution.executed),
        latency_ms=latency_ms,
        steps=steps,
    )
