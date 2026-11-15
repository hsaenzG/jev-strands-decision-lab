"""Abstracción del proveedor de decisiones.

Un `DecisionProvider` recibe el estado de confianza y devuelve una señal
*consultiva* (`DecisionSignals`). Nunca autoriza: eso es trabajo del motor de
políticas. Si el proveedor falla, debe señalarlo con `ProviderError`, y la capa
superior lo traduce a fail-closed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import DecisionSignals, DecisionState


class ProviderError(Exception):
    """Fallo al obtener una señal del proveedor (timeout, schema, auth, etc.)."""

    def __init__(self, message: str, *, reason_code: str = "provider_error") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ProviderTimeout(ProviderError):
    """El proveedor no respondió dentro del presupuesto de tiempo."""

    def __init__(self, message: str = "tiempo de espera agotado") -> None:
        super().__init__(message, reason_code="provider_timeout")


class ProviderSchemaError(ProviderError):
    """El proveedor respondió, pero con un cuerpo malformado o inesperado."""

    def __init__(self, message: str = "respuesta malformada del proveedor") -> None:
        super().__init__(message, reason_code="provider_schema_error")


@runtime_checkable
class DecisionProvider(Protocol):
    """Interfaz que todo proveedor de decisiones debe implementar."""

    name: str

    def evaluate(self, state: DecisionState) -> DecisionSignals:
        """Devuelve una señal consultiva o lanza `ProviderError` si falla."""
        ...
