"""Servidor HTTP mínimo que expone el pipeline al frontend de aprendizaje.

Usa solo la librería estándar (sin dependencias nuevas). Sirve la misma lógica
verificada que la CLI, de modo que el frontend muestra decisiones reales.

Por defecto usa el **proveedor real de Jev** (requiere TYPESAFE_API_KEY). Pasa
`--mock` para forzar el proveedor determinista local sin red.

Endpoints:
  GET  /api/health                 -> estado, proveedor y si la clave autentica.
  GET  /api/scenarios              -> catálogo de los 3 escenarios.
  GET  /api/code                   -> código real de cada etapa del flujo.
  POST /api/run                    -> corre un escenario y devuelve los pasos.
       body: {"scenario_id": "...", "approve": false}

Arranque:
  uv run python -m decision_lab.server            # Jev real (puerto 8000)
  uv run python -m decision_lab.server --mock     # proveedor mock local
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .code_snippets import build_snippets
from .demo_scenarios import DEMO_SCENARIOS, run_demo_scenario
from .env import load_dotenv
from .providers.base import ProviderError
from .providers.jev import RealJevProvider, jev_available
from .providers.mock import MockJevProvider
from .state import AuthenticatedIdentity, build_decision_state


def _public_scenarios() -> list[dict[str, Any]]:
    """Catálogo seguro para el frontend (sin estructuras internas)."""
    return [
        {
            "id": s["id"],
            "titulo": s["titulo"],
            "descripcion": s["descripcion"],
            "prompt": s["prompt"],
            "role": s["role"],
            "environment": s["environment"],
            "tool": s["tool"],
            "esperado": s["esperado"],
            "esperado_con_aprobacion": s.get("esperado_con_aprobacion"),
            "permite_aprobacion": s.get("approval") == "optional",
        }
        for s in DEMO_SCENARIOS
    ]


def _probe_jev() -> dict[str, Any]:
    """Hace una llamada mínima para verificar que la clave autentica.

    Devuelve un dict con el resultado, sin lanzar. Se usa en /api/health para que
    el frontend muestre de inmediato si Jev real está disponible.
    """
    if not jev_available():
        return {"authenticated": False, "reason": "no_api_key"}
    identity = AuthenticatedIdentity(actor_id="probe", role="operator")
    state = build_decision_state(
        identity=identity,
        tool_name="inspect_service",
        arguments={"service": "payments", "environment": "staging"},
        environment="staging",
    )
    try:
        RealJevProvider().evaluate(state)
        return {"authenticated": True, "reason": "ok"}
    except ProviderError as exc:
        return {"authenticated": False, "reason": exc.reason_code, "detail": str(exc)}


class Handler(BaseHTTPRequestHandler):
    # Modo del servidor, inyectado por clase.
    use_mock: bool = False

    def _provider(self) -> Any:
        if self.use_mock:
            return MockJevProvider()
        # Modo real: exige el proveedor de Jev. Si no hay clave, es un error
        # explícito (no caemos a mock en silencio).
        return RealJevProvider()

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 (nombre impuesto por la base)
        self._send_json({}, status=204)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            if self.use_mock:
                self._send_json(
                    {"status": "ok", "provider": "mock-jev", "mode": "mock", "jev": None}
                )
            else:
                jev = _probe_jev()
                self._send_json(
                    {
                        "status": "ok" if jev["authenticated"] else "degraded",
                        "provider": "jev-typesafe",
                        "mode": "live",
                        "jev": jev,
                    }
                )
        elif self.path == "/api/scenarios":
            self._send_json({"scenarios": _public_scenarios()})
        elif self.path == "/api/code":
            snippets = {k: s.to_dict() for k, s in build_snippets().items()}
            self._send_json({"snippets": snippets})
        else:
            self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/run":
            self._send_json({"error": "not_found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=400)
            return

        scenario_id = body.get("scenario_id")
        approve = bool(body.get("approve", False))
        if scenario_id not in {s["id"] for s in DEMO_SCENARIOS}:
            self._send_json({"error": "unknown_scenario"}, status=400)
            return

        try:
            provider = self._provider()
        except ProviderError as exc:
            self._send_json(
                {"error": "provider_unavailable", "reason": exc.reason_code, "detail": str(exc)},
                status=503,
            )
            return

        run = run_demo_scenario(scenario_id, provider, approve=approve)
        self._send_json(run.to_dict())

    def log_message(self, fmt: str, *args: Any) -> None:
        # Silencia el log por request para no ensuciar la salida de la demo.
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decision-lab-server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Usa el proveedor mock determinista local, sin red (por defecto: Jev real)",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    Handler.use_mock = args.mock
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    if args.mock:
        print(f"Decision Lab API en http://{args.host}:{args.port}  (proveedor: MOCK local)")
    else:
        print(f"Decision Lab API en http://{args.host}:{args.port}  (proveedor: Jev real)")
        if not jev_available():
            print(
                "  AVISO: no hay TYPESAFE_API_KEY en el entorno. Las corridas "
                "devolverán 503. Exporta tu clave o usa --mock."
            )
        else:
            probe = _probe_jev()
            if probe["authenticated"]:
                print("  Clave Jev verificada: autenticación OK.")
            else:
                print(
                    f"  AVISO: la clave Jev NO autenticó ({probe['reason']}). "
                    "Las decisiones serán fail-closed (deny). Revisa TYPESAFE_API_KEY."
                )

    print("Endpoints: GET /api/health, GET /api/scenarios, GET /api/code, POST /api/run")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
