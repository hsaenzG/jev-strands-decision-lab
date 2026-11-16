"""Los tres escenarios guionados de la demo, reutilizables por CLI y servidor.

Cada escenario describe una historia y cómo prepararlo (incluida la aprobación,
para el caso de producción). La función `run_demo_scenario` arma el estado y lo
corre instrumentado por pasos.
"""

from __future__ import annotations

from typing import Any

from .providers.base import DecisionProvider
from .state import ApprovalStore, AuthenticatedIdentity
from .steps import StepRun, run_with_steps

# Catálogo de escenarios. 'approval' indica si se emite una aprobación vinculada
# a la acción antes de correrla (solo el escenario de producción la usa).
DEMO_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "staging_inspect",
        "titulo": "Consultar estado en staging",
        "descripcion": "Un operador consulta la salud del servicio de pagos en staging.",
        "prompt": "¿Cómo está el servicio de pagos en staging?",
        "role": "operator",
        "environment": "staging",
        "tool": "inspect_service",
        "arguments": {"service": "payments", "environment": "staging"},
        "esperado": "allow",
        "approval": False,
    },
    {
        "id": "prod_restart",
        "titulo": "Reiniciar pagos en producción",
        "descripcion": (
            "Un operador pide reiniciar pagos en producción. Requiere aprobación "
            "humana; con la aprobación exacta vinculada, se permite."
        ),
        "prompt": "Reinicia el servicio de pagos en producción.",
        "role": "operator",
        "environment": "production",
        "tool": "restart_service",
        "arguments": {"service": "payments", "environment": "production"},
        "esperado": "review",  # sin aprobación
        "esperado_con_aprobacion": "allow",
        "approval": "optional",  # el frontend decide si aprueba
    },
    {
        "id": "unauthorized_restart",
        "titulo": "Reinicio sin permisos",
        "descripcion": "Un developer sin permiso pide reiniciar checkout en staging.",
        "prompt": "Reinicia checkout en staging.",
        "role": "developer",
        "environment": "staging",
        "tool": "restart_service",
        "arguments": {"service": "checkout", "environment": "staging"},
        "esperado": "deny",
        "approval": False,
    },
]

DEMO_SCENARIOS_BY_ID = {s["id"]: s for s in DEMO_SCENARIOS}


def run_demo_scenario(
    scenario_id: str,
    provider: DecisionProvider,
    *,
    approve: bool = False,
) -> StepRun:
    """Corre un escenario de la demo instrumentado por pasos.

    `approve=True` solo tiene efecto en el escenario de producción: emite una
    aprobación humana vinculada a la acción exacta antes de evaluar.
    """
    scenario = DEMO_SCENARIOS_BY_ID[scenario_id]
    identity = AuthenticatedIdentity(actor_id="demo-user", role=scenario["role"])
    approvals = ApprovalStore()
    request_id = f"demo_{scenario_id}"

    if approve and scenario.get("approval") == "optional":
        approvals.grant(
            request_id=request_id,
            tool_name=scenario["tool"],
            arguments=scenario["arguments"],
            approver="oncall-lead",
        )

    return run_with_steps(
        scenario_id=scenario_id,
        identity=identity,
        tool_name=scenario["tool"],
        arguments=scenario["arguments"],
        environment=scenario["environment"],
        provider=provider,
        approvals=approvals,
        request_id=request_id,
        prompt_text=scenario["prompt"],
    )
