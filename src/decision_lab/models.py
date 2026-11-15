"""Tipos del dominio para la capa de decisiones.

Estos tipos son el *contrato interno* del laboratorio. A propósito son
independientes del formato de red de Jev (o de cualquier proveedor): el agente,
el motor de políticas y la telemetría solo hablan este lenguaje. El adaptador de
proveedor traduce entre el mundo externo y estos tipos.

Regla central del proyecto: **razonar no es autorizar**. El LLM propone, el
proveedor (Jev) emite una señal consultiva, y el motor de políticas determinista
tiene la última palabra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Rutas que un proveedor de decisiones puede sugerir. Son señales *consultivas*:
# nunca autorizan por sí solas.
SuggestedRoute = Literal["execute", "review", "reject"]

# Acción final que emite el motor de políticas determinista.
PolicyAction = Literal["allow", "review", "deny"]


@dataclass(frozen=True)
class DecisionState:
    """Estado de confianza de una decisión.

    Lo construye un componente confiable (el *trusted state builder*) a partir de
    la identidad autenticada y la llamada de herramienta propuesta. Nunca se arma
    a partir de afirmaciones del prompt del usuario: un usuario no puede
    "declararse" admin ni "declarar" que ya tiene una aprobación.
    """

    request_id: str
    tool_name: str
    arguments: dict[str, object]
    environment: str  # p. ej. "staging" | "production"
    actor_role: str  # rol verificado de la identidad autenticada
    approval_granted: bool  # aprobación verificada y vinculada (no una afirmación del prompt)
    # Metadatos opcionales de la aprobación, para validar vínculo exacto.
    approval_request_id: str | None = None
    approval_tool_name: str | None = None
    approval_arguments_hash: str | None = None


@dataclass(frozen=True)
class DecisionSignals:
    """Señal consultiva devuelta por un proveedor de decisiones.

    Modela de forma neutral las primitivas de Jev (Choice/Score/Noul) sin acoplar
    el resto del sistema al SDK de TypeSafe. `suggested_route` viene de un Choice;
    `human_review_score` y `risk_label` son opcionales y solo informativos.
    """

    suggested_route: SuggestedRoute
    human_review_score: float | None  # 0..1, p. ej. confianza o un Noul de riesgo
    risk_label: str | None
    provider: str  # identificador del proveedor + versión de modelo
    confidence: float | None = None  # 0..1, confianza reportada por el proveedor


@dataclass(frozen=True)
class PolicyOutcome:
    """Decisión final y determinista del motor de políticas."""

    action: PolicyAction
    reason_code: str  # código estable y legible, p. ej. "unauthorized_role"
    detail: str = ""  # explicación breve en español para trazas y demo


@dataclass(frozen=True)
class Approval:
    """Aprobación humana explícita, vinculada y de un solo uso.

    Una aprobación válida está atada a un `request_id`, a un nombre exacto de
    herramienta y al hash canónico de los argumentos. Si la acción cambia, la
    aprobación deja de aplicar y se debe re-evaluar.
    """

    request_id: str
    tool_name: str
    arguments_hash: str
    approver: str
    expires_at: float  # epoch segundos


@dataclass
class ExecutionResult:
    """Resultado de ejecutar (simuladamente) una herramienta permitida."""

    executed: bool
    output: str
    reason_code: str = "ok"
    extra: dict[str, object] = field(default_factory=dict)
