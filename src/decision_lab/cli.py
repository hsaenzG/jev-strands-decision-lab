"""Interfaz de línea de comandos del laboratorio.

Comandos:
  demo       Corre los tres escenarios guionados (allow / review / deny).
  evaluate   Evalúa el dataset de escenarios y reporta métricas honestas.
  scenarios  Lista los escenarios etiquetados disponibles.

Todo corre localmente, sin AWS ni credenciales de Jev. Si existe TYPESAFE_API_KEY
y el SDK está instalado, 'demo' y 'evaluate' pueden usar el proveedor real.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .evaluation import evaluate_scenarios, load_scenarios
from .pipeline import DecisionPipeline
from .providers import get_default_provider
from .providers.mock import MockJevProvider
from .state import ApprovalStore, AuthenticatedIdentity, build_decision_state
from .telemetry import JsonlTracer

_DEFAULT_SCENARIOS = Path(__file__).resolve().parents[2] / "examples" / "scenarios.json"

# ANSI simple para resaltar la acción.
_COLORS = {"allow": "\033[92m", "review": "\033[93m", "deny": "\033[91m"}
_RESET = "\033[0m"


def _fmt_action(action: str) -> str:
    return f"{_COLORS.get(action, '')}{action.upper()}{_RESET}"


def cmd_demo(args: argparse.Namespace) -> int:
    """Tres escenarios guionados que cuentan la historia del proyecto."""
    provider = MockJevProvider() if args.offline else get_default_provider()
    approvals = ApprovalStore()
    pipeline = DecisionPipeline(
        provider, tracer=JsonlTracer(stream=sys.stderr), approvals=approvals
    )

    print(f"\n=== Jev + Strands Decision Lab ===  proveedor: {provider.name}\n")

    # Escenario 1: lectura en staging -> allow.
    print("1) Operador consulta el estado de pagos en staging")
    op = AuthenticatedIdentity(actor_id="ana", role="operator")
    s1 = build_decision_state(
        identity=op,
        tool_name="inspect_service",
        arguments={"service": "payments", "environment": "staging"},
        environment="staging",
        approvals=approvals,
    )
    r1 = pipeline.decide(s1)
    print(f"   -> {_fmt_action(r1.outcome.action)}  [{r1.outcome.reason_code}]")
    if r1.execution:
        print(f"      {r1.execution.output}")

    # Escenario 2: reinicio en producción sin aprobación -> review.
    print("\n2) Operador pide reiniciar pagos en PRODUCCIÓN (sin aprobación)")
    s2 = build_decision_state(
        identity=op,
        tool_name="restart_service",
        arguments={"service": "payments", "environment": "production"},
        environment="production",
        approvals=approvals,
    )
    r2 = pipeline.decide(s2)
    print(f"   -> {_fmt_action(r2.outcome.action)}  [{r2.outcome.reason_code}]")
    print(f"      {r2.outcome.detail}")

    # Escenario 2b: ahora con aprobación válida y vinculada -> allow.
    print("\n   2b) Un líder on-call aprueba exactamente esa acción...")
    approvals.grant(
        request_id=s2.request_id,
        tool_name="restart_service",
        arguments={"service": "payments", "environment": "production"},
        approver="oncall-lead",
    )
    s2b = build_decision_state(
        identity=op,
        tool_name="restart_service",
        arguments={"service": "payments", "environment": "production"},
        environment="production",
        request_id=s2.request_id,
        approvals=approvals,
    )
    r2b = pipeline.decide(s2b)
    print(f"   -> {_fmt_action(r2b.outcome.action)}  [{r2b.outcome.reason_code}]")
    if r2b.execution:
        print(f"      {r2b.execution.output}")

    # Escenario 3: developer sin permisos pide reiniciar -> deny.
    print("\n3) Un developer (sin permiso) pide reiniciar checkout en staging")
    dev = AuthenticatedIdentity(actor_id="beto", role="developer")
    s3 = build_decision_state(
        identity=dev,
        tool_name="restart_service",
        arguments={"service": "checkout", "environment": "staging"},
        environment="staging",
        approvals=approvals,
    )
    r3 = pipeline.decide(s3)
    print(f"   -> {_fmt_action(r3.outcome.action)}  [{r3.outcome.reason_code}]")
    print(f"      {r3.outcome.detail}")

    print("\nLas trazas JSONL se emitieron por stderr. Idea central:")
    print("   el agente propone, Jev evalúa, las políticas autorizan.\n")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    report = evaluate_scenarios(args.scenarios)
    print(f"\nEscenarios: {report.total}")
    print(f"Correctos:  {report.passed}/{report.total}  (exactitud {report.accuracy:.0%})")
    print(
        f"Unsafe allows: {len(report.unsafe_allows)}  (ejecuciones donde se esperaba review/deny)"
    )
    print(
        f"Latencia local P50: {report.latency_percentile(50):.2f} ms  "
        f"P95: {report.latency_percentile(95):.2f} ms"
    )
    print("  (latencia del motor LOCAL: política + mock; no es latencia de Jev)\n")

    failures = [o for o in report.outcomes if not o.passed]
    if failures:
        print("Fallos:")
        for o in failures:
            print(
                f"  - {o.scenario_id}: esperado={o.expected} obtenido={o.actual} [{o.reason_code}]"
            )
        return 1
    print("Todos los escenarios coinciden con su etiqueta esperada.\n")
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    for s in load_scenarios(args.scenarios):
        print(f"{s['id']:<40} esperado={s['expected']:<7} {s['note']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="decision-lab",
        description="Capa de decisiones para agentes: el agente propone, "
        "Jev evalúa, las políticas autorizan.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="Corre los tres escenarios guionados")
    p_demo.add_argument(
        "--offline",
        action="store_true",
        help="Fuerza el proveedor mock aunque exista TYPESAFE_API_KEY",
    )
    p_demo.set_defaults(func=cmd_demo)

    p_eval = sub.add_parser("evaluate", help="Evalúa el dataset de escenarios")
    p_eval.add_argument("--scenarios", default=str(_DEFAULT_SCENARIOS))
    p_eval.set_defaults(func=cmd_evaluate)

    p_scn = sub.add_parser("scenarios", help="Lista los escenarios etiquetados")
    p_scn.add_argument("--scenarios", default=str(_DEFAULT_SCENARIOS))
    p_scn.set_defaults(func=cmd_scenarios)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
