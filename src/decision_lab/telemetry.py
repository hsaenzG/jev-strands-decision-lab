"""Trazas estructuradas en JSONL, con redacción.

Cada decisión produce una línea JSON con: request_id, herramienta, entorno, rol,
ruta sugerida por el proveedor, versión del proveedor, acción de la política,
código de razón, latencia en ms y resultado. Los argumentos se registran de
forma reducida y nunca se registran secretos.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import TextIO

from .models import DecisionSignals, DecisionState, ExecutionResult, PolicyOutcome

# Claves de argumentos cuyo valor nunca debe registrarse en claro.
_SENSITIVE_KEYS = ("password", "token", "secret", "api_key", "authorization")


def _redact_arguments(arguments: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in arguments.items():
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            redacted[key] = "[redactado]"
        else:
            redacted[key] = value
    return redacted


@dataclass
class TraceRecord:
    """Un registro de traza de una decisión completa."""

    request_id: str
    tool_name: str
    environment: str
    actor_role: str
    suggested_route: str | None
    provider: str | None
    policy_action: str
    reason_code: str
    latency_ms: float
    executed: bool
    arguments: dict[str, object] = field(default_factory=dict)
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "request_id": self.request_id,
                "tool_name": self.tool_name,
                "environment": self.environment,
                "actor_role": self.actor_role,
                "suggested_route": self.suggested_route,
                "provider": self.provider,
                "policy_action": self.policy_action,
                "reason_code": self.reason_code,
                "latency_ms": round(self.latency_ms, 2),
                "executed": self.executed,
                "arguments": self.arguments,
                "detail": self.detail,
            },
            ensure_ascii=False,
        )


class JsonlTracer:
    """Escribe registros de traza, uno por línea, a un stream (por defecto stdout)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def record(
        self,
        *,
        state: DecisionState,
        signals: DecisionSignals | None,
        outcome: PolicyOutcome,
        result: ExecutionResult | None,
        latency_ms: float,
    ) -> TraceRecord:
        rec = TraceRecord(
            request_id=state.request_id,
            tool_name=state.tool_name,
            environment=state.environment,
            actor_role=state.actor_role,
            suggested_route=signals.suggested_route if signals else None,
            provider=signals.provider if signals else None,
            policy_action=outcome.action,
            reason_code=outcome.reason_code,
            latency_ms=latency_ms,
            executed=bool(result and result.executed),
            arguments=_redact_arguments(state.arguments),
            detail=outcome.detail,
        )
        self._stream.write(rec.to_json() + "\n")
        self._stream.flush()
        return rec


def now_ms() -> float:
    """Reloj monótono en milisegundos, para medir latencia de decisión."""
    return time.perf_counter() * 1000.0
