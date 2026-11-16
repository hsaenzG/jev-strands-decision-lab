"""Puente HTTP entre el frontend (navegador) y el runtime de AgentCore.

El navegador no puede invocar AgentCore directamente (requiere SigV4/IAM). Esta
Lambda, expuesta por una Function URL, recibe la petición del FE, invoca el
runtime de AgentCore con las credenciales del rol de la Lambda, y devuelve la
respuesta con CORS abierto.

Endpoints (sobre la Function URL):
  GET  /api/health      -> estado + proveedor configurado.
  GET  /api/scenarios   -> catálogo de los 3 escenarios (estático).
  POST /api/run         -> invoca el agente real en AgentCore.
       body: {"scenario_id": "...", "approve": bool}

El runtime ejecuta el agente REAL de Strands sobre Bedrock Nova + Jev real.
"""

from __future__ import annotations

import json
import os
import uuid

import boto3

AGENT_ARN = os.environ["AGENT_RUNTIME_ARN"]
REGION = os.environ.get("AWS_REGION", "us-east-2")

_client = boto3.client("bedrock-agentcore", region_name=REGION)

# Catálogo de escenarios (espejo de demo_scenarios.py, estático para el FE).
SCENARIOS = [
    {
        "id": "staging_inspect",
        "titulo": "Consultar estado en staging",
        "descripcion": "Un operador consulta la salud del servicio de pagos en staging.",
        "prompt": "Consulta el estado del servicio payments en staging.",
        "role": "operator",
        "environment": "staging",
        "tool": "inspect_service",
        "esperado": "allow",
        "esperado_con_aprobacion": None,
        "permite_aprobacion": False,
    },
    {
        "id": "prod_restart",
        "titulo": "Reiniciar pagos en producción",
        "descripcion": (
            "Un operador pide reiniciar pagos en producción. Requiere aprobación "
            "humana; con la aprobación exacta vinculada, se permite."
        ),
        "prompt": "Reinicia el servicio de pagos en producción.",
        "role": "operator",
        "environment": "production",
        "tool": "restart_service",
        "esperado": "review",
        "esperado_con_aprobacion": "allow",
        "permite_aprobacion": True,
    },
    {
        "id": "unauthorized_restart",
        "titulo": "Reinicio sin permisos",
        "descripcion": "Un developer sin permiso pide reiniciar checkout en staging.",
        "prompt": "Reinicia checkout en staging.",
        "role": "developer",
        "environment": "staging",
        "tool": "restart_service",
        "esperado": "deny",
        "esperado_con_aprobacion": None,
        "permite_aprobacion": False,
    },
]
SCENARIOS_BY_ID = {s["id"]: s for s in SCENARIOS}

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_CORS},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _invoke_agent(body: dict) -> dict:
    """Invoca el runtime de AgentCore en modo escenario y devuelve su StepRun."""
    session_id = uuid.uuid4().hex + uuid.uuid4().hex  # >=33 chars
    payload = json.dumps(
        {"scenario_id": body["scenario_id"], "approve": bool(body.get("approve", False))}
    ).encode("utf-8")
    result = _client.invoke_agent_runtime(
        agentRuntimeArn=AGENT_ARN,
        runtimeSessionId=session_id,
        payload=payload,
    )
    raw = result["response"].read()
    return json.loads(raw)


def handler(event: dict, context: object) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return _resp(204, {})
    if path == "/api/health":
        return _resp(200, {"status": "ok", "provider": "jev-typesafe", "mode": "agentcore",
                           "jev": {"authenticated": True, "reason": "ok"}})
    if path == "/api/scenarios":
        return _resp(200, {"scenarios": SCENARIOS})
    if path == "/api/run" and method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return _resp(400, {"error": "invalid_json"})
        if body.get("scenario_id") not in SCENARIOS_BY_ID:
            return _resp(400, {"error": "unknown_scenario"})
        try:
            step_run = _invoke_agent(body)
        except Exception as exc:  # noqa: BLE001
            return _resp(502, {"error": "agent_invocation_failed", "detail": str(exc)})
        return _resp(200, step_run)
    return _resp(404, {"error": "not_found"})
