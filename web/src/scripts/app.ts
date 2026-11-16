// Lógica del frontend de aprendizaje. Habla con el backend Python, anima el
// recorrido de una decisión por el flujo agéntico, y muestra el código real de
// cada etapa al hacer clic en su caja.

const API_BASE =
  (import.meta.env.PUBLIC_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000';

type StepStatus = 'ok' | 'warn' | 'block' | 'info';

interface Scenario {
  id: string;
  titulo: string;
  descripcion: string;
  prompt: string;
  role: string;
  environment: string;
  tool: string;
  esperado: string;
  esperado_con_aprobacion: string | null;
  permite_aprobacion: boolean;
}

interface Step {
  key: string;
  title: string;
  status: StepStatus;
  summary: string;
  data: Record<string, unknown>;
}

interface RunResult {
  scenario_id: string;
  final_action: 'allow' | 'review' | 'deny';
  reason_code: string;
  executed: boolean;
  latency_ms: number;
  steps: Step[];
}

interface CodeSnippet {
  key: string;
  title: string;
  file: string;
  language: string;
  code: string;
  explanation: string;
}

// Mapea el 'key' de un paso del backend al nodo del diagrama.
function nodeKeyFor(stepKey: string): string {
  if (stepKey === 'execute' || stepKey === 'review' || stepKey === 'deny') return 'outcome';
  return stepKey;
}

const ACTION_LABEL: Record<string, string> = {
  allow: 'PERMITIDO',
  review: 'REQUIERE APROBACIÓN',
  deny: 'DENEGADO',
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let scenarios: Scenario[] = [];
let snippets: Record<string, CodeSnippet> = {};
let selectedScenarioId: string | null = null;
let running = false;
let lastRun: RunResult | null = null;
let openNodeKey: string | null = null;

function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!));
}

async function checkHealth(): Promise<void> {
  const pill = $('api-status');
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    const data = await res.json();
    if (data.mode === 'mock') {
      pill.textContent = 'API conectada · proveedor: MOCK local';
      pill.className = 'pill pill--ok';
    } else if (data.jev && data.jev.authenticated) {
      pill.textContent = 'API conectada · Jev real (autenticado)';
      pill.className = 'pill pill--ok';
    } else {
      const reason = data.jev ? data.jev.reason : 'desconocido';
      pill.textContent = `Jev real sin autenticar (${reason}) — las decisiones serán deny`;
      pill.className = 'pill pill--err';
    }
  } catch {
    pill.textContent = 'API no disponible — inicia el backend (ver comando)';
    pill.className = 'pill pill--err';
  }
}

async function loadScenarios(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/scenarios`);
  const data = await res.json();
  scenarios = data.scenarios as Scenario[];
  renderScenarioCards();
}

async function loadSnippets(): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/api/code`);
    const data = await res.json();
    snippets = data.snippets as Record<string, CodeSnippet>;
  } catch {
    snippets = {};
  }
}

function renderScenarioCards(): void {
  const container = $('scenarios');
  container.innerHTML = '';
  for (const s of scenarios) {
    const card = document.createElement('button');
    card.className = 'scenario';
    card.type = 'button';
    card.setAttribute('aria-selected', String(s.id === selectedScenarioId));
    card.dataset.id = s.id;
    card.innerHTML = `
      <div class="scenario__title">${escapeHtml(s.titulo)}</div>
      <div class="scenario__desc">${escapeHtml(s.descripcion)}</div>
      <div class="scenario__tags">
        <span class="tag">rol: ${escapeHtml(s.role)}</span>
        <span class="tag">${escapeHtml(s.environment)}</span>
        <span class="tag">${escapeHtml(s.tool)}</span>
      </div>`;
    card.addEventListener('click', () => selectScenario(s.id));
    container.appendChild(card);
  }
}

function selectScenario(id: string): void {
  selectedScenarioId = id;
  renderScenarioCards();
  const scenario = scenarios.find((s) => s.id === id)!;
  $('controls').hidden = false;
  const toggleWrap = $('approve-toggle').closest('.switch') as HTMLElement;
  toggleWrap.style.display = scenario.permite_aprobacion ? 'flex' : 'none';
  ($('approve-toggle') as HTMLInputElement).checked = false;
  resetVisuals();
}

function resetVisuals(): void {
  for (const node of document.querySelectorAll('.cnode')) {
    node.className = 'cnode';
  }
  lastRun = null;
  $('verdict').hidden = true;
  $('trace-panel').hidden = true;
  $('replay-btn').hidden = true;
  // Si hay un panel de detalle abierto, refresca su pestaña de I/O (vacía ahora).
  if (openNodeKey) renderDetail(openNodeKey);
}

function nodeEl(key: string): HTMLElement | null {
  return document.getElementById(`node-${key}`);
}

function setNodeStatus(key: string, status: StepStatus, active: boolean): void {
  const node = nodeEl(key);
  if (!node) return;
  node.classList.remove('is-active');
  node.classList.add('s-' + status);
  if (active) node.classList.add('is-active');
}

