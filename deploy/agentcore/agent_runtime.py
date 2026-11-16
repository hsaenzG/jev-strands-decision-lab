"""Entrypoint de AgentCore Runtime para el Jev + Strands Decision Lab.

Envuelve el agente real de Strands (Nova sobre Bedrock) con el hook de decisión,
Jev real y la política determinista. Son las 4 líneas de AgentCore sobre el mismo
código del laboratorio: el agente propone, Jev evalúa, las políticas autorizan.

La clave de Jev se lee de AWS Secrets Manager (no se hardcodea). El runtime
inyecta el nombre del secreto por variable de entorno JEV_SECRET_ID.

Nota de arranque: los imports pesados (Strands) y la lectura del secreto se hacen
de forma perezosa dentro del entrypoint, para que la inicialización del runtime
termine dentro del límite de 30s de AgentCore.
"""

from __future__ import annotations

import io
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

_jev_key_loaded = False


def _load_jev_key() -> None:
    """Carga la clave de Jev desde Secrets Manager a TYPESAFE_API_KEY (una vez)."""
    global _jev_key_loaded
    if _jev_key_loaded or os.environ.get("TYPESAFE_API_KEY"):
        _jev_key_loaded = True
        return
    secret_id = os.environ.get("JEV_SECRET_ID")
    if secret_id:
        region = os.environ.get("AWS_REGION", "us-east-2")
        try:
            import boto3

            client = boto3.client("secretsmanager", region_name=region)
            value = client.get_secret_value(SecretId=secret_id)["SecretString"]
            os.environ["TYPESAFE_API_KEY"] = value
        except Exception as exc:  # no romper; el proveedor hará fail-closed
            print(f"[warn] no se pudo leer el secreto de Jev: {exc}")
    _jev_key_loaded = True


@app.entrypoint
def invoke(payload: dict, context: object) -> dict:
    """Evalúa a través de la capa de decisiones. Dos modos:

    - Modo escenario (para el FE): payload {"scenario_id": ..., "approve": bool}
      devuelve el StepRun instrumentado (model→propose→hook→estado→Jev→política→
      resultado) que el frontend anima en el ciclo agéntico.
    - Modo agente libre: payload {"prompt": ..., "role": ..., "environment": ...}
      corre el agente real de Strands y devuelve su respuesta + decisiones.
    """
    _load_jev_key()

    from decision_lab.providers import get_default_provider
    from decision_lab.providers.mock import MockJevProvider

    use_mock = bool(payload.get("use_mock", False))
    provider = MockJevProvider() if use_mock else get_default_provider()

    # --- Modo escenario: lo que consume el frontend ---
    scenario_id = payload.get("scenario_id")
    if scenario_id:
        from decision_lab.demo_scenarios import run_demo_scenario

        approve = bool(payload.get("approve", False))
        run = run_demo_scenario(scenario_id, provider, approve=approve)
        return run.to_dict()

    # --- Modo agente libre: agente real de Strands sobre Bedrock ---
    from decision_lab.agent import build_live_agent
    from decision_lab.pipeline import DecisionPipeline
    from decision_lab.state import ApprovalStore, AuthenticatedIdentity
    from decision_lab.telemetry import JsonlTracer

    prompt = payload.get("prompt", "Consulta el estado del servicio payments en staging.")
    role = payload.get("role", "operator")
    environment = payload.get("environment", "staging")

    trace_buf = io.StringIO()
    pipeline = DecisionPipeline(
        provider,
        tracer=JsonlTracer(stream=trace_buf),
        approvals=ApprovalStore(),
    )
    identity = AuthenticatedIdentity(actor_id="agentcore-user", role=role)

    agent = build_live_agent(pipeline, identity=identity, environment=environment)
    result = agent(prompt)

    decisions = [
        {
            "tool_name": d.state.tool_name,
            "arguments": d.state.arguments,
            "action": d.outcome.action,
            "reason_code": d.outcome.reason_code,
            "detail": d.outcome.detail,
            "provider": d.signals.provider if d.signals else None,
            "suggested_route": d.signals.suggested_route if d.signals else None,
            "risk": d.signals.human_review_score if d.signals else None,
        }
        for d in agent.decision_gate.decisions
    ]

    return {
        "response": str(result),
        "decisions": decisions,
        "provider": provider.name,
        "traces": trace_buf.getvalue(),
    }


if __name__ == "__main__":
    app.run()
