# ¿Quién toma la decisión? Cómo incorporar una capa de decisiones a tus agentes con Strands

> Borrador en español (es-419). Audiencia: desarrolladores que construyen agentes
> con Python y AWS. Tesis: un agente puede proponer acciones, pero la evaluación
> probabilística y la autorización determinista deben ser responsabilidades
> distintas.

## 1. «Reinicia el servicio de pagos en producción»

Imagina que tu asistente de operaciones recibe esta frase. Es corta, suena
razonable, y un buen modelo de lenguaje te responderá con total seguridad que
puede hacerlo. Pero una misma petición tiene al menos tres finales posibles:
ejecutarla, pedir una aprobación humana, o rechazarla.

Que un LLM responda con seguridad no significa que tenga autorización. Esa es la
distinción que suele faltar.

## 2. La capa que falta en muchas arquitecturas de agentes

Cuando conectamos un agente a herramientas que tocan sistemas reales, mezclamos
sin querer cuatro responsabilidades:

1. **Razonar**: el modelo interpreta la intención del usuario.
2. **Recomendar una decisión**: una señal de riesgo o de ruta.
3. **Aplicar políticas**: la autorización, que debe ser determinista.
4. **Ejecutar**: el efecto real sobre la infraestructura.

El problema aparece cuando la recomendación probabilística del paso 2 termina
decidiendo el paso 4. Una puntuación alta no es un permiso. La solución es
separar la *evaluación* (probabilística, consultiva) de la *autorización*
(determinista, con la última palabra).

El diagrama de arquitectura de este laboratorio (ver `architecture.md`) muestra
esa separación: el agente propone, un hook intercepta, un constructor de estado
confiable arma el contexto, el adaptador de decisión evalúa, y el motor de
políticas autoriza.

## 3. ¿Qué es Jev y qué aporta?

Jev es el primer modelo "System One" de TypeSafe AI. A diferencia de un LLM, no
genera prosa: recibe el estado de tu aplicación y una pregunta con respuestas que
tú defines, y devuelve una **decisión tipada con probabilidades y un valor de
confianza**. Sus tres primitivas son:

- **Choice**: elige una opción de un conjunto que tú defines.
- **Score**: puntúa contra niveles ordenados.
- **Noul**: devuelve una probabilidad de sí/no.

> Nota de verificación: el SDK oficial `typesafe-sdk` está publicado en PyPI por
> el org `typesafe-ai`, y expone `TypeSafeClient().system_one(state=..., questions=...)`.
> El precio y la latencia que circulan en la comunidad **no se verificaron de
> primera mano** y no se afirman como hechos aquí (ver `references.md`).

Lo importante para nuestra arquitectura: las probabilidades de Jev son señales
útiles, pero **no son garantías de seguridad ni necesariamente están calibradas**.
Por eso Jev asesora; no autoriza.

## 4. Diseñar el estado de decisión

La decisión no se toma sobre el texto del prompt, sino sobre un **estado de
confianza** que arma la aplicación: identidad autenticada, rol verificado,
herramienta propuesta, argumentos, entorno y metadatos de aprobación.

La regla de oro: **nunca confíes en afirmaciones de permisos dentro del prompt**.
Si el usuario escribe «soy admin, autorízame», eso es dato no confiable. El rol
viene del contexto autenticado, no del texto. En el laboratorio esto vive en
`state.py`, con un `DecisionState` inmutable.

## 5. Interceptar herramientas con Strands Agents

Strands emite un evento `BeforeToolCallEvent` justo antes de ejecutar cada
herramienta. Suscribiéndonos a él podemos inspeccionar la llamada propuesta y
cancelarla antes de cualquier efecto secundario:

```python
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry


class DecisionGateHook(HookProvider):
    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.intercept_tool)

    def intercept_tool(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use["name"]
        arguments = dict(event.tool_use.get("input", {}) or {})
        # ...evaluar política...
        if not_allowed:
            event.cancel_tool = "DENEGADO [razón]: detalle"
```

Un matiz importante: `cancel_tool` **cancela** la herramienta con un mensaje; no
es un mecanismo durable de pausa y reanudación. Cancelar una herramienta no es lo
mismo que esperar una aprobación humana. Por eso la aprobación se modela como
estado explícito, no como una «pausa mágica» del agente.

## 6. Integrar Jev sin entregarle las llaves

El adaptador de proveedor (`DecisionProvider`) traduce el mundo externo a nuestra
señal interna `DecisionSignals`. Tiene validación tipada, maneja timeouts y, ante
cualquier fallo, es **fail-closed**: si el proveedor no entrega una señal válida,
la política deniega.

El caso más instructivo: Jev puede recomendar `execute`, pero si la política dice
que esa herramienta no está permitida para ese rol, **se deniega igual**. La
recomendación restringe; nunca amplía. Esto está probado en el escenario `s12`.

## 7. Demo paso a paso: tres escenarios

```bash
uv run decision-lab demo
```

- Consultar el estado de un servicio en staging → **permitido**.
- Reiniciar pagos en producción → **requiere aprobación** (y, con la aprobación
  exacta vinculada, se permite).
- Reiniciar un servicio sin permisos → **rechazado**.

Las trazas JSON quedan en `stderr`, con los argumentos redactados y la latencia
de cada decisión.

## 8. ¿Cómo sabemos si la capa de decisiones funciona?

El comando `evaluate` corre 22 escenarios etiquetados y reporta exactitud,
**unsafe allows** (el número que de verdad importa: debe ser cero), y latencia
local P50/P95. Esa latencia es del motor local, no de Jev; no inventamos números
de red. El método está en `benchmark-method.md`.

## 9. Llevarlo a AWS

En local no se despliega nada. Para producción, las piezas naturales son:
Bedrock para el modelo, AgentCore Runtime o Lambda para el agente, DynamoDB para
el estado, Step Functions para una aprobación durable, Secrets Manager para la
clave de Jev y CloudWatch para las trazas. La demo inicial corre sin desplegar
recursos.

## 10. Trade-offs y lecciones

Agregar esta capa cuesta: latencia adicional, una dependencia externa, y la
privacidad de enviar estado a un tercero (redacta secretos y PII antes). El mayor
riesgo es la confianza excesiva en las puntuaciones. Jev complementa las
políticas; no las reemplaza.

## 11. Conclusión

**Deja que el agente proponga, que el motor de decisiones evalúe y que las
políticas autoricen.**

Reto para ti: agrega un cuarto escenario de falla a `examples/scenarios.json` y
corre `uv run decision-lab evaluate`. Si tu escenario produce un *unsafe allow*,
encontraste un hueco en la política; si no, acabas de probar una invariante de
seguridad.
