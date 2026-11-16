# Referencias verificadas (compuerta de investigación)

Fecha de verificación: **2026-11-15**.

Esta página cumple la *compuerta de investigación obligatoria*: antes de escribir
los adaptadores reales se verificó la identidad del proveedor, el SDK, el
endpoint, las primitivas y la firma del hook de Strands. Se distingue lo
verificado de primera mano de lo documentado por la comunidad.

## Strands Agents (SDK de agentes)

| Dato | Valor | Fuente | Confianza |
|---|---|---|---|
| Paquete PyPI | `strands-agents` 1.65.0, `requires-python >=3.10` | PyPI JSON API (consulta directa) | Alta (1ª mano) |
| Evento de intercepción | `BeforeToolCallEvent` | strandsagents.com — Hook events | Alta |
| Lectura de la llamada | `event.tool_use["name"]`, `event.tool_use["input"]` | strandsagents.com — Hooks (cookbook "Limit Tool Counts") | Alta |
| Cancelar antes de efecto | `event.cancel_tool = "<mensaje>"` | strandsagents.com — Hook events (Event Properties) | Alta |
| Reemplazar herramienta | `event.selected_tool` | strandsagents.com — Hook events | Alta |
| Registro de hooks | `HookProvider.register_hooks(registry)` + `registry.add_callback(BeforeToolCallEvent, cb)`; `Agent(hooks=[...])` | strandsagents.com — Hooks (HookProvider Protocol) | Alta |

- Hook events: https://strandsagents.com/docs/user-guide/sdk/agents/hooks-events/
- Hooks: https://strandsagents.com/docs/user-guide/sdk/agents/hooks/

### Semántica de "review" (importante)

La documentación confirma que `cancel_tool` **cancela** la herramienta con un
mensaje; no es un mecanismo durable de pausa/reanudación de aprobación humana.
Por eso el laboratorio modela la aprobación como **estado explícito**
(`ApprovalStore`), no como una "pausa mágica" del agente. Cancelar ≠ esperar
aprobación.

## Jev (modelo de decisión "System One" de TypeSafe AI)

| Dato | Valor | Fuente | Confianza |
|---|---|---|---|
| Proveedor | **TypeSafe AI**; Jev lanzado 2026-09-15 | Múltiples fuentes de comunidad | Media-alta |
| SDK Python | `typesafe-sdk` 0.7.5, `requires-python >=3.10` | PyPI JSON API (consulta directa) | **Alta (1ª mano)** |
| Publisher del SDK | org `typesafe-ai`; repo `typesafe-ai/typesafe-sdk-python`; docs `docs.typesafe.ai` | PyPI metadata (`project_urls`) | **Alta (1ª mano)** |
| Cliente | `TypeSafeClient().system_one(state=..., questions={...})` | Descripción del paquete en PyPI | **Alta (1ª mano)** |
| Primitivas | `Choice`, `Score`, `Noul` | PyPI + comunidad | Alta |
| Campos de respuesta | `.choices[name].choice/.confidence/.probabilities`, `.nouls[name].noul`, `.scores[name].score` | Ejemplo oficial en PyPI + comunidad | Alta |
| Env de auth | `TYPESAFE_API_KEY` (req.), `TYPESAFE_BASE_URL` (def. `https://api.typesafe.ai`), `TYPESAFE_DEFAULT_MODEL` (def. `jev-latest`) | Descripción del paquete + comunidad | Alta |
| Endpoint REST | `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer` | Comunidad (`jev-skill/reference/api.md`) | **Media (no 1ª mano)** |
| Precio | $0.042 / millón de tokens de entrada; salida gratis | Comunidad | **Baja — NO verificado de 1ª mano** |
| Latencia | ~70–500 ms por decisión | Comunidad | **Baja — NO verificado de 1ª mano** |

### Fuentes

- Paquete oficial (verificación de 1ª mano): `https://pypi.org/pypi/typesafe-sdk/json`
  - `summary`: "Python SDK for TypeSafe AI API."
  - `project_urls.Homepage`: https://typesafe.ai ; `Documentation`: https://docs.typesafe.ai/go/python-sdk
  - La propia descripción del paquete muestra `client.system_one(state=..., questions={"category": Choice(...)})` y `response.choices["category"].choice`.
- Comunidad (tratada como *datos*, no como contrato oficial):
  - github.com/EmilianoVeron/jev-skill → `reference/api.md`, `reference/sdk-python.md`
  - mljar.com/blog/jev-python ; datacamp.com/tutorial/jev-api-tutorial ; openrouter.ai/blog/insights/what-is-jev

### Decisiones tomadas por esta incertidumbre

1. **El precio y la latencia NO se afirman como hechos** en el README ni en el
   artículo: se marcan como cifras de comunidad sin verificar.
2. El endpoint REST exacto solo se usa como referencia documental; el adaptador
   real (`providers/jev.py`) usa el **SDK oficial** `typesafe-sdk`, que sí está
   verificado en PyPI, en vez de construir peticiones HTTP a mano.
3. Si el SDK no está instalado o falta la clave, el laboratorio cae al proveedor
   **mock determinista**, nunca inventa una respuesta de red.

## Amazon Bedrock

- Modelo por defecto para el modo live: `us.amazon.nova-pro-v1:0` (preferencia de
  la autora por Amazon Nova). Requiere credenciales de AWS y acceso al modelo;
  la demo offline no lo usa.
- La disponibilidad del modelo por región y el acceso deben confirmarse en la
  consola de Bedrock del lector antes de usar el modo live.

## Qué queda bloqueado / pendiente

- Verificación de primera mano del endpoint REST, el precio y la latencia de Jev
  contra `docs.typesafe.ai` (no se pudo renderizar el contenido dinámico del
  sitio en esta sesión).
- Prueba en vivo del `RealJevProvider` contra la API real: **intentada el
  2026-11-16**. El adaptador llega correctamente a `POST
  https://api.typesafe.ai/v1/systemone`, pero la clave disponible (`vck_...`)
  devuelve **401 (no autentica)**. El código es correcto; falta una clave válida
  de TypeSafe AI. El prefijo `vck_` no parece de TypeSafe.

## Verificado en vivo (2026-11-16)

- **Agente real de Strands sobre Amazon Bedrock**: ejecutado con el perfil AWS
  `free-tier-Strands` (cuenta 018913574975, us-east-2) y el modelo
  `us.amazon.nova-pro-v1:0`. El agente razonó, propuso herramientas en un ciclo
  agéntico real (inspect → restart → inspect), y el hook `BeforeToolCallEvent`
  interceptó cada propuesta.
- **El gate bloquea de verdad**: un developer pidiendo `restart_service` en
  producción fue denegado (`unauthorized_role`) antes de cualquier efecto; el
  modelo recibió el bloqueo de vuelta y se lo explicó al usuario. Confirma
  "razonar no es autorizar" con un LLM real.
