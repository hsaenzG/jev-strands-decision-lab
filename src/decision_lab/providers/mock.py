"""Proveedor de decisiones mock, determinista y sin red.

Reproduce de forma predecible el *comportamiento* de un modelo tipo Jev
(Choice execute/review/reject + un score de riesgo), sin llamar a ningún
servicio externo. Es el proveedor por defecto del laboratorio y permite correr
la demo completa sin credenciales de AWS ni de Jev.

IMPORTANTE: este mock NO es Jev. No reproduce sus probabilidades reales ni su
calibración. Sirve para demostrar el *pipeline de decisión*, no para afirmar
resultados del modelo real.
"""

from __future__ import annotations

from ..models import DecisionSignals, DecisionState
from .base import ProviderError, ProviderSchemaError, ProviderTimeout

# Palabras que simulan una señal de riesgo detectable en los argumentos.
_RISKY_HINTS = ("delete", "drop", "wipe", "force", "prod-payments-core")


class MockJevProvider:
    """Proveedor determinista con reglas transparentes.

    Reglas de simulación (documentadas y reproducibles):
      - Herramienta de solo lectura (inspect_service) -> execute, riesgo bajo.
      - restart_service en staging -> execute, riesgo medio-bajo.
      - restart_service en producción -> review (sugiere ojo humano).
      - Si los argumentos contienen una pista riesgosa -> reject.

    Flags de prueba para forzar fallos del proveedor (para tests de fail-closed):
      - fail_mode="timeout"  -> lanza ProviderTimeout
      - fail_mode="schema"   -> lanza ProviderSchemaError
      - fail_mode="error"    -> lanza ProviderError genérico
      - suggest_execute_always=True -> siempre sugiere execute (para probar que
        la política puede sobreescribir una recomendación insegura).
    """

    name = "mock-jev"

    def __init__(
        self,
        *,
        fail_mode: str | None = None,
        suggest_execute_always: bool = False,
        provider_version: str = "mock-jev/0.1.0",
    ) -> None:
        self.fail_mode = fail_mode
        self.suggest_execute_always = suggest_execute_always
        self.provider_version = provider_version

    def evaluate(self, state: DecisionState) -> DecisionSignals:
        if self.fail_mode == "timeout":
            raise ProviderTimeout()
        if self.fail_mode == "schema":
            raise ProviderSchemaError()
        if self.fail_mode == "error":
            raise ProviderError("fallo simulado del proveedor")

        if self.suggest_execute_always:
            return DecisionSignals(
                suggested_route="execute",
                human_review_score=0.1,
                risk_label="forced-execute",
                provider=self.provider_version,
                confidence=0.99,
            )

        args_text = " ".join(str(v).lower() for v in state.arguments.values())
        if any(hint in args_text for hint in _RISKY_HINTS):
            return DecisionSignals(
                suggested_route="reject",
                human_review_score=0.95,
                risk_label="high-risk-argument",
                provider=self.provider_version,
                confidence=0.9,
            )

        if state.tool_name == "inspect_service":
            return DecisionSignals(
                suggested_route="execute",
                human_review_score=0.05,
                risk_label="read-only",
                provider=self.provider_version,
                confidence=0.97,
            )

        if state.tool_name == "restart_service":
            if state.environment in ("production", "prod"):
                return DecisionSignals(
                    suggested_route="review",
                    human_review_score=0.7,
                    risk_label="prod-write",
                    provider=self.provider_version,
                    confidence=0.8,
                )
            return DecisionSignals(
                suggested_route="execute",
                human_review_score=0.3,
                risk_label="staging-write",
                provider=self.provider_version,
                confidence=0.85,
            )

        # Herramienta no modelada por el mock: señal conservadora de review.
        return DecisionSignals(
            suggested_route="review",
            human_review_score=0.6,
            risk_label="unknown-tool",
            provider=self.provider_version,
            confidence=0.5,
        )
