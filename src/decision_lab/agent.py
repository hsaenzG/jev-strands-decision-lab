"""Construcción del agente de Strands sobre Amazon Bedrock (modo live).

El modo live requiere `strands-agents` instalado y credenciales de AWS con
acceso a Bedrock. El modo offline NO usa este módulo: demuestra el pipeline con
llamadas de herramienta propuestas de forma determinista (ver cli.py).

Las herramientas que se registran son envoltorios de las simulaciones; aun así,
el hook de decisión las intercepta antes de cualquier efecto. Como las tools son
simuladas, nunca tocan infraestructura real.
"""

from __future__ import annotations

from typing import Any

from .hooks import DecisionGateHook
from .pipeline import DecisionPipeline
from .state import AuthenticatedIdentity
from .tools import inspect_service as _inspect
from .tools import restart_service as _restart

DEFAULT_SYSTEM_PROMPT = (
    "Eres un asistente de operaciones. Puedes inspeccionar el estado de un "
    "servicio y, si corresponde, proponer reiniciarlo. Propón llamadas de "
    "herramienta con argumentos claros: service y environment. No asumas que "
    "tienes autorización: otra capa decide si la acción se ejecuta."
)

# Modelo por defecto de Bedrock. Hazel prefiere Amazon Nova para sus demos.
DEFAULT_BEDROCK_MODEL = "us.amazon.nova-pro-v1:0"


def _build_strands_tools() -> list[Any]:
    """Envuelve las simulaciones como herramientas de Strands con @tool."""
    from strands import tool

    @tool
    def inspect_service(service: str, environment: str) -> str:
        """Consulta el estado de salud de un servicio.

        Args:
            service: nombre del servicio, p. ej. "payments".
            environment: entorno, p. ej. "staging" o "production".
        """
        return _inspect(service, environment).output

    @tool
    def restart_service(service: str, environment: str) -> str:
        """Reinicia un servicio.

        Args:
            service: nombre del servicio, p. ej. "payments".
            environment: entorno, p. ej. "staging" o "production".
        """
        return _restart(service, environment).output

    return [inspect_service, restart_service]


def build_live_agent(
    pipeline: DecisionPipeline,
    *,
    identity: AuthenticatedIdentity,
    environment: str,
    model_id: str = DEFAULT_BEDROCK_MODEL,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> Any:
    """Crea un `Agent` de Strands con el hook de decisión conectado.

    Lanza ImportError con un mensaje claro si falta el SDK.
    """
    try:
        from strands import Agent
        from strands.models import BedrockModel
    except ImportError as exc:  # pragma: no cover - requiere entorno sin SDK
        raise ImportError(
            "El modo live requiere 'strands-agents'. Instala con: uv sync --extra strands"
        ) from exc

    gate = DecisionGateHook(pipeline, identity=identity, environment=environment)
    model = BedrockModel(model_id=model_id)
    agent = Agent(
        model=model,
        tools=_build_strands_tools(),
        hooks=[gate],
        system_prompt=system_prompt,
    )
    # Exponemos el gate para inspeccionar las decisiones tras una invocación.
    agent.decision_gate = gate  # type: ignore[attr-defined]
    return agent
