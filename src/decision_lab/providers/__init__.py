"""Proveedores de decisiones: interfaz, mock determinista y adaptador real de Jev."""

from __future__ import annotations

from .base import (
    DecisionProvider,
    ProviderError,
    ProviderSchemaError,
    ProviderTimeout,
)
from .mock import MockJevProvider

__all__ = [
    "DecisionProvider",
    "ProviderError",
    "ProviderSchemaError",
    "ProviderTimeout",
    "MockJevProvider",
    "get_default_provider",
]


def get_default_provider() -> DecisionProvider:
    """Devuelve el proveedor real si hay credenciales, o el mock en caso contrario."""
    from .jev import RealJevProvider, jev_available

    if jev_available():
        try:
            return RealJevProvider()
        except ProviderError:
            # Si el SDK no está instalado o falla la configuración, caemos al mock.
            return MockJevProvider()
    return MockJevProvider()
