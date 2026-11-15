# Guion de demo (10–15 minutos)

Objetivo: dejar grabada una idea en la cabeza del público — **razonar no es
autorizar**. El agente propone, Jev evalúa, las políticas autorizan.

## Antes de empezar (1 min)

```bash
cd jev-strands-decision-lab
uv sync
```

Todo corre offline, sin AWS ni clave de Jev. Si tienes proyector, agranda la
fuente de la terminal.

## 1. El gancho (2 min)

Plantea en voz alta: *"Reinicia el servicio de pagos en producción."* Pregunta
al público: ¿debería un agente hacerlo solo porque un LLM dijo que sí?

Muestra la lista de escenarios:

```bash
uv run decision-lab scenarios
```

Señala que hay tres resultados posibles: `allow`, `review`, `deny`.

## 2. La demo de los tres caminos (4 min)

```bash
uv run decision-lab demo
```

Narra cada bloque mientras aparece:

1. **Operador consulta estado en staging → ALLOW.** Lectura de bajo riesgo; la
   política y la señal del proveedor coinciden.
2. **Operador pide reiniciar pagos en PRODUCCIÓN → REVIEW.** Aquí está el corazón:
   aunque el operador tiene permiso, una escritura en producción exige aprobación
   humana vinculada. La herramienta se cancela con un mensaje claro.
   - **2b. Llega la aprobación exacta → ALLOW.** La aprobación está atada al
     mismo request, herramienta y hash de argumentos. Recién ahí ejecuta.
3. **Developer sin permiso pide reiniciar → DENY.** El rol confiable manda; da
   igual lo que diga el prompt.

## 3. La moraleja de seguridad (3 min)

Abre `examples/scenarios.json` y muestra los casos "malos":

- `s12`: el proveedor dice `execute`, pero la herramienta no está en la allowlist
  → `deny`. **La recomendación no amplía permisos.**
- `s09`/`s10`/`s11`: el proveedor falla (timeout, schema, error) → `deny`
  (fail-closed).
- `s21`: el prompt afirma ser admin → se ignora; el rol confiable es developer →
  `deny`.

Corre la evaluación y muestra la métrica clave:

```bash
uv run decision-lab evaluate
```

Destaca: **Unsafe allows: 0**. Ese es el número que importa.

## 4. Cómo está hecho (3 min)

Muestra tres archivos, en este orden:

1. `src/decision_lab/hooks.py` — la intercepción con `BeforeToolCallEvent` y
   `event.cancel_tool` (patrón verificado contra la doc de Strands).
2. `src/decision_lab/policy.py` — las reglas deterministas en orden; la única
   autoridad para autorizar.
3. `src/decision_lab/providers/jev.py` — el adaptador real de Jev detrás de
   `TYPESAFE_API_KEY`; sin clave, se usa el mock.

## 5. Cierre (1 min)

*"Deja que el agente proponga, que el motor de decisiones evalúe y que las
políticas autoricen."* Reto al público: agrega un cuarto escenario de falla a
`examples/scenarios.json` y corre `evaluate`.

## Plan B si algo falla en vivo

- Ten a mano la salida de `uv run decision-lab demo` ya capturada.
- Los tests son rápidos: `uv run pytest -q` como respaldo de que todo pasa.
