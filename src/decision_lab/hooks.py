"""Integración con Strands: intercepción de herramientas con BeforeToolCallEvent.

Patrón verificado contra la documentación oficial de Strands Agents (ver
docs/references.md):

  - Se implementa el protocolo `HookProvider` con `register_hooks(registry)`.
  - Se suscribe a `BeforeToolCallEvent` con `registry.add_callback(...)`.
  - Se lee el nombre y los argumentos propuestos con `event.tool_use["name"]`
    y `event.tool_use["input"]`.
  - Para bloquear una herramienta antes de cualquier efecto secundario se asigna
    `event.cancel_tool = "<mensaje>"`.

Semántica importante (de 01 - Architecture): cancelar una herramienta NO es lo
mismo que un flujo durable de aprobación. Cuando la política devuelve `review`,
el hook cancela la ejecución con un mensaje que explica que se requiere
aprobación humana; el laboratorio modela la aprobación como estado explícito
(ApprovalStore), no como "pausa mágica" del agente.

El import de Strands es perezoso: este módulo se puede importar en modo offline
sin tener el SDK instalado. Solo se necesita Strands cuando se corre el agente
real contra Bedrock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .pipeline import DecisionPipeline
from .state import AuthenticatedIdentity, build_decision_state

if TYPE_CHECKING:  # solo para type-checking; no se importa en runtime offline
    from strands.hooks import BeforeToolCallEvent, HookRegistry


class DecisionGateHook:
    """HookProvider que aplica la capa de decisiones a cada herramienta propuesta.

    Implementa el protocolo `HookProvider` de Strands por composición: expone
    `register_hooks(registry)`, que es lo único que el SDK necesita.
    """

    def __init__(
        self,
        pipeline: DecisionPipeline,
        *,
        identity: AuthenticatedIdentity,
        environment: str,
    ) -> None:
        self.pipeline = pipeline
        self.identity = identity
        self.environment = environment
        # Resultados de las decisiones de esta invocación, para inspección en demo.
        self.decisions: list[Any] = []

    def register_hooks(self, registry: HookRegistry) -> None:
        """Suscribe el callback de intercepción al evento BeforeToolCallEvent."""
        from strands.hooks import BeforeToolCallEvent

        registry.add_callback(BeforeToolCallEvent, self.intercept_tool)

    def intercept_tool(self, event: BeforeToolCallEvent) -> None:
        """Evalúa la herramienta propuesta antes de ejecutarla.

        La identidad y el entorno vienen del contexto confiable del hook, no del
        prompt. El motor de políticas decide; si no es `allow`, se cancela la
        herramienta con `event.cancel_tool`.
        """
        tool_use = event.tool_use
        tool_name = tool_use["name"]
        arguments = dict(tool_use.get("input", {}) or {})

        state = build_decision_state(
            identity=self.identity,
            tool_name=tool_name,
            arguments=arguments,
            environment=self.environment,
            approvals=self.pipeline.approvals,
        )
        result = self.pipeline.decide(state)
        self.decisions.append(result)

        if result.outcome.action != "allow":
            # Bloqueamos la ejecución real de la herramienta del agente. El
            # pipeline NO ejecutó la simulación en este caso (solo ejecuta en
            # allow), así que no hay efecto secundario.
            prefix = {
                "deny": "DENEGADO",
                "review": "REQUIERE APROBACIÓN HUMANA",
            }.get(result.outcome.action, "BLOQUEADO")
            event.cancel_tool = f"{prefix} [{result.outcome.reason_code}]: {result.outcome.detail}"
