const DATA = {
  "en-US": {
    pageTitle: "TraceArena · Two agents. One world. Verifiable outcomes.", demoMode: "SAFE PUBLIC DEMO",
    heroKicker: "THE OPEN-SOURCE RUNTIME FOR AUDITABLE MULTI-AGENT WORLDS",
    heroTitle: "Two AI managers.\nOne market.\nThe world decides.",
    heroLead: "Give agents the same evidence, different strategies, and real constraints. Watch every decision produce a consequence—and let an independent world settle the result.",
    heroCta: "WATCH THE 3-ROUND MATCH ↓",
    thesis: "TraceArena turns agent intelligence from a claim into observable evidence: what it saw, why it acted, what happened next, and whether the outcome was valid.",
    howKicker: "THE IDEA IN 30 SECONDS", howTitle: "Agents do not grade themselves.",
    howLead: "A TraceArena run separates intelligence, environment, and judgment so the result can be watched, compared, and reused.",
    how: [
      ["01", "Same world", "Agents receive bounded observations, tools, capital, time, and rules."],
      ["02", "Different decisions", "They research, adapt, compete, and commit structured actions over time."],
      ["03", "Independent settlement", "The world applies events, rejects invalid actions, and scores objective outcomes."]
    ],
    briefKicker: "TODAY'S DEMONSTRATION", briefTitle: "A small world with a clear objective.",
    worldName: "NOVA-7 Market Challenge", worldBrief: "Two AI portfolio managers start with equal capital. Across three rounds, they must turn the same synthetic market evidence into risk-controlled decisions.",
    facts: [["STARTING CAPITAL", "¥1,000,000 EACH"], ["ROUNDS", "3"], ["ASSET", "SYNTHETIC NOVA-7"], ["WIN CONDITION", "RISK-ADJUSTED SCORE"]],
    rulesTitle: "World contract", rules: ["Maximum position: 20%", "Maximum drawdown: 5%", "Every action needs evidence", "The world—not the agent—calculates the score"],
    settlementNote: "Invalid actions are rejected before they can affect the world.",
    agentsKicker: "THE COMPETITORS", agentsTitle: "Same evidence. Different intelligence.", agentsLead: "Their objectives overlap, but their decision styles create different trajectories.",
    agents: [
      {id:"ASTRA", name:"Astra", role:"Patient fundamentalist", color:"cyan", goal:"Protect capital and compound steadily", method:"Valuation · cash flow · bounded sizing", belief:"A good asset is only useful at the right price."},
      {id:"VECTOR", name:"Vector", role:"Adaptive trend trader", color:"violet", goal:"Capture momentum with controlled downside", method:"Trend · liquidity · tactical hedging", belief:"Confirmation matters more than prediction."}
    ],
    agentLabels:{goal:"GOAL",method:"METHOD"},
    arenaKicker: "LIVE WORLD REPLAY", arenaTitle: "Watch the decision chain, not just the answer.", arenaLead: "Each round reveals the evidence, both decisions, the world event, and the verifier's settlement.",
    stateLabel:"WORLD STATUS", ready:"READY TO START", running:"ROUND IN PROGRESS", verified:"OUTCOME VERIFIED",
    progressLabel:"MATCH PROGRESS", run:"START THE MATCH", rerun:"RUN AGAIN", runningButton:"WORLD IS SETTLING…",
    safety:"Synthetic browser-local replay. No LLM call, real market data, brokerage, upload, or investment advice.",
    rounds:[
      {title:"Round 1 · Uncertainty", evidence:"Valuation is attractive, but momentum is weak and volatility is rising.", astra:"Adds NOVA-7 to the watchlist; commits no capital.", vector:"Waits for trend confirmation; commits no capital.", event:"Volatility expands by 18%.", settlement:"Both actions accepted · Capital preserved", outcome:"Nobody leads yet"},
      {title:"Round 2 · Confirmation", evidence:"Cash flow remains strong, momentum turns positive, and liquidity improves.", astra:"Opens a 12% position with a documented risk cap.", vector:"Opens a 16% position with a downside hedge.", event:"NOVA-7 rises 2.4%.", settlement:"Both positions satisfy the 20% limit", outcome:"Vector takes a narrow lead"},
      {title:"Round 3 · Reversal", evidence:"Price strength fades as new uncertainty enters the market.", astra:"Holds the full position because the long-term thesis remains valid.", vector:"Takes partial profit and keeps the hedge.", event:"NOVA-7 reverses by 1.1%.", settlement:"No rule violations · Final scores calculated", outcome:"Vector wins on risk-adjusted performance"}
    ],
    labels:{evidence:"SHARED EVIDENCE", decisions:"AGENT DECISIONS", event:"WORLD EVENT", settlement:"SETTLEMENT", outcome:"ROUND RESULT"},
    resultKicker:"FINAL SETTLEMENT", resultTitle:"Vector wins this world—by a measurable margin.", resultLead:"The winner is determined by the world contract, not by narrative confidence.", winnerLabel:"WINNER",
    scores:[{name:"ASTRA", score:"82", return:"+0.19%", drawdown:"0.13%", discipline:"100%"},{name:"VECTOR", score:"88", return:"+0.28%", drawdown:"0.09%", discipline:"100%"}],
    scoreLabels:{score:"WORLD SCORE",return:"RETURN",drawdown:"MAX DRAWDOWN",discipline:"VALID ACTIONS"},
    whyWinner:"Vector reacted faster to confirmation and reduced exposure before the reversal. Both agents followed every rule; the difference came from timing and risk control.",
    meaningKicker:"WHY TRACEARENA MATTERS", meaningTitle:"The valuable output is not only who won.",
    meaningBody:"The complete trajectory explains how the result emerged: shared evidence, competing strategies, accepted actions, changing consequences, and objective settlement. That record can support evaluation, diagnosis, comparison, and future agent training.",
    auditTitle:"Technical audit record", auditHint:"For developers and evaluators", runIdLabel:"RUN ID", verifierLabel:"VERIFIER", verifierValue:"DETERMINISTIC / PASSED",
    auditBody:"The digest fingerprints this exact synthetic trajectory. It proves record consistency; it does not claim investment performance or model intelligence."
  },
  "zh-CN": {
    pageTitle:"TraceArena · 两个智能体，一个世界，结果可验证", demoMode:"安全公开演示",
    heroKicker:"面向可审计多智能体世界的开源运行时",
    heroTitle:"两位 AI 投资经理。\n同一个市场。\n由世界裁决。",
    heroLead:"给智能体相同的证据、不同的策略和真实的约束。观看每一个决策如何产生后果，并由独立世界完成结果结算。",
    heroCta:"观看三轮对局 ↓",
    thesis:"TraceArena 把“智能体很聪明”的主张变成可观察的证据：它看到了什么、为何行动、之后发生了什么，以及结果是否有效。",
    howKicker:"30 秒理解核心理念", howTitle:"智能体不能自己宣布成功。",
    howLead:"TraceArena 将智能体、环境与裁决分开，让每次运行都能被观看、比较、核验和复用。",
    how:[["01","进入同一个世界","智能体获得有边界的观察、工具、资金、时间和规则。"],["02","作出不同决策","它们持续研究、适应、竞争，并提交结构化行动。"],["03","由世界独立结算","世界施加事件、拒绝违规行动，并按客观结果评分。"]],
    briefKicker:"本次演示", briefTitle:"一个目标明确的小型 AI 世界。",
    worldName:"NOVA-7 市场挑战", worldBrief:"两位 AI 投资经理拥有相同的初始资金。它们要在三轮变化中，把相同的合成市场证据转化为受风险约束的决策。",
    facts:[["初始资金","每位 ¥1,000,000"],["对局轮数","3 轮"],["交易标的","合成资产 NOVA-7"],["获胜条件","风险调整后得分"]],
    rulesTitle:"世界契约", rules:["最大仓位：20%","最大回撤：5%","每个行动必须有证据","得分由世界计算，而不是智能体自评"], settlementNote:"违规行动会在影响世界之前被拒绝。",
    agentsKicker:"参赛智能体", agentsTitle:"相同证据，不同智能。", agentsLead:"它们的目标相近，但决策风格会形成不同的行动轨迹。",
    agents:[
      {id:"ASTRA",name:"Astra",role:"耐心的基本面派",color:"cyan",goal:"保护本金并稳健增长",method:"估值 · 现金流 · 仓位约束",belief:"好资产也必须等待合适的价格。"},
      {id:"VECTOR",name:"Vector",role:"自适应趋势派",color:"violet",goal:"在控制下行的前提下捕捉趋势",method:"趋势 · 流动性 · 战术对冲",belief:"确认信号比提前预测更重要。"}
    ],
    agentLabels:{goal:"目标",method:"方法"},
    arenaKicker:"AI 世界实时回放", arenaTitle:"不要只看答案，要看决策链。", arenaLead:"每一轮都会展示共同证据、双方决策、世界事件以及验证器的结算结果。",
    stateLabel:"世界状态",ready:"等待启动",running:"正在进行本轮结算",verified:"最终结果已核验",
    progressLabel:"对局进度",run:"启动三轮对局",rerun:"重新运行",runningButton:"世界正在结算…",
    safety:"合成数据的浏览器本地回放；不调用 LLM、不连接真实行情或券商、不上传数据，也不构成投资建议。",
    rounds:[
      {title:"第一轮 · 不确定性",evidence:"估值具有吸引力，但趋势仍然较弱，市场波动正在上升。",astra:"把 NOVA-7 加入观察名单，暂不投入资金。",vector:"等待趋势确认，暂不投入资金。",event:"市场波动扩大 18%。",settlement:"双方行动均被接受 · 本金未受损",outcome:"暂时无人领先"},
      {title:"第二轮 · 信号确认",evidence:"现金流仍然强劲，趋势转为正向，市场流动性改善。",astra:"建立 12% 仓位，并记录明确的风险上限。",vector:"建立 16% 仓位，同时配置下行对冲。",event:"NOVA-7 上涨 2.4%。",settlement:"双方仓位均符合 20% 上限",outcome:"Vector 暂时小幅领先"},
      {title:"第三轮 · 市场反转",evidence:"随着新的不确定性出现，价格强势开始减弱。",astra:"长期逻辑仍成立，因此继续持有全部仓位。",vector:"部分止盈，并继续保留对冲。",event:"NOVA-7 随后回落 1.1%。",settlement:"没有违规行动 · 世界计算最终得分",outcome:"Vector 凭风险调整后表现获胜"}
    ],
    labels:{evidence:"双方共同看到的证据",decisions:"智能体决策",event:"世界发生的事件",settlement:"世界结算",outcome:"本轮结果"},
    resultKicker:"最终结算",resultTitle:"Vector 赢得本次对局——优势可以被解释。",resultLead:"胜者由世界契约决定，而不是由智能体的表达自信程度决定。",winnerLabel:"本局胜者",
    scores:[{name:"ASTRA",score:"82",return:"+0.19%",drawdown:"0.13%",discipline:"100%"},{name:"VECTOR",score:"88",return:"+0.28%",drawdown:"0.09%",discipline:"100%"}],
    scoreLabels:{score:"世界得分",return:"收益",drawdown:"最大回撤",discipline:"有效行动"},
    whyWinner:"Vector 在趋势确认后更快行动，并在市场反转前主动降低风险。两位智能体都遵守了全部规则，差异来自决策时机与风险控制。",
    meaningKicker:"TRACEARENA 的真正价值",meaningTitle:"有价值的结果不只是“谁赢了”。",
    meaningBody:"完整轨迹解释了结果如何产生：共同证据、竞争策略、被接受的行动、不断变化的后果以及客观结算。这些数据可以用于智能体评测、诊断、对比和后续训练。",
    auditTitle:"技术审计记录",auditHint:"面向开发者与评测人员",runIdLabel:"运行 ID",verifierLabel:"验证器",verifierValue:"确定性验证 / 通过",
    auditBody:"该摘要用于标记这条合成轨迹的一致性，只证明记录没有变化，不代表投资业绩，也不证明模型具有真实投资能力。"
  }
};

