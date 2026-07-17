/**
 * OS 层运营台「本回合全过程」链路模型（按结算类型 ID 套用）。
 *
 * 场景包只声明 process_chain_type / settlement 默认 mode；
 * 不得在 Console 里按 scenario_name 分流。
 *
 * 合法 ID 与 backend/app/contracts/settlement_types.py 对齐：
 * simulation | external_reality | deterministic_verifier | hybrid
 */

export const PROCESS_CHAIN_TYPE_IDS = [
  'simulation',
  'external_reality',
  'deterministic_verifier',
  'hybrid',
]

/**
 * @typedef {{ id: string, label: string, css: string, optional?: boolean }} ProcessStepDef
 * @typedef {{ type_id: string, label: string, empty_hint: string, steps: ProcessStepDef[] }} ProcessChainProfile
 * @typedef {{
 *   type_id: string,
 *   label: string,
 *   summary: string,
 *   empty_hint: string,
 *   focus: string[],
 * }} SettlementExplainProfile
 */

/** @type {Record<string, ProcessChainProfile>} */
export const PROCESS_CHAIN_PROFILES = {
  simulation: {
    type_id: 'simulation',
    label: '模拟世界决策链',
    empty_hint: '开局后按「注入 → 怎么想 → 输出 → 读懂 → 世界结果 → 结算数值」展开每位 Agent。',
    steps: [
      { id: 'perceive', label: '注入内容', css: 'step-see' },
      { id: 'think', label: '怎么想的', css: 'step-think' },
      { id: 'said', label: '输出内容', css: 'step-say' },
      { id: 'parsed', label: '读懂动作', css: 'step-parse' },
      { id: 'settle', label: '世界结果', css: 'step-judge', optional: true },
      { id: 'metrics', label: '结算数值', css: 'step-metric' },
    ],
  },
  external_reality: {
    type_id: 'external_reality',
    label: '外部现实观测链',
    empty_hint: '开局后按「任务注入 → 观测计划 → 外部回传 → 来源校验 → 现实结果」展开。',
    steps: [
      { id: 'perceive', label: '任务注入', css: 'step-see' },
      { id: 'think', label: '观测计划', css: 'step-think' },
      { id: 'said', label: '外部回传', css: 'step-say' },
      { id: 'parsed', label: '来源校验', css: 'step-parse' },
      { id: 'settle', label: '现实结果', css: 'step-judge', optional: true },
      { id: 'metrics', label: '结算数值', css: 'step-metric' },
    ],
  },
  deterministic_verifier: {
    type_id: 'deterministic_verifier',
    label: '确定性校验链',
    empty_hint: '开局后按「题目注入 → 提交内容 → 结构化答案 → 校验裁决 → 得分」展开。',
    steps: [
      { id: 'perceive', label: '题目注入', css: 'step-see' },
      { id: 'said', label: '提交内容', css: 'step-say' },
      { id: 'parsed', label: '结构化答案', css: 'step-parse' },
      { id: 'settle', label: '校验裁决', css: 'step-judge', optional: true },
      { id: 'metrics', label: '得分结果', css: 'step-metric' },
    ],
  },
  hybrid: {
    type_id: 'hybrid',
    label: '投资/混合决策链',
    empty_hint:
      '开局后按「注入内容 → 怎么想的 → 输出内容 → 提交订单 → 成交结果 → 账本」展开每位 Agent。',
    steps: [
      { id: 'perceive', label: '注入内容', css: 'step-see' },
      { id: 'think', label: '怎么想的', css: 'step-think' },
      { id: 'said', label: '输出内容', css: 'step-say' },
      { id: 'parsed', label: '提交订单', css: 'step-parse' },
      { id: 'settle', label: '成交结果', css: 'step-judge', optional: true },
      { id: 'metrics', label: '账本结果', css: 'step-metric' },
    ],
  },
}

/**
 * 右栏「可解释结算」按同一 4 类 ID 套用说明骨架（与左 3 决策链解耦）。
 * @type {Record<string, SettlementExplainProfile>}
 */
export const SETTLEMENT_EXPLAIN_PROFILES = {
  simulation: {
    type_id: 'simulation',
    label: '模拟世界结算',
    summary: '结果由场景规则/世界物理加工，不依赖外部真实行情。本栏只解释「本回合如何结算」。',
    empty_hint: '开局并产生结算后，这里会说明规则依据、结果与数值变化。',
    focus: ['outcome', 'authority', 'values', 'rule'],
  },
  external_reality: {
    type_id: 'external_reality',
    label: '外部现实结算',
    summary: '结果来自外部真实世界观测；OS 只核验来源与新鲜度，不编造答案。',
    empty_hint: '开局后将展示已验证观测、来源与对应结算说明。',
    focus: ['outcome', 'evidence', 'authority', 'values'],
  },
  deterministic_verifier: {
    type_id: 'deterministic_verifier',
    label: '确定性校验结算',
    summary: '由可复现校验器判对错/是否合法，不经 LLM 裁判。',
    empty_hint: '提交并校验后，这里会展示裁决、规则版本与得分。',
    focus: ['outcome', 'authority', 'values', 'rule'],
  },
  hybrid: {
    type_id: 'hybrid',
    label: '混合结算（现实行情 + 场景账本）',
    summary:
      '外部观测与场景账本共同决定结果。本栏解释本回合「为什么这样结算」。',
    empty_hint: '产生结算后，这里会拆开：证据 → 结果说明 → 场景账本 → 数值变化。',
    focus: ['outcome', 'evidence', 'ledger', 'values', 'authority'],
  },
}

