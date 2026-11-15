"""Constructor de estado confiable y utilidades de aprobación.

Este módulo materializa una de las fronteras de confianza más importantes del
laboratorio: el prompt del usuario es *entrada no confiable*. La identidad, el
rol y las aprobaciones provienen del contexto autenticado de la aplicación,
nunca de lo que diga el texto del usuario.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass

from .models import Approval, DecisionState


def new_request_id() -> str:
    """Genera un identificador de solicitud único y rastreable."""
    return f"req_{uuid.uuid4().hex[:12]}"


def canonical_arguments_hash(arguments: dict[str, object]) -> str:
    """Hash canónico y estable de los argumentos de una herramienta.

    Serializa con claves ordenadas y separadores compactos para que dos llamadas
    con los mismos argumentos (en cualquier orden) produzcan el mismo hash. Esto
    es lo que permite vincular una aprobación a *exactamente* una acción.
    """
    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Identidad ya autenticada por la aplicación (fuera de este laboratorio)."""

    actor_id: str
    role: str  # p. ej. "operator", "developer", "viewer"


class ApprovalStore:
    """Almacén en memoria de aprobaciones de un solo uso.

    En producción esto sería un recurso durable (DynamoDB, Step Functions, etc.).
    Aquí es suficiente para demostrar vínculo exacto, expiración y no-replay.
    """

    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}
        self._consumed: set[str] = set()

    def grant(
        self,
        *,
        request_id: str,
        tool_name: str,
        arguments: dict[str, object],
        approver: str,
        ttl_seconds: float = 300.0,
    ) -> Approval:
        """Registra una aprobación vinculada a una acción canónica."""
        approval = Approval(
            request_id=request_id,
            tool_name=tool_name,
            arguments_hash=canonical_arguments_hash(arguments),
            approver=approver,
            expires_at=time.time() + ttl_seconds,
        )
        self._approvals[request_id] = approval
        return approval

    def is_valid_for(
        self,
        *,
        request_id: str,
        tool_name: str,
        arguments: dict[str, object],
        now: float | None = None,
    ) -> bool:
        """¿Existe una aprobación válida, no expirada, no usada y con vínculo exacto?"""
        now = time.time() if now is None else now
        approval = self._approvals.get(request_id)
        if approval is None:
            return False
        if request_id in self._consumed:
            return False
        if approval.expires_at < now:
            return False
        if approval.tool_name != tool_name:
            return False
        if approval.arguments_hash != canonical_arguments_hash(arguments):
            return False
        return True

    def consume(self, request_id: str) -> None:
        """Marca una aprobación como usada para impedir replay."""
        self._consumed.add(request_id)


def build_decision_state(
    *,
    identity: AuthenticatedIdentity,
    tool_name: str,
    arguments: dict[str, object],
    environment: str,
    request_id: str | None = None,
    approvals: ApprovalStore | None = None,
) -> DecisionState:
    """Arma el `DecisionState` combinando identidad confiable + acción propuesta.

    El rol proviene de `identity` (autenticada), jamás del prompt. La bandera
    `approval_granted` se calcula contra el `ApprovalStore`, nunca se acepta como
    dato de entrada del modelo o del usuario.
    """
    rid = request_id or new_request_id()
    approval_granted = False
    if approvals is not None:
        approval_granted = approvals.is_valid_for(
            request_id=rid,
            tool_name=tool_name,
            arguments=arguments,
        )
    return DecisionState(
        request_id=rid,
        tool_name=tool_name,
        arguments=dict(arguments),
        environment=environment,
        actor_role=identity.role,
        approval_granted=approval_granted,
        approval_request_id=rid if approval_granted else None,
        approval_tool_name=tool_name if approval_granted else None,
        approval_arguments_hash=(canonical_arguments_hash(arguments) if approval_granted else None),
    )