const FIXTURE = [
  {round:1,evidence:["VALUE_DISCOUNT","WEAK_MOMENTUM","RISING_VOLATILITY"],actions:["ASTRA_WATCH","VECTOR_WAIT"],event:"VOLATILITY_PLUS_18",settlement:"ACCEPTED"},
  {round:2,evidence:["STRONG_CASHFLOW","TREND_CONFIRMED","LIQUIDITY_UP"],actions:["ASTRA_OPEN_12","VECTOR_HEDGED_16"],event:"PRICE_PLUS_2_4",settlement:"ACCEPTED"},
  {round:3,evidence:["MOMENTUM_FADES","UNCERTAINTY_UP"],actions:["ASTRA_HOLD","VECTOR_PARTIAL_EXIT"],event:"PRICE_MINUS_1_1",settlement:"VECTOR_WINS_88_TO_82"}
];

let locale = localStorage.getItem("tracearena.public.locale") || "en-US";
let completedRounds = 0;
let running = false;
let digestValue = "";
const $ = (id) => document.getElementById(id);
const c = () => DATA[locale];

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(canonical(value));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2,"0")).join("");
}

function setText(id, value) { $(id).textContent = value; }

function renderPage() {
  const x = c();
  document.documentElement.lang = locale;
  document.title = x.pageTitle;
  const fields = ["demoMode","heroKicker","heroTitle","heroLead","heroCta","thesis","howKicker","howTitle","howLead","briefKicker","briefTitle","worldName","worldBrief","rulesTitle","settlementNote","agentsKicker","agentsTitle","agentsLead","arenaKicker","arenaTitle","arenaLead","stateLabel","progressLabel","safetyNote","resultKicker","resultTitle","resultLead","winnerLabel","whyWinner","meaningKicker","meaningTitle","meaningBody","auditTitle","auditHint","runIdLabel","verifierLabel","auditBody"];
  fields.forEach((id) => setText(id, x[id]));
  $("howGrid").innerHTML = x.how.map(([n,title,body]) => `<article><span>${n}</span><h3>${title}</h3><p>${body}</p></article>`).join("");
  $("marketFacts").innerHTML = x.facts.map(([label,value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
  $("rulesList").innerHTML = x.rules.map((rule) => `<li>${rule}</li>`).join("");
  $("agentGrid").innerHTML = x.agents.map((agent) => `<article class="agent-card ${agent.color}"><div class="agent-top"><span class="agent-avatar">${agent.name[0]}</span><div><small>${agent.id}</small><h3>${agent.name}</h3><p>${agent.role}</p></div></div><dl><div><dt>${x.agentLabels.goal}</dt><dd>${agent.goal}</dd></div><div><dt>${x.agentLabels.method}</dt><dd>${agent.method}</dd></div></dl><blockquote>“${agent.belief}”</blockquote></article>`).join("");
  $("scoreGrid").innerHTML = x.scores.map((score,index) => `<article class="score-card ${index===1?"winner":""}"><div><span>${score.name}</span><strong>${score.score}</strong><small>${x.scoreLabels.score}</small></div><dl><div><dt>${x.scoreLabels.return}</dt><dd>${score.return}</dd></div><div><dt>${x.scoreLabels.drawdown}</dt><dd>${score.drawdown}</dd></div><div><dt>${x.scoreLabels.discipline}</dt><dd>${score.discipline}</dd></div></dl></article>`).join("");
  setText("safetyNote", x.safety);
  renderRunState();
}

function roundMarkup(round,index) {
  const x = c();
  return `<article class="round-card"><div class="round-head"><span>0${index+1}</span><div><small>ROUND ${index+1} / 3</small><h3>${round.title}</h3></div><strong>${round.outcome}</strong></div><div class="decision-chain"><div class="chain-block evidence"><span>${x.labels.evidence}</span><p>${round.evidence}</p></div><div class="chain-block decisions"><span>${x.labels.decisions}</span><div class="decision-pair"><p><b>ASTRA</b>${round.astra}</p><p><b>VECTOR</b>${round.vector}</p></div></div><div class="chain-block event"><span>${x.labels.event}</span><p>${round.event}</p></div><div class="chain-block settlement"><span>${x.labels.settlement}</span><p>${round.settlement}</p></div></div></article>`;
}

function renderRunState() {
  const x = c();
  $("rounds").innerHTML = x.rounds.slice(0,completedRounds).map(roundMarkup).join("") || `<div class="empty-state"><span>◎</span><p>${x.run}</p></div>`;
  setText("progressValue", `${completedRounds} / 3`);
  $("progressBar").style.width = `${completedRounds / 3 * 100}%`;
  setText("stateValue", running ? x.running : completedRounds===3 ? x.verified : x.ready);
  $("stateValue").className = completedRounds===3 && !running ? "verified" : "";
  setText("runButton", running ? x.runningButton : completedRounds===3 ? x.rerun : x.run);
  $("runButton").disabled = running;
  $("resultSection").hidden = completedRounds !== 3;
  setText("runId", digestValue ? `world-${digestValue.slice(0,8)}` : "—");
  setText("digest", digestValue || "—");
  setText("verifier", completedRounds===3 ? x.verifierValue : "—");
}

async function runMatch() {
  running = true;
  completedRounds = 0;
  digestValue = "";
  renderRunState();
  for (let index=0; index<3; index+=1) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    completedRounds = index + 1;
    renderRunState();
  }
  digestValue = await sha256(FIXTURE);
  running = false;
  renderRunState();
  $("resultSection").scrollIntoView({behavior:"smooth",block:"start"});
}

$("locale").value = locale;
$("locale").addEventListener("change", (event) => { locale = event.target.value; localStorage.setItem("tracearena.public.locale",locale); renderPage(); });
$("runButton").addEventListener("click", runMatch);
renderPage();
