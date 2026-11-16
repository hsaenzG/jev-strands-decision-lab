"""Fragmentos de código real de cada etapa del flujo agéntico.

En vez de incrustar cadenas de código a mano (que se desincronizarían), se
extrae el código fuente vivo con `inspect.getsource`. Así, al hacer clic en una
caja del diagrama, el frontend muestra el código verdadero que implementa esa
etapa, con su archivo de origen.

Las claves coinciden con los nodos del diagrama del frontend.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import agent, hooks, policy, state, tools
from .providers import jev as jev_provider


@dataclass
class CodeSnippet:
    key: str
    title: str
    file: str
    language: str
    code: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "file": self.file,
            "language": self.language,
            "code": self.code,
            "explanation": self.explanation,
        }


def _src(obj: Callable[..., Any]) -> tuple[str, str]:
    """Devuelve (código, ruta-relativa) de un objeto."""
    code = inspect.getsource(obj)
    file = inspect.getsourcefile(obj) or ""
    # Acorta la ruta a algo legible (src/decision_lab/...).
    marker = "src/decision_lab/"
    idx = file.find(marker)
    rel = file[idx:] if idx >= 0 else file
    return code, rel


def _snippet(
    key: str,
    title: str,
    obj: Callable[..., Any],
    explanation: str,
    language: str = "python",
) -> CodeSnippet:
    code, file = _src(obj)
    return CodeSnippet(
        key=key,
        title=title,
        file=file,
        language=language,
        code=code,
        explanation=explanation,
    )


def build_snippets() -> dict[str, CodeSnippet]:
    """Mapa etapa -> fragmento de código real que la implementa."""
    snippets = [
        _snippet(
            "model",
            "El modelo razona (Bedrock / Nova)",
            agent.build_live_agent,
            "El ciclo agéntico de Strands empieza aquí: el modelo (Amazon Nova "
            "sobre Bedrock) recibe el prompt y el historial, razona y decide si "
            "llamar una herramienta. Es el centro del loop: cada resultado de "
            "herramienta vuelve a este paso para la siguiente ronda.",
        ),
        _snippet(
            "propose",
            "El agente propone una herramienta",
            agent._build_strands_tools,
            "El modelo elige una herramienta y sus argumentos. Las herramientas "
            "se declaran con @tool en Strands. Aquí nada se ejecuta todavía: es "
            "una propuesta que el ciclo debe autorizar.",
        ),
        _snippet(
            "hook",
            "El hook BeforeToolCallEvent intercepta",
            hooks.DecisionGateHook.intercept_tool,
            "Strands dispara BeforeToolCallEvent antes de ejecutar cada "
            "herramienta. El hook lee el nombre y los argumentos propuestos y, si "
            "la política no autoriza, cancela con event.cancel_tool.",
        ),
        _snippet(
            "state",
            "Constructor de estado confiable",
            state.build_decision_state,
            "El rol viene de la identidad autenticada, NUNCA del prompt. La "
            "bandera approval_granted se calcula contra el ApprovalStore, no se "
            "acepta como dato de entrada.",
        ),
        _snippet(
            "provider",
            "Jev evalúa (adaptador de decisión)",
            jev_provider.RealJevProvider.evaluate,
            "El adaptador de Jev hace una pregunta Choice (ruta) y un Noul "
            "(riesgo) y devuelve una señal CONSULTIVA. Ante cualquier fallo, "
            "lanza ProviderError y la política aplica fail-closed. Jev nunca "
            "autoriza por sí solo.",
        ),
        _snippet(
            "policy",
            "Motor de políticas determinista",
            policy.evaluate_policy,
            "La única autoridad para autorizar. Aplica reglas deterministas en "
            "orden. La señal de Jev puede restringir (review/deny), pero jamás "
            "ampliar lo que las reglas permiten.",
        ),
        _snippet(
            "outcome",
            "Resultado → vuelve al modelo",
            tools.execute_simulated,
            "Solo si la política devuelve 'allow' se invoca la herramienta "
            "simulada. En 'review' se espera aprobación humana; en 'deny' se "
            "cancela sin efecto. El resultado (ejecución, bloqueo o mensaje) "
            "VUELVE al modelo como entrada de la siguiente ronda del ciclo.",
        ),
    ]
    return {s.key: s for s in snippets}
