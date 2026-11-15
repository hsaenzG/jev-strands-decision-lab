"""Motor de políticas determinista.

Este es el único componente con autoridad para autorizar. Recibe el estado de
confianza y la señal consultiva del proveedor, y aplica reglas deterministas en
orden. La señal de Jev puede *restringir* (pedir review o deny), pero jamás
*ampliar* lo que las reglas permiten.

Orden de evaluación (de 02 - Decision Policies and States):
  1. Herramienta desconocida o argumentos inválidos -> deny.
  2. Actor sin rol de confianza -> deny.
  3. Rol insuficiente para la herramienta -> deny.
  4. Fallo del proveedor (timeout/schema/señal desconocida) -> deny (fail-closed).
  5. El proveedor recomienda reject -> deny.
  6. Reinicio en producción sin aprobación válida -> review (nunca execute).
  7. El proveedor recomienda review (o supera umbral de riesgo) -> review.
  8. En caso contrario -> allow solo si permiso y entorno lo permiten.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DecisionSignals, DecisionState, PolicyOutcome

# --- Configuración determinista de autorización -----------------------------

# Qué roles pueden invocar cada herramienta. Allowlist explícita: lo que no está
# listado, se niega.
DEFAULT_TOOL_ROLES: dict[str, frozenset[str]] = {
    "inspect_service": frozenset({"viewer", "developer", "operator"}),
    "restart_service": frozenset({"operator"}),
}

# Herramientas que la aplicación conoce. Cualquier otra -> deny.
DEFAULT_TOOL_ALLOWLIST: frozenset[str] = frozenset(DEFAULT_TOOL_ROLES)

# Esquema mínimo esperado por herramienta: nombre de argumento -> tipo requerido.
DEFAULT_TOOL_SCHEMAS: dict[str, dict[str, type]] = {
    "inspect_service": {"service": str, "environment": str},
    "restart_service": {"service": str, "environment": str},
}

# Herramientas destructivas que exigen aprobación humana cuando el entorno es
# sensible (producción).
WRITE_TOOLS: frozenset[str] = frozenset({"restart_service"})
SENSITIVE_ENVIRONMENTS: frozenset[str] = frozenset({"production", "prod"})


@dataclass(frozen=True)
class PolicyConfig:
    """Configuración inyectable del motor de políticas."""

    tool_roles: dict[str, frozenset[str]] = field(default_factory=lambda: dict(DEFAULT_TOOL_ROLES))
    tool_allowlist: frozenset[str] = DEFAULT_TOOL_ALLOWLIST
    tool_schemas: dict[str, dict[str, type]] = field(
        default_factory=lambda: dict(DEFAULT_TOOL_SCHEMAS)
    )
    write_tools: frozenset[str] = WRITE_TOOLS
    sensitive_environments: frozenset[str] = SENSITIVE_ENVIRONMENTS
    # Umbral de riesgo: si el proveedor reporta un human_review_score por encima
    # de esto, se fuerza review aunque sugiera execute.
    review_risk_threshold: float = 0.5


def _validate_schema(state: DecisionState, schema: dict[str, type]) -> str | None:
    """Devuelve un detalle de error si el esquema no se cumple, o None si es válido."""
    for name, expected in schema.items():
        if name not in state.arguments:
            return f"falta el argumento requerido '{name}'"
        value = state.arguments[name]
        if not isinstance(value, expected):
            return (
                f"el argumento '{name}' debe ser {expected.__name__}, "
                f"se recibió {type(value).__name__}"
            )
    return None


def evaluate_policy(
    state: DecisionState,
    signals: DecisionSignals | None,
    config: PolicyConfig | None = None,
) -> PolicyOutcome:
    """Aplica las reglas deterministas y devuelve la decisión final.

    `signals` es `None` cuando el proveedor falló (timeout, respuesta malformada,
    sin credenciales en modo que exige proveedor). Ese caso es *fail-closed*.
    """
    cfg = config or PolicyConfig()

    # Regla 1a: herramienta desconocida.
    if state.tool_name not in cfg.tool_allowlist:
        return PolicyOutcome(
            action="deny",
            reason_code="unknown_tool",
            detail=f"la herramienta '{state.tool_name}' no está en la allowlist",
        )

    # Regla 1b: argumentos inválidos contra el esquema.
    schema = cfg.tool_schemas.get(state.tool_name, {})
    schema_error = _validate_schema(state, schema)
    if schema_error is not None:
        return PolicyOutcome(
            action="deny",
            reason_code="invalid_arguments",
            detail=schema_error,
        )

    # Regla 2: actor sin rol de confianza.
    if not state.actor_role:
        return PolicyOutcome(
            action="deny",
            reason_code="unauthenticated_actor",
            detail="no hay un rol de confianza en el estado",
        )

    # Regla 3: rol insuficiente para la herramienta.
    allowed_roles = cfg.tool_roles.get(state.tool_name, frozenset())
    if state.actor_role not in allowed_roles:
        return PolicyOutcome(
            action="deny",
            reason_code="unauthorized_role",
            detail=(f"el rol '{state.actor_role}' no puede invocar '{state.tool_name}'"),
        )

    # Regla 4: fallo del proveedor -> fail-closed.
    if signals is None:
        return PolicyOutcome(
            action="deny",
            reason_code="provider_unavailable",
            detail="el proveedor de decisiones no entregó una señal válida; fail-closed",
        )

    # Regla 5: el proveedor recomienda rechazar.
    if signals.suggested_route == "reject":
        return PolicyOutcome(
            action="deny",
            reason_code="provider_reject",
            detail="el proveedor recomendó rechazar la acción",
        )

    # Regla 6: escritura en entorno sensible sin aprobación válida -> review.
    #   Esta regla domina sobre cualquier 'execute' que sugiera el proveedor.
    is_write = state.tool_name in cfg.write_tools
    is_sensitive = state.environment in cfg.sensitive_environments
    if is_write and is_sensitive and not state.approval_granted:
        return PolicyOutcome(
            action="review",
            reason_code="production_requires_approval",
            detail=(
                "acción de escritura en entorno sensible: requiere aprobación "
                "humana vinculada antes de ejecutar"
            ),
        )

    # Una aprobación humana válida y vinculada (verificada en la regla 6 contra el
    # ApprovalStore) ES la revisión humana para esta acción exacta. Por eso puede
    # satisfacer un 'review' consultivo del proveedor o un riesgo alto, pero nunca
    # un 'reject' (regla 5) ni un rol insuficiente (regla 3), que ya se evaluaron.
    human_already_reviewed = state.approval_granted

    # Regla 7: el proveedor pide review, o el riesgo supera el umbral.
    if signals.suggested_route == "review" and not human_already_reviewed:
        return PolicyOutcome(
            action="review",
            reason_code="provider_review",
            detail="el proveedor recomendó revisión humana",
        )
    if (
        not human_already_reviewed
        and signals.human_review_score is not None
        and signals.human_review_score >= cfg.review_risk_threshold
    ):
        return PolicyOutcome(
            action="review",
            reason_code="risk_threshold_exceeded",
            detail=(
                f"riesgo {signals.human_review_score:.2f} >= umbral {cfg.review_risk_threshold:.2f}"
            ),
        )

    # Regla 8: permitir. Todas las comprobaciones deterministas pasaron y el
    # proveedor sugirió execute.
    return PolicyOutcome(
        action="allow",
        reason_code="allow_authorized",
        detail="acción autorizada por rol, entorno y señal consultiva",
    )