/** HarnessStep.kind → 运营台中文标签 */
export const HARNESS_STEP_KIND_LABELS = {
  perceive: '感知',
  plan: '规划',
  discover_tool: '发现能力',
  install_tool: '安装工具',
  execute_tool: '调用工具',
  write_code: '写代码',
  run_code: '跑代码',
  observe: '观察结果',
  reflect: '反思',
  submit_action: '提交动作',
}

function _asText(value, limit = 280) {
  if (value == null) return ''
  if (typeof value === 'string') return value.trim().slice(0, limit)
  try {
    return JSON.stringify(value, null, 0).slice(0, limit)
  } catch {
    return String(value).slice(0, limit)
  }
}

function _extractCode(details = {}) {
  if (!details || typeof details !== 'object') return ''
  for (const key of ['code', 'source_code', 'script', 'python', 'content']) {
    const v = details[key]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return ''
}

/**
 * 把 harness_trace（或 tool_activity 兜底）整理成可复用摘要结构（当前左栏不单独展示该节点）。
 * @param {object|null|undefined} harnessTrace
 * @param {Array<object>} [toolActivity]
 */
export function summarizeHarnessLoop(harnessTrace, toolActivity = []) {
  const steps = Array.isArray(harnessTrace?.steps) ? harnessTrace.steps : []
  if (steps.length) {
    const productive = steps.filter(
      (s) => !['perceive', 'submit_action'].includes(String(s?.kind || '')),
    )
    const tools = productive.filter((s) =>
      ['discover_tool', 'install_tool', 'execute_tool'].includes(String(s?.kind || '')),
    )
    const codes = productive.filter((s) =>
      ['write_code', 'run_code'].includes(String(s?.kind || '')),
    )
    const status = String(harnessTrace.status || '')
    const statusZh = ({
      completed: '完成',
      failed: '失败',
      blocked: '阻塞',
      budget_exhausted: '预算耗尽',
      running: '进行中',
    })[status] || status || '未知'
    return {
      summary: `Agent Loop ${steps.length} 步 · 工具 ${tools.length} · 代码 ${codes.length} · ${statusZh}`,
      steps: steps.map((s, i) => {
        const details = (s && typeof s.details === 'object' && s.details) || {}
        const code = _extractCode(details)
        const summaryText = _asText(s.public_summary, 360)
        const extra = []
        if (details.source) extra.push(`来源 ${details.source}`)
        if (Array.isArray(details.errors) && details.errors.length) {
          extra.push(`错误 ${details.errors.slice(0, 2).join('；')}`)
        }
        return {
          key: String(s.step_id || `${s.kind}-${i}`),
          kind: String(s.kind || ''),
          label: HARNESS_STEP_KIND_LABELS[s.kind] || String(s.kind || '步骤'),
          status: String(s.status || ''),
          text: summaryText,
          meta: extra.join(' · '),
          code,
          duration_ms: Number(s.duration_ms || 0),
        }
      }),
      raw: harnessTrace,
    }
  }

  const tools = Array.isArray(toolActivity) ? toolActivity : []
  if (tools.length) {
    return {
      summary: `本回合公开工具活动 ${tools.length} 条（无完整 Harness 轨迹时的兜底）`,
      steps: tools.map((t, i) => ({
        key: `tool-${i}-${t.tool_id || t.run_id || i}`,
        kind: 'execute_tool',
        label: HARNESS_STEP_KIND_LABELS.execute_tool,
        status: t.ok === false ? 'failed' : 'succeeded',
        text: _asText(t.summary || t.tool_id || t.tool, 360),
        meta: t.source ? `来源 ${t.source}` : '',
        code: '',
        duration_ms: Number(t.duration_ms || 0),
      })),
      raw: { tool_activity: tools },
    }
  }

  return {
    summary: '',
    steps: [],
    raw: null,
  }
}

/**
 * @param {string | null | undefined} typeId
 * @returns {ProcessChainProfile}
 */
export function resolveProcessChainProfile(typeId) {
  const key = String(typeId || '').trim()
  if (PROCESS_CHAIN_PROFILES[key]) return PROCESS_CHAIN_PROFILES[key]
  return PROCESS_CHAIN_PROFILES.simulation
}

/**
 * @param {string | null | undefined} typeId
 * @returns {SettlementExplainProfile}
 */
export function resolveSettlementExplainProfile(typeId) {
  const key = String(typeId || '').trim()
  if (SETTLEMENT_EXPLAIN_PROFILES[key]) return SETTLEMENT_EXPLAIN_PROFILES[key]
  return SETTLEMENT_EXPLAIN_PROFILES.simulation
}

/**
 * 从运营 schema 解析场景声明的链路类型 ID。
 * 优先 operator_trace.process_chain_type；
 * 其次看 execution 路由是否声明了 hybrid；
 * 最后回退 execution.default.mode。
 */
export function processChainTypeFromSchema(schema = {}) {
  const trace = schema.operator_trace || {}
  const explicit = trace.process_chain_type || trace.profile_id || trace.chain_type
  if (explicit) return String(explicit).trim()

  const routes = schema.execution?.routes || {}
  const routeModes = Object.values(routes).map((r) => String(r?.mode || ''))
  if (routeModes.includes('hybrid')) return 'hybrid'

  const mode = schema.execution?.default?.mode
  if (mode) return String(mode).trim()
  return 'simulation'
}
