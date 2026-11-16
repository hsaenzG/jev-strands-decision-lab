# Arquitectura

Dos vistas complementarias: el **flujo de decisión** (lógica del agente) y la
**infraestructura AWS** sobre la que corre desplegado.

## 1. Flujo de decisión (lógica del agente)

```mermaid
flowchart TD
    U[Solicitud del usuario] --> A[Agente Strands / Bedrock]
    A --> T[Llamada de herramienta propuesta]
    T --> H[Hook BeforeToolCallEvent]
    H --> S[Constructor de estado confiable]
    S --> J[Adaptador de decisión Jev]
    J --> P[Motor de políticas determinista]
    S --> P
    P -->|allow| X[Ejecución de herramienta simulada]
    P -->|review| R[Flujo de aprobación humana]
    P -->|deny| D[Cancelar herramienta]
    R -->|aprobada, mismo request y argumentos| X
    R -->|rechazada o expirada| D
    X --> O[Traza y respuesta del agente]
    D --> O
```

## 2. Infraestructura AWS (lo desplegado)

```mermaid
flowchart LR
    User([Usuario / navegador])

    subgraph PERSONAL["Cuenta AWS: personal"]
        R53[Route 53<br/>zona hazelsaenz.tech]
    end

    subgraph STRANDS["Cuenta AWS: free-tier-Strands · us-east-2"]
        AMP[Amplify Hosting<br/>FE Astro + CloudFront + ACM]
        APIGW[API Gateway<br/>HTTP API + CORS]
        LAMBDA[Lambda jev-bridge<br/>invoca el runtime con SigV4]
        subgraph AC["AgentCore Runtime · jevstrandsdemo"]
            AGENT[Agente Strands<br/>+ hook de decisión + política]
        end
        BR[Amazon Bedrock<br/>Nova us.amazon.nova-pro-v1:0]
        SM[Secrets Manager<br/>clave de Jev]
        CW[CloudWatch Logs]
    end

    JEV[[Jev · TypeSafe AI<br/>api.typesafe.ai · jev-1.14.0]]

    User -->|HTTPS www.apps.strands-jev-demo.hazelsaenz.tech| R53
    R53 -->|CNAME| AMP
    AMP -->|fetch /api/*| APIGW
    APIGW --> LAMBDA
    LAMBDA -->|InvokeAgentRuntime| AGENT
    AGENT -->|InvokeModel| BR
    AGENT -->|señal consultiva| JEV
    AGENT -->|GetSecretValue| SM
    AGENT -.observabilidad.-> CW
```

Mapeo lógico → infraestructura: el *agente* y el *hook/política* viven dentro del
**AgentCore Runtime**; el *adaptador de Jev* llama a **api.typesafe.ai**; el
modelo es **Bedrock Nova**; el navegador llega por **Amplify → API Gateway →
Lambda**. Las herramientas son simuladas también en la nube: no se toca
infraestructura real.

## Responsabilidades

- **Strands**: interpreta la intención del usuario y *propone* llamadas de
  herramienta. No autoriza.
- **Constructor de estado confiable** (`state.py`): combina la herramienta y
  argumentos propuestos con la identidad autenticada, el rol, el entorno y los
  metadatos de aprobación verificados. **Nunca** acepta afirmaciones de rol o
  aprobación que vengan del prompt del usuario.
- **Adaptador Jev** (`providers/`): evalúa rutas candidatas o señales de riesgo;
  jamás autoriza por su cuenta.
- **Motor de políticas** (`policy.py`): valida permiso, allowlist de
  herramientas, entorno, aprobación y defaults seguros. Es la única autoridad.
- **Ejecutor** (`tools.py`): solo efectos simulados en el MVP.
- **Observabilidad** (`telemetry.py`): traza request ID, herramienta, entradas
  de decisión (redactadas), proveedor/versión, salida, regla de política,
  latencia y resultado.

## Contratos internos (independientes del formato de red de Jev)

Ver `src/decision_lab/models.py`: `DecisionState`, `DecisionSignals`,
`PolicyOutcome`. El resto del sistema solo habla estos tipos; el adaptador de
proveedor traduce el mundo externo a ellos. Esto evita acoplar la política al
esquema de respuesta de ningún proveedor.

## Máquina de estados de la decisión

```
RECEIVED → PROPOSED → EVALUATING → EVALUATED → POLICY_CHECKED
         → ALLOWED / WAITING_APPROVAL / DENIED → EXECUTING → COMPLETED / FAILED
```

- Timeout o respuesta inválida del proveedor: `EVALUATING → DENIED` (fail-closed).
- `WAITING_APPROVAL → ALLOWED` solo tras una aprobación autenticada, no expirada,
  vinculada a request ID + herramienta exacta + hash canónico de argumentos.
- Una acción distinta debe re-evaluarse.

## AWS (opcional)

Bedrock para el modelo; AgentCore Runtime o Lambda para el agente; DynamoDB para
el estado; Step Functions para aprobación durable; Secrets Manager para la clave
de Jev; CloudWatch/OpenTelemetry para trazas. **Local primero**: nada se
despliega ni genera gasto sin una decisión explícita del lector.
