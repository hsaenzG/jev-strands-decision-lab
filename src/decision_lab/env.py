"""Carga mínima de un archivo .env sin dependencias externas.

Solo soporta líneas `CLAVE=valor` y comentarios con `#`. No sobrescribe
variables que ya existan en el entorno (el entorno tiene prioridad). Busca el
.env en la raíz del repositorio.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path | None = None) -> None:
    """Carga variables de un .env en os.environ si no están ya definidas."""
    if path is None:
        # raíz del repo = dos niveles arriba de src/decision_lab/
        path = Path(__file__).resolve().parents[2] / ".env"
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
