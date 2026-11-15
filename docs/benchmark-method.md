# Método de evaluación (honesto)

Este documento explica **cómo** se miden las cosas en el laboratorio y, sobre
todo, qué **no** se afirma. El objetivo es que cualquier número del README o del
artículo sea reproducible y esté correctamente atribuido.

## Qué se mide

El comando `decision-lab evaluate` corre el dataset de `examples/scenarios.json`
contra el pipeline y reporta:

- **Exactitud por etiqueta**: fracción de escenarios cuya acción obtenida
  (`allow` / `review` / `deny`) coincide con la etiqueta esperada.
- **Unsafe allows**: número de escenarios donde se obtuvo `allow` pero se
  esperaba `review` o `deny`. Esta es la métrica de seguridad clave; el objetivo
  es **cero**.
- **Latencia local P50/P95**: tiempo del motor local (construcción de estado +
  política + proveedor mock). Se mide con `time.perf_counter()`.

## Qué NO se mide aquí (y por qué)

- **Latencia del servicio Jev real**: NO se mide en modo offline. La latencia
  reportada es del motor local con el mock, no de una llamada de red. Las cifras
  de ~70–500 ms que circulan en la comunidad **no se verificaron** en este
  laboratorio (ver `references.md`).
- **Costo por decisión**: el precio de Jev ($0.042 / M tokens de entrada) es un
  dato de comunidad **sin verificar de primera mano**; no se usa para calcular un
  costo "real" de la demo.
- **Calibración de probabilidades**: el mock produce scores fijos y
  deterministas; no son probabilidades calibradas. No se afirma nada sobre la
  calibración del modelo real.

## Comparación entre modos de decisión

El laboratorio permite comparar tres enfoques como *asesores* de la política:

1. **Solo reglas**: ignorar la señal del proveedor y decidir solo con la
   política determinista (equivale a `signals=None` → fail-closed, o a tratar
   toda ruta como `execute` y dejar que la política filtre).
2. **Mock Jev**: el proveedor determinista de este repo.
3. **Jev real**: con `TYPESAFE_API_KEY` y el extra `[jev]` instalado.

En los tres casos, la propiedad invariante es la misma: **ningún asesor puede
ampliar lo que la política permite**. Un `execute` del proveedor nunca convierte
un rol sin permiso en una ejecución.

## Cómo reproducir

```bash
uv run decision-lab evaluate
uv run pytest -q
```

Para medir con el proveedor real (requiere clave y acceso de red), define
`TYPESAFE_API_KEY` e instala el extra:

```bash
uv sync --extra jev
export TYPESAFE_API_KEY=sk-...
# y adapta la evaluación para instanciar RealJevProvider
```

> Cualquier número de latencia/costo del proveedor real debe medirse con tu
> propia clave y reportarse con su fecha y versión de modelo. No copies cifras de
> terceros como si fueran tuyas.
