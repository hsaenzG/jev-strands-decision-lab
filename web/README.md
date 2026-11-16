# Decision Lab — Frontend de aprendizaje (Astro)

Una interfaz visual para *ver* cómo una llamada de herramienta viaja por la capa
de decisiones, dibujada como un **diagrama de flujo agéntico con cajas**: el
agente propone, el hook intercepta, se arma el estado confiable, Jev evalúa, la
política decide y (si corresponde) se ejecuta. Al correr un escenario, las cajas
se iluminan en secuencia; **haz clic en cualquier caja** para abrir un panel con
el **código real** de esa etapa (extraído del fuente Python con `inspect`) y la
entrada/salida de la última corrida.

No reimplementa la lógica: consume el **backend Python** del laboratorio, de modo
que lo que ves en pantalla son decisiones reales del mismo motor que la CLI.

## Cómo correrlo (dos procesos)

**1. Backend Python** (desde la raíz del repo):

```bash
uv run python -m decision_lab.server          # http://127.0.0.1:8000
# o con el proveedor real de Jev si tienes clave:
uv run python -m decision_lab.server --live
```

**2. Frontend Astro** (desde `web/`):

```bash
npm install
npm run dev                                    # http://localhost:4321
```

Abre http://localhost:4321, elige un escenario y pulsa **Correr escenario**.

## Qué puedes probar

- **Consultar estado en staging** → PERMITIDO (lectura de bajo riesgo).
- **Reiniciar pagos en producción** → REQUIERE APROBACIÓN; marca *"Emitir
  aprobación humana vinculada"* y vuelve a correr para verlo pasar a PERMITIDO.
- **Reinicio sin permisos** → DENEGADO (rol insuficiente; el prompt no manda).

## Configuración

El frontend apunta por defecto a `http://127.0.0.1:8000`. Para cambiarlo, define
la variable de entorno al construir/servir:

```bash
PUBLIC_API_BASE=http://127.0.0.1:9000 npm run dev
```

## Build estático

```bash
npm run build      # genera dist/ (sitio estático)
npm run preview    # sirve dist/ localmente
```

El sitio es estático; toda la interacción ocurre por `fetch` al backend desde el
navegador. Necesitas el backend Python corriendo para que los botones funcionen.
