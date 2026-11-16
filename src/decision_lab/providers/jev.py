"""Proveedor de decisiones real sobre Jev (TypeSafe AI).

Este adaptador solo se activa si hay una `TYPESAFE_API_KEY` en el entorno. En su
ausencia, el laboratorio usa `MockJevProvider` y la demo corre completa sin red.

Contrato verificado (ver docs/references.md):
  - SDK oficial en PyPI: `typesafe-sdk` (org `typesafe-ai`), Python >= 3.10.
  - Cliente: `TypeSafeClient().system_one(state=..., questions={...})`.
  - Primitivas: `Choice`, `Score`, `Noul`. Respuestas con `.choice`,
    `.confidence`, `.probabilities`, `.noul`, `.score`.
  - Variable de entorno de auth: `TYPESAFE_API_KEY`.

Decisión de diseño: Jev NO autoriza. Hacemos una pregunta `Choice` para obtener
una ruta sugerida (execute/review/reject) y un `Noul` para un score de riesgo.
El motor de políticas determinista sigue teniendo la última palabra.

Nota de redacción (threat model): antes de enviar `state` a un tercero, redacta
secretos y datos personales. Aquí solo enviamos metadatos operativos (nombre de
herramienta, servicio, entorno), nunca credenciales.
"""

from __future__ import annotations

import os
from typing import Any

from ..models import DecisionSignals, DecisionState
from .base import ProviderError, ProviderSchemaError, ProviderTimeout

# Import opcional del SDK a nivel de módulo. El paquete es una dependencia
# opcional (extra [jev]); si no está, el adaptador real no se puede usar, pero el
# resto del laboratorio (mock) sigue funcionando.
try:
    from typesafe_sdk import (
        Choice,
        Noul,
        TypeSafeAPIResponseValidationError,
        TypeSafeAPITimeoutError,
        TypeSafeClient,
        TypeSafeError,
    )

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - entorno sin el extra [jev]
    _SDK_AVAILABLE = False

# Pregunta Choice que mapea 1:1 con nuestras rutas internas.
_ROUTE_CRITERIA = {
    "execute": "La acción operativa propuesta es segura y rutinaria; ejecutar.",
    "review": "La acción es sensible o ambigua; requiere revisión humana.",
    "reject": "La acción es peligrosa o claramente fuera de política; rechazar.",
}


def jev_available() -> bool:
    """¿Hay credenciales para intentar el proveedor real?"""
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def _redacted_state_payload(state: DecisionState) -> dict[str, Any]:
    """Construye el `state` que se envía a Jev, solo con metadatos operativos."""
    return {
        "tool_name": state.tool_name,
        "environment": state.environment,
        "actor_role": state.actor_role,
        # Argumentos operativos; en un sistema real, redacta aquí cualquier PII.
        "arguments": {k: str(v) for k, v in state.arguments.items()},
    }


class RealJevProvider:
    """Adaptador del SDK oficial de TypeSafe AI (Jev)."""

    name = "jev-typesafe"

    def __init__(self, *, model: str = "jev-latest", timeout: float = 10.0) -> None:
        if not _SDK_AVAILABLE:
            raise ProviderError(
                "falta el paquete 'typesafe-sdk'; instala con el extra [jev]",
                reason_code="provider_sdk_missing",
            )
        if not jev_available():
            raise ProviderError(
                "TYPESAFE_API_KEY no está configurada; usa el proveedor mock",
                reason_code="provider_not_configured",
            )
        self.model = model
        self.timeout = timeout

    def evaluate(self, state: DecisionState) -> DecisionSignals:
        questions: dict[str, Any] = {
            "route": Choice(
                instructions=(
                    "Dada esta acción operativa propuesta por un agente, "
                    "¿cuál es la ruta más prudente?"
                ),
                criteria=_ROUTE_CRITERIA,
            ),
            "risk": Noul(
                instructions=(
                    "¿Esta acción conlleva un riesgo operativo alto que justifique "
                    "revisión humana?"
                ),
            ),
        }

        try:
            with TypeSafeClient() as client:
                response = client.system_one(
                    state=_redacted_state_payload(state),
                    questions=questions,
                    model=self.model,
                )
        except TypeSafeAPITimeoutError as exc:
            raise ProviderTimeout(str(exc)) from exc
        except TypeSafeAPIResponseValidationError as exc:
            raise ProviderSchemaError(str(exc)) from exc
        except TypeSafeError as exc:
            raise ProviderError(str(exc), reason_code="provider_api_error") from exc
        except Exception as exc:  # red u otros errores inesperados -> fail-closed
            raise ProviderError(
                f"error inesperado del proveedor: {exc}",
                reason_code="provider_unexpected",
            ) from exc

        return self._parse(response)

    def _parse(self, response: Any) -> DecisionSignals:
        """Traduce la respuesta del SDK a nuestra señal interna.

        Se programa de forma defensiva: cualquier forma inesperada se trata como
        error de esquema (fail-closed), nunca como un 'execute' silencioso.
        """
        try:
            route_answer = response.choices["route"]
            route = route_answer.choice
            confidence = getattr(route_answer, "confidence", None)
            risk_answer = response.nouls["risk"]
            risk = float(risk_answer.noul)
            model_used = getattr(response, "model", self.model)
        except Exception as exc:
            raise ProviderSchemaError(
                f"no se pudo interpretar la respuesta de Jev: {exc}"
            ) from exc

        if route not in _ROUTE_CRITERIA:
            raise ProviderSchemaError(f"ruta desconocida devuelta por Jev: {route!r}")

        return DecisionSignals(
            suggested_route=route,
            human_review_score=risk,
            risk_label=f"jev-risk={risk:.2f}",
            provider=f"jev-typesafe/{model_used}",
            confidence=confidence,
        )