// Busca el paso de la última corrida que corresponde a un nodo del diagrama.
function stepForNode(key: string): Step | null {
  if (!lastRun) return null;
  // Para 'outcome', el paso puede venir como execute/review/deny.
  const match = lastRun.steps.find((s) => nodeKeyFor(s.key) === key);
  return match ?? null;
}

// --- Panel de detalle (código + entrada/salida) ---

function openDetail(key: string): void {
  openNodeKey = key;
  for (const n of document.querySelectorAll('.cnode')) n.classList.remove('is-selected');
  nodeEl(key)?.classList.add('is-selected');
  renderDetail(key);
  $('detail').hidden = false;
  $('detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeDetail(): void {
  openNodeKey = null;
  for (const n of document.querySelectorAll('.cnode')) n.classList.remove('is-selected');
  $('detail').hidden = true;
}

function selectTab(tab: 'code' | 'io'): void {
  const codeTab = $('tab-code');
  const ioTab = $('tab-io');
  codeTab.classList.toggle('is-active', tab === 'code');
  ioTab.classList.toggle('is-active', tab === 'io');
  $('detail-code').hidden = tab !== 'code';
  $('detail-io').hidden = tab !== 'io';
}

function renderDetail(key: string): void {
  const snippet = snippets[key];
  $('detail-title').textContent = snippet ? snippet.title : key;
  $('detail-file').textContent = snippet ? snippet.file : '';
  $('detail-explain').textContent = snippet ? snippet.explanation : '';
  $('detail-code').textContent = snippet ? snippet.code : 'Código no disponible.';

  // Entrada / salida de la última corrida para esta etapa.
  const step = stepForNode(key);
  const empty = $('detail-io-empty');
  const summary = $('detail-io-summary');
  const dataPre = $('detail-io-data');
  if (step) {
    empty.hidden = true;
    summary.hidden = false;
    dataPre.hidden = false;
    summary.textContent = step.summary;
    dataPre.textContent = JSON.stringify(step.data, null, 2);
  } else {
    empty.hidden = false;
    summary.hidden = true;
    dataPre.hidden = true;
  }
  selectTab('code');
}

function showVerdict(run: RunResult): void {
  const v = $('verdict');
  v.hidden = false;
  v.className = `verdict a-${run.final_action}`;
  $('verdict-action').textContent = ACTION_LABEL[run.final_action] ?? run.final_action;
  const policy = run.steps.find((s) => s.key === 'policy');
  $('verdict-reason').textContent = policy?.summary ?? '';
  $('verdict-meta').textContent =
    `reason_code=${run.reason_code} · ejecutado=${run.executed} · latencia=${run.latency_ms} ms`;
}

async function runSelected(): Promise<void> {
  if (!selectedScenarioId || running) return;
  running = true;
  const runBtn = $('run-btn') as HTMLButtonElement;
  runBtn.disabled = true;
  resetVisuals();

  const approve = ($('approve-toggle') as HTMLInputElement).checked;
  let run: RunResult;
  try {
    const res = await fetch(`${API_BASE}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_id: selectedScenarioId, approve }),
    });
    if (res.status === 503) {
      const err = await res.json();
      $('api-status').textContent =
        `Proveedor Jev no disponible (${err.reason}). Exporta una TYPESAFE_API_KEY válida o usa --mock.`;
      $('api-status').className = 'pill pill--err';
      running = false;
      runBtn.disabled = false;
      return;
    }
    run = (await res.json()) as RunResult;
  } catch {
    $('api-status').textContent = 'No se pudo correr: ¿está el backend activo?';
    $('api-status').className = 'pill pill--err';
    running = false;
    runBtn.disabled = false;
    return;
  }

  lastRun = run;

  // Anima: ilumina cada nodo en secuencia.
  for (const step of run.steps) {
    const key = nodeKeyFor(step.key);
    setNodeStatus(key, step.status, true);
    await sleep(700);
    const node = nodeEl(key);
    node?.classList.remove('is-active');
  }

  showVerdict(run);
  $('trace').textContent = JSON.stringify(run, null, 2);
  $('trace-panel').hidden = false;
  $('replay-btn').hidden = false;

  // Si hay un detalle abierto, refréscalo con los datos nuevos.
  if (openNodeKey) renderDetail(openNodeKey);

  running = false;
  runBtn.disabled = false;
}

function wireNodeClicks(): void {
  for (const node of document.querySelectorAll<HTMLElement>('.cnode')) {
    const key = node.dataset.node!;
    node.addEventListener('click', () => {
      if (openNodeKey === key) {
        closeDetail();
      } else {
        openDetail(key);
      }
    });
  }
}

export function initApp(): void {
  checkHealth();
  loadSnippets();
  loadScenarios().catch(() => {
    $('scenarios').innerHTML =
      '<p style="color:var(--block)">No se pudieron cargar los escenarios. Inicia el backend Python.</p>';
  });
  wireNodeClicks();
  $('run-btn').addEventListener('click', runSelected);
  $('replay-btn').addEventListener('click', runSelected);
  $('detail-close').addEventListener('click', closeDetail);
  $('tab-code').addEventListener('click', () => selectTab('code'));
  $('tab-io').addEventListener('click', () => selectTab('io'));
}
