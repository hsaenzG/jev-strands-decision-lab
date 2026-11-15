"""Herramientas simuladas del asistente de operaciones.

NUNCA tocan infraestructura real. Son simulaciones deterministas para la demo:
`inspect_service` devuelve un estado sintético y `restart_service` registra un
reinicio simulado. Esto hace segura la ejecución local y repetible la demo.
"""

from __future__ import annotations

from .models import ExecutionResult

# Estado sintético de servicios para la simulación de inspección.
_FAKE_SERVICE_HEALTH: dict[str, str] = {
    "payments": "degraded",
    "checkout": "healthy",
    "auth": "healthy",
}


def inspect_service(service: str, environment: str) -> ExecutionResult:
    """Consulta (simulada) el estado de salud de un servicio."""
    status = _FAKE_SERVICE_HEALTH.get(service, "unknown")
    return ExecutionResult(
        executed=True,
        output=(f"[simulado] servicio '{service}' en '{environment}': estado={status}"),
        extra={"service": service, "environment": environment, "status": status},
    )


def restart_service(service: str, environment: str) -> ExecutionResult:
    """Reinicia (simuladamente) un servicio. No ejecuta ninguna acción real."""
    return ExecutionResult(
        executed=True,
        output=(f"[simulado] se reinició el servicio '{service}' en '{environment}'"),
        extra={"service": service, "environment": environment, "action": "restart"},
    )


# Registro de herramientas simuladas que el ejecutor puede invocar.
SIMULATED_TOOLS = {
    "inspect_service": inspect_service,
    "restart_service": restart_service,
}


def execute_simulated(tool_name: str, arguments: dict[str, object]) -> ExecutionResult:
    """Invoca una herramienta simulada tras haber sido autorizada por la política."""
    fn = SIMULATED_TOOLS.get(tool_name)
    if fn is None:
        return ExecutionResult(
            executed=False,
            output=f"herramienta simulada desconocida: {tool_name}",
            reason_code="unknown_tool",
        )
    return fn(**arguments)  # type: ignore[arg-type]
