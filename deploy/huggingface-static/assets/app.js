const COPY = {
  "en-US": {
    eyebrow: "A VERIFIABLE MULTI-AGENT WORLD", title: "WATCH INTELLIGENCE\nACT UNDER CONSTRAINT.",
    subtitle: "Run a bounded TraceArena world where two agents share rules, compete for outcomes, and leave an auditable trajectory.",
    scenarioLabel: "INTERACTIVE PUBLIC DEMO", scenarioTitle: "Synthetic Market Decision World",
    scenarioBody: "Two agents receive the same synthetic evidence but pursue different objectives. The world accepts structured actions, applies events, and settles outcomes independently.",
    run: "RUN THE AI WORLD", running: "WORLD RUNNING…",
    notice: "Runs locally in your browser. No model call, real market data, brokerage connection, upload, or financial advice.",
    status: "WORLD STATUS", ready: "READY", done: "VERIFIED", failed: "FAILED",
    runId: "RUN ID", ticks: "TRAJECTORY STEPS", trajectoryLabel: "AUDIT TRAJECTORY",
    trajectoryTitle: "Evidence. Actions. Consequences.", empty: "Run the world to generate a verifiable trajectory.",
    step: "STEP", actions: "actions", events: "events", settlements: "settlements"
  },
  "zh-CN": {
    eyebrow: "可验证的多智能体世界", title: "观看智能体在约束中\n采取行动。",
    subtitle: "运行一个共享规则、竞争目标并留下完整审计轨迹的 TraceArena AI 世界。",
    scenarioLabel: "交互式公开演示", scenarioTitle: "合成市场决策世界",
    scenarioBody: "两个智能体获得相同的合成证据，但目标与风险偏好不同。世界接收结构化行动、施加事件，并独立完成结果结算。",
    run: "启动 AI 世界", running: "世界运行中…",
    notice: "完全在浏览器本地运行；不调用模型、不接真实行情或券商、不上传数据，也不构成投资建议。",
    status: "世界状态", ready: "就绪", done: "核验通过", failed: "运行失败",
    runId: "运行 ID", ticks: "轨迹步数", trajectoryLabel: "审计轨迹", trajectoryTitle: "证据、行动与后果",
    empty: "启动世界后将在这里生成可验证轨迹。", step: "步骤", actions: "行动", events: "事件", settlements: "结算"
  }
};

const FIXTURE = [
  {tick: 1, world_actions: [
    {agent: "Astra", action: "BUILD_WATCHLIST", evidence: ["SYN-VAL-01", "SYN-CF-01"], thesis: "Quality and cash-flow resilience"},
    {agent: "Vector", action: "WAIT_FOR_CONFIRMATION", evidence: ["SYN-TA-01", "SYN-DEPTH-01"], thesis: "Momentum is not yet confirmed"}
  ], world_events: [{type: "VOLATILITY_EXPANDS", impact: "Risk budget reduced by 15%"}], settlements: [{authority: "world_rules", result: "BOTH_ACTIONS_ACCEPTED"}]},
  {tick: 2, world_actions: [
    {agent: "Astra", action: "OPEN_BOUNDED_POSITION", evidence: ["SYN-FUND-02", "SYN-RISK-01"], thesis: "Position capped at 12%"},
    {agent: "Vector", action: "OPEN_HEDGED_POSITION", evidence: ["SYN-MACD-02", "SYN-RISK-02"], thesis: "Confirmation arrived with hedge"}
  ], world_events: [{type: "PRICE_REPRICES", impact: "Synthetic asset +2.4%"}], settlements: [{authority: "deterministic_verifier", result: "CONSTRAINTS_SATISFIED"}]},
  {tick: 3, world_actions: [
    {agent: "Astra", action: "HOLD_AND_DOCUMENT", evidence: ["SYN-OUTCOME-01"], thesis: "Thesis remains inside risk bounds"},
    {agent: "Vector", action: "TAKE_PARTIAL_PROFIT", evidence: ["SYN-OUTCOME-01", "SYN-LIQ-01"], thesis: "Protect short-horizon objective"}
  ], world_events: [{type: "RUN_CLOSED", impact: "No rejected or unauthorized actions"}], settlements: [{authority: "canonical_replay", result: "VERIFIED_TRAJECTORY"}]}
];

let locale = localStorage.getItem("tracearena.public.locale") || "en-US";
let run = null;
const $ = (id) => document.getElementById(id);
const t = (key) => COPY[locale][key];
const ticks = () => run?.replay?.ticks || [];

function canonicalString(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalString).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalString(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(canonicalString(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function render() {
  document.documentElement.lang = locale;
  document.title = `TraceArena · ${t("scenarioTitle")}`;
  for (const [id, key] of [["eyebrow", "eyebrow"], ["title", "title"], ["subtitle", "subtitle"], ["scenarioLabel", "scenarioLabel"], ["scenarioTitle", "scenarioTitle"], ["scenarioBody", "scenarioBody"], ["runButton", "run"], ["notice", "notice"], ["statusLabel", "status"], ["runLabel", "runId"], ["tickLabel", "ticks"], ["trajectoryLabel", "trajectoryLabel"], ["trajectoryTitle", "trajectoryTitle"]]) $(id).textContent = t(key);
  $("statusValue").textContent = run ? t("done") : t("ready");
  $("runValue").textContent = run?.run_id || "—";
  $("tickValue").textContent = run ? String(ticks().length) : "—";
  $("digestValue").textContent = run?.manifest?.canonical_replay_sha256?.slice(0, 18) || "—";
  const timeline = $("timeline"); timeline.replaceChildren();
  if (!run) {
    const item = document.createElement("li"); item.className = "empty"; item.textContent = t("empty"); timeline.append(item); return;
  }
  ticks().forEach((frame, index) => {
    const item = document.createElement("li");
    const number = document.createElement("b"); number.textContent = String(index + 1).padStart(2, "0");
    const body = document.createElement("div");
    const title = document.createElement("strong"); title.textContent = `${t("step")} ${frame.tick}`;
    const meta = document.createElement("span"); meta.textContent = `${frame.world_actions.length} ${t("actions")} · ${frame.world_events.length} ${t("events")} · ${frame.settlements.length} ${t("settlements")}`;
    const detail = document.createElement("span"); detail.textContent = frame.world_actions.map((action) => `${action.agent}: ${action.action}`).join(" / ");
    body.append(title, meta, detail); item.append(number, body); timeline.append(item);
  });
}

$("locale").value = locale;
$("locale").onchange = (event) => { locale = event.target.value; localStorage.setItem("tracearena.public.locale", locale); render(); };
$("runButton").onclick = async () => {
  const button = $("runButton"); button.disabled = true; button.textContent = t("running");
  try {
    await new Promise((resolve) => setTimeout(resolve, 650));
    const digest = await sha256(FIXTURE);
    run = {run_id: `local-${digest.slice(0, 8)}`, replay: {ticks: FIXTURE}, manifest: {canonical_replay_sha256: digest}};
    render();
  } catch (error) {
    console.error("TraceArena browser replay failed", error); $("statusValue").textContent = t("failed");
  } finally {
    button.disabled = false; button.textContent = t("run");
  }
};
render();
