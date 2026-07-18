<template>
  <div class="app-shell">

    <div class="main-row">

      <div class="canvas-col">
        <div ref="mountEl" class="scene-area"></div>

        <!-- 仪表盘演绎形态：由场景包 presentation.render_mode=dashboard 触发。
             两位经理各占一区，内容全部来自场景数据；OS 只负责渲染。 -->
        <div v-if="dashboardMode" class="scene-dashboard">
          <div class="sd-head">
            <div class="sd-title">{{ uiText('title', '') || scenarioDisplayName }}</div>
            <div class="sd-sub">{{ uiText('subtitle', '') }}</div>
          </div>
          <div class="sd-zones">
            <article v-for="agent in dashboardAgents" :key="agent.agentId"
                     class="sd-zone" :class="{ leading: agent.leading, dead: agent.eliminated }"
                     :style="{ '--z': agent.color }">
              <header class="sd-zone-head">
                <div class="sd-avatar" :style="agent.avatarUrl ? {} : { background: agent.color }">
                  <img v-if="agent.avatarUrl" class="sd-avatar-img" :src="agent.avatarUrl" :alt="agent.name" />
                  <template v-else>{{ agent.badge }}</template>
                </div>
                <div class="sd-id">
                  <div class="sd-name">{{ agent.name }}</div>
                  <div class="sd-role">{{ agent.roleTitle }}</div>
                </div>
                <div class="sd-rank" :class="{ hot: agent.leading }">
                  {{ agent.eliminated ? uiText('ranking_eliminated', '已退出')
                     : (agent.leading ? uiText('ranking_leading', '领先') : ('第 ' + agent.rank)) }}
                </div>
              </header>
              <div class="sd-primary">
                <span class="sd-primary-label">{{ dashboardPrimaryLabel }}</span>
                <span class="sd-primary-val">{{ agent.scoreLabel }}</span>
              </div>
              <div class="sd-metrics">
                <div v-for="m in agent.metrics" :key="m.id" class="sd-metric" :class="m.tone">
                  <span class="sd-metric-label">{{ m.label }}</span>
                  <span class="sd-metric-val">{{ m.value }}</span>
                </div>
                <div v-if="!agent.metrics.length && uiText('empty_metric_label', '')" class="sd-metric neutral">
                  <span class="sd-metric-label">{{ uiText('empty_metric_label', '') }}</span>
                  <span class="sd-metric-val">{{ uiText('empty_metric_value', '') }}</span>
                </div>
              </div>
              <div v-if="uiText('holdings_label', '')" class="sd-holdings">
                <div class="sd-holdings-label">{{ uiText('holdings_label', '') }}</div>
                <div v-if="agent.holdings.length" class="sd-holdings-list">
                  <div v-for="h in agent.holdings" :key="h.asset_id" class="sd-holding-row">
                    <span class="sd-holding-name" :title="h.asset_id">
                      <b>{{ h.name || formatHoldingName(h.asset_id) }}</b>
                      <i v-if="h.name">{{ formatHoldingName(h.asset_id) }}</i>
                    </span>
                    <span class="sd-holding-qty">{{ formatHoldingQty(h.quantity) }}股</span>
                    <span class="sd-holding-cost">买入 {{ formatHoldingPrice(h.avg_cost) }}</span>
                  </div>
                </div>
                <div v-else class="sd-holdings-empty">{{ uiText('holdings_empty', '') }}</div>
              </div>
              <div class="sd-strategy">
                <div class="sd-strategy-label">{{ uiText('thoughts_title', '操盘思路') }}</div>
                <p v-if="agent.monologue" class="sd-strategy-text">{{ agent.monologue }}</p>
                <p v-else class="sd-strategy-empty">等待本回合独白…</p>
              </div>
              <div class="sd-strategy sd-invest">
                <div class="sd-strategy-label">
                  {{ uiText('strategy_title', '投资策略') }}
                  <em>{{ uiText('strategy_source', '思维链') }}</em>
                </div>
                <p v-if="agent.strategy" class="sd-strategy-text">{{ agent.strategy }}</p>
                <p v-else class="sd-strategy-empty">等待本回合策略摘要…</p>
              </div>
            </article>
          </div>
        </div>

        <!-- 场景挑战开始时展示场景包提供的里程碑信息 -->
        <transition name="challenge-fade">
          <div v-if="currentMilestone" class="challenge-banner" :key="currentMilestone.id">
            <div class="challenge-order">{{ milestoneEyebrow(currentMilestone) }}</div>
            <div class="challenge-title">{{ currentMilestone.title }}</div>
            <div class="challenge-subline">{{ milestoneSubline(currentMilestone) }}</div>
          </div>
        </transition>

        <!-- 全场景加载覆盖层 -->
        <div v-if="scenarioSwitching || ((isComputing || waitingMessage) && narrativeFeed.length === 0)" class="scene-loading-overlay">
          <div class="loading-orb">
            <div class="loading-ring r1"></div>
            <div class="loading-ring r2"></div>
            <div class="loading-ring r3"></div>
            <div class="loading-core"></div>
          </div>
          <div class="loading-text">{{ scenarioSwitching ? '正在切换世界…' : (waitingMessage || 'AI 智能体正在推演中...') }}</div>
          <div class="loading-hint">{{ scenarioSwitching ? '正在原子加载场景规则、角色与视听资源' : '每个回合需要调用 AI 模型进行决策，请耐心等待' }}</div>
        </div>

        <!-- 场景右下角持续加载指示器 -->
        <div v-if="(isComputing || waitingMessage) && narrativeFeed.length > 0" class="scene-mini-loader">
          <div class="mini-loader-dots">
            <span></span><span></span><span></span>
          </div>
          <span>{{ waitingMessage || '推演中...' }}</span>
        </div>

        <div class="hud-tl">
          <div class="brand-mark">
            <div class="brand-glyph">
              <svg viewBox="0 0 64 64" fill="none" aria-label="AI World">
                <defs>
                  <linearGradient id="brand-core" x1="10" y1="8" x2="55" y2="58">
                    <stop stop-color="#B9F5FF"/>
                    <stop offset=".42" stop-color="#00D4FF"/>
                    <stop offset="1" stop-color="#8B5CF6"/>
                  </linearGradient>
                  <linearGradient id="brand-orbit" x1="5" y1="10" x2="61" y2="52">
                    <stop stop-color="#00D4FF" stop-opacity=".15"/>
                    <stop offset=".5" stop-color="#7C3AED"/>
                    <stop offset="1" stop-color="#FF4DA6" stop-opacity=".18"/>
                  </linearGradient>
                  <radialGradient id="brand-glow">
                    <stop stop-color="#00D4FF" stop-opacity=".5"/>
                    <stop offset="1" stop-color="#00D4FF" stop-opacity="0"/>
                  </radialGradient>
                </defs>
                <circle cx="32" cy="32" r="29" fill="url(#brand-glow)" opacity=".22"/>
                <g class="brand-orbit orbit-a">
                  <path d="M9 35C15 16 35 7 53 17" stroke="url(#brand-orbit)" stroke-width="2.2" stroke-linecap="round"/>
                  <circle cx="53" cy="17" r="2.4" fill="#A78BFA"/>
                </g>
                <g class="brand-orbit orbit-b">
                  <path d="M12 45C27 57 50 50 56 31" stroke="url(#brand-orbit)" stroke-width="1.5" stroke-linecap="round"/>
                  <circle cx="12" cy="45" r="1.8" fill="#00D4FF"/>
                </g>
                <path d="M32 12L48 21.5V40.5L32 50L16 40.5V21.5L32 12Z" fill="rgba(3,9,22,.82)" stroke="url(#brand-core)" stroke-width="2.2"/>
                <path d="M32 19L42 25V37L32 43L22 37V25L32 19Z" fill="url(#brand-core)" opacity=".14" stroke="#71E7FF" stroke-width="1.2"/>
                <path d="M25 35.5L28.5 25.5L32 33L35.5 25.5L39 35.5" stroke="url(#brand-core)" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>
                <circle cx="32" cy="32" r="2.2" fill="#E8FCFF" class="brand-core-dot"/>
              </svg>
            </div>
            <div class="brand-text">
              <span class="brand-name"><b>AI</b> WORLD</span>
              <span class="brand-sub">MULTI-AGENT ARENA OS</span>
            </div>
          </div>
          <span v-if="snapshot.tick > 0" class="tick-pill tick-pill-playback" title="前台画面和导演演出当前播放到的回合">
            <span class="tick-dot"></span>
            <span class="tick-label">播放</span>T{{ snapshot.tick }}
          </span>
          <span v-if="computedTick > snapshot.tick" class="tick-pill tick-pill-engine" title="后台引擎已经计算完成、正在等待前台播放的回合">
            <span class="tick-label">计算</span>T{{ computedTick }}
          </span>
          <span v-if="snapshot.is_game_over" class="win-pill">
            <svg class="win-icon" viewBox="0 0 20 20" fill="currentColor"><path d="M10 1l2.39 4.84 5.34.78-3.87 3.77.91 5.32L10 13.27l-4.77 2.51.91-5.32L2.27 6.69l5.34-.78z"/></svg>
            {{ agentName(snapshot.winner_id) }} 胜出
          </span>
          <!-- Buffer 状态指示 -->
          <span v-if="isComputing" class="computing-pill">
            <span class="computing-dot"></span>
            <span class="computing-text">推演中</span>
          </span>
          <span v-if="waitingMessage && !isComputing" class="computing-pill computing-waiting">
            <span class="computing-dot"></span>
            <span class="computing-text">{{ waitingMessage }}</span>
          </span>
          <span v-if="bufferSize > 0" :class="['buffer-pill', `bh-${bufferHealth}`]">
            <span class="buffer-bar">
              <span class="buffer-fill" :style="{ width: Math.min(100, bufferAheadMs / 60000 * 100) + '%' }"></span>
            </span>
            <span class="buffer-label">{{ Math.round(bufferAheadMs / 1000) }}s</span>
          </span>
        </div>

        <button class="scene-notice-book" :title="uiText('notice_tooltip', '查看场景说明')" @click="openScenarioNotice">
          <svg viewBox="0 0 32 32" aria-hidden="true">
            <path d="M5.5 5.5c4.2-.8 7.3.1 10.5 2.5v18c-3.2-2.4-6.3-3.3-10.5-2.5v-18Z"/>
            <path d="M26.5 5.5c-4.2-.8-7.3.1-10.5 2.5v18c3.2-2.4 6.3-3.3 10.5-2.5v-18Z"/>
            <path d="M8.5 10.5c1.8-.1 3.3.3 4.8 1.2M8.5 14c1.8-.1 3.3.3 4.8 1.2M23.5 10.5c-1.8-.1-3.3.3-4.8 1.2M23.5 14c-1.8-.1-3.3.3-4.8 1.2"/>
          </svg>
          <span>{{ uiText('notice_label', '场景说明') }}</span>
        </button>

        <div class="hud-tr">
          <button class="hud-btn" :disabled="isResetting" title="开始 / 继续推演" @click="handlePlay()">▶</button>
          <button class="hud-btn" :disabled="isResetting" title="暂停" @click="handlePause()">⏸</button>
          <button class="hud-btn" :disabled="isResetting" title="重置本局" @click="handleReset()">↺</button>
          <div class="hud-sep"></div>
          <button :class="['hud-btn', 'btn-cfg', { active: showConfig }]" title="模型配置" @click="showConfig = !showConfig">⚙</button>
          <button
            v-if="canAccessOperator"
            class="hud-btn hud-switch"
            title="切换到运营台（无需重新登录）"
            @click="goToOperator"
          >
            <svg viewBox="0 0 20 20" width="13" height="13" aria-hidden="true">
              <rect x="3" y="3" width="6" height="6" rx="1" stroke="currentColor" stroke-width="1.6" fill="none"/>
              <rect x="11" y="3" width="6" height="6" rx="1" stroke="currentColor" stroke-width="1.6" fill="none"/>
              <rect x="3" y="11" width="6" height="6" rx="1" stroke="currentColor" stroke-width="1.6" fill="none"/>
              <rect x="11" y="11" width="6" height="6" rx="1" stroke="currentColor" stroke-width="1.6" fill="currentColor" opacity=".8"/>
            </svg>
            <span class="hud-switch-label">运营台</span>
            <svg viewBox="0 0 20 20" width="12" height="12" class="hud-switch-arrow" aria-hidden="true">
              <path d="M8 4L14 10L8 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            </svg>
            <span class="hud-switch-shine"></span>
          </button>
          <UserAccountMenu variant="hud" />
        </div>

        <div v-if="!dashboardMode && settlementStandings.length" class="scene-standings">
          <div v-for="item in settlementStandings" :key="item.agentId"
               :class="['standing-card', { leader: item.rank === 1 && !item.eliminated && !item.pending, dead: !item.isAlive, eliminated: item.eliminated }]"
               :style="{ '--ag-color': item.color, '--score-pct': item.scorePct + '%' }"
               :title="item.detail">
            <div class="standing-rank">{{ item.rank }}</div>
            <div class="standing-main">
              <div class="standing-head">
                <span class="standing-name">{{ item.name }}</span>
                <span class="standing-state">{{ item.eliminated
                  ? uiText('ranking_eliminated', '已退出')
                  : (item.pending
                    ? '待场景结算'
                    : (item.rank === 1
                    ? uiText('ranking_leading', '领先')
                    : `${uiText('ranking_gap_prefix', '差')} ${item.gapLabel}`)) }}</span>
              </div>
              <div class="standing-score-row">
                <strong>{{ item.scoreLabel }}</strong>
                <span>{{ item.scoreCaption }}</span>
                <em :class="{ up: item.trend > 0, down: item.trend < 0 }">
                  {{ trendLabel(item.trend) }}
                </em>
              </div>
              <div class="danger-row" v-if="!item.eliminated && item.riskMetric" :class="{ hot: item.danger >= 70 }"
                   :title="`${item.riskMetric.label} ${item.danger} / ${item.riskMetric.max}`">
                <span class="danger-tag">⚠ {{ item.riskMetric.label }}</span>
                <span class="danger-track"><i :style="{ width: item.danger + '%' }"></i><em class="danger-threshold"></em></span>
                <b class="danger-num">{{ item.danger }}</b>
              </div>
            </div>
          </div>
        </div>

        <div v-if="snapshot.is_game_over && snapshot.victory_attribution?.length" class="victory-recap">
          <div class="vr-head" @click="recapCollapsed = !recapCollapsed">
            <span>🏆 终局裁定 · 胜负溯源</span><em>{{ recapCollapsed ? '展开' : '收起' }}</em>
          </div>
          <div v-if="!recapCollapsed" class="vr-body">
            <div v-for="item in snapshot.victory_attribution" :key="item.agent_id" class="vr-card" :class="{ champ: item.rank === 1 }">
              <div class="vr-headline">{{ item.headline }}</div>
              <div class="vr-line plus" v-for="s in item.strengths" :key="'s'+s">＋ {{ s }}</div>
              <div class="vr-line weak" v-for="w in item.weaknesses" :key="'w'+w">－ {{ w }}</div>
              <div class="vr-line fatal" v-if="item.fatal">✖ {{ item.fatal }}</div>
              <div class="vr-mix">结算来源：{{ sourceMixText(item.source_mix) }}</div>
            </div>
          </div>
        </div>

        <div v-if="hasRuleWorld" class="hud-ledger">
          <span class="hl-title">📜 账本</span>
          <span v-for="(label, key) in LEDGER_LABELS" :key="key" class="hl-badge">
            {{ label }}<b>{{ ledgerCounts[key] ?? 0 }}</b>
          </span>
        </div>
      </div>

      <aside class="right-sidebar">

        <!-- ── 解说：紧凑时间线 ── -->
        <section class="zone zone-narration">
          <div class="zone-hd">
            <span class="zone-title">{{ uiText('narrative_title', '世界演绎') }}</span>
            <span v-if="narrativeFeed.length" class="zone-count">{{ narrativeFeed.length }}</span>
          </div>
          <div class="feed-scroll" ref="feedEl">
            <div class="timeline">
              <template v-for="entry in narrativeFeed" :key="entry.id">
                <div :class="['tl-entry', `etype-${entry.type}`]">
                  <span class="tl-tick">T{{ entry.tick }}</span>
                  <span class="tl-dot"></span>
                  <p class="tl-text">
                    <b :style="{ color: entry.color }">{{ entry.speaker }}</b>
                    {{ entry.content }}
                  </p>
                </div>
              </template>
            </div>
            <div v-if="narrativeFeed.length === 0 && !waitingMessage" class="feed-empty">点击 ▶ 开始推演…</div>
            <div v-if="waitingMessage" class="feed-waiting">
              <span class="fw-pulse"></span>
              <span>{{ waitingMessage }}</span>
            </div>
          </div>
        </section>

        <!-- ── 内心独白 + 投资策略：角色卡片 ── -->
        <section class="zone zone-thoughts">
          <div class="zone-hd">
            <span class="zone-title">{{ uiText('thoughts_title', '角色思考') }}</span>
            <span class="zone-source">{{ uiText('thoughts_source', '模型输出') }}</span>
          </div>
          <div class="thoughts-list">
            <div v-for="agent in snapshot.agents" :key="agent.agent_id"
                 :class="['thought-card', { 'tc-dead': !agent.is_alive || isEliminated(agent.agent_id) }]"
                 :style="{ '--ag-color': agent.color }">
              <div class="tc-head">
                <span class="tc-avatar" :style="agentAvatarUrl(agent.agent_id) ? {} : { background: agent.color }">
                  <img v-if="agentAvatarUrl(agent.agent_id)" class="tc-avatar-img" :src="agentAvatarUrl(agent.agent_id)" :alt="agent.name" />
                  <template v-else>{{ (agent.name || '?').charAt(0) }}</template>
                </span>
                <div class="tc-info">
                  <span class="tc-name">{{ agent.name }}</span>
                  <span :class="['tc-status', (agent.is_alive && !isEliminated(agent.agent_id)) ? 'alive' : 'dead']">
                    {{ agentStatusText(agent) }}
                  </span>
                </div>
              </div>
              <div class="tc-body">
                <div class="tc-block">
                  <label>{{ uiText('thoughts_title', '操盘思路') }}</label>
                  <p v-if="agent.character_monologue" class="tc-thought">{{ agent.character_monologue }}</p>
                  <p v-else-if="agent.public_attrs?.last_text" class="tc-speech">「{{ agent.public_attrs.last_text }}」</p>
                  <p v-else class="tc-silence">思考中…</p>
                </div>
                <div class="tc-block tc-strategy">
                  <label>
                    {{ uiText('strategy_title', '投资策略') }}
                    <em>{{ uiText('strategy_source', '思维链') }}</em>
                  </label>
                  <p v-if="agent.public_reasoning_summary" class="tc-strategy-text">{{ agent.public_reasoning_summary }}</p>
                  <p v-else class="tc-silence">等待策略摘要…</p>
                </div>
              </div>
            </div>
            <div v-if="!snapshot.agents.length" class="thoughts-empty">等待角色出场</div>
          </div>
        </section>

        <section v-show="showConfig" class="zone zone-config">
          <div class="zone-hd">
            <span class="zone-icon">⚙</span>
            <span class="zone-title">模型配置</span>
          </div>
          <div class="cfg-scroll">
            <div v-for="agent in agentConfigs" :key="agent.id" class="acfg-card">
              <div class="acfg-head">
                <span class="acfg-dot" :style="{ background: agent.color }"></span>
                <span class="acfg-name">{{ agent.name }}</span>
                <span class="acfg-id">{{ agent.id }}</span>
              </div>
              <div class="cfg-row driver-row">
                <label>驱动</label>
                <div class="driver-toggle">
                  <button
                    type="button"
                    class="driver-btn"
                    :class="{ active: (agent.driver || 'llm') === 'llm' }"
                    :disabled="!canEditModelConfig"
                    @click="setAgentDriver(agent, 'llm')"
                  >LLM</button>
                  <button
                    type="button"
                    class="driver-btn"
                    :class="{ active: agent.driver === 'agent' }"
                    :disabled="!canEditModelConfig"
                    @click="setAgentDriver(agent, 'agent')"
                  >Agent</button>
                </div>
              </div>
              <template v-if="(agent.driver || 'llm') === 'llm'">
                <div class="cfg-row">
                  <label>Provider</label>
                  <select v-model="agent.provider" :disabled="!canEditModelConfig">
                    <option v-for="p in availableProviders" :key="p" :value="p">{{ p }}</option>
                  </select>
                </div>
                <div class="cfg-row">
                  <label>Model</label>
                  <input v-model="agent.model" :disabled="!canEditModelConfig" />
                </div>
                <div class="cfg-row">
                  <label>API Key</label>
                  <input v-model="agent.api_key" type="password" :disabled="!canEditModelConfig" />
                </div>
                <button
                  v-if="canEditModelConfig"
                  class="btn-apply btn-inline"
                  @click="saveAgentConfig(agent)"
                >应用</button>
              </template>
              <template v-else>
                <div class="agent-ext-block">
                  <div class="ext-status-row">
                    <span
                      class="ext-badge"
                      :class="agent.external_status?.connected ? 'on' : 'off'"
                    >
                      {{
                        agent.external_status?.connected
                          ? `已连接（${agent.external_status?.agent_label || '外部 Agent'}）`
                          : (agent.external_status?.status === 'AWAITING' ? '决策中…' : '未连接')
                      }}
                    </span>
                  </div>
                  <div v-if="agent.join_url" class="ext-link" :title="agent.join_url">
                    {{ agent.join_url }}
                  </div>
                  <p v-else class="ext-hint">尚未生成接入链接，点击下方「生成链接」</p>
                  <div class="ext-actions">
                    <button
                      type="button"
                      class="ext-btn"
                      :disabled="!agent.join_url"
                      @click="copyJoinLink(agent)"
                    >复制链接</button>
                    <button
                      type="button"
                      class="ext-btn"
                      :disabled="!agent.copy_bundle"
                      @click="copyFullBundle(agent)"
                    >复制完整说明</button>
                    <button
                      v-if="canEditModelConfig"
                      type="button"
                      class="ext-btn"
                      @click="regenerateAgentLink(agent)"
                    >{{ agent.join_url ? '重新生成' : '生成链接' }}</button>
                    <button
                      v-if="canEditModelConfig && agent.has_join_token"
                      type="button"
                      class="ext-btn danger"
                      @click="revokeAgentLinkAction(agent)"
                    >作废链接</button>
                  </div>
                  <p class="ext-hint">
                    通用说明：
                    <a :href="agent.skill_url || skillDocUrl" target="_blank" rel="noopener">skill.md</a>
                  </p>
                </div>
              </template>
            </div>
            <div class="cfg-divider">🗂 场景包</div>
            <select v-model="selectedScenario" class="select-full">
              <option v-for="s in scenarios" :key="s" :value="s">{{ s }}</option>
            </select>
            <button class="btn-apply mt8" @click="switchScenario">切换场景</button>
            <input ref="scenarioFileInput" type="file" accept=".zip" style="display:none" @change="onScenarioFileChosen" />
            <button class="btn-apply mt8" @click="scenarioFileInput?.click()">上传我的场景包(.zip)</button>
            <p v-if="uploadMsg" class="cfg-msg">{{ uploadMsg }}</p>
            <div class="cfg-divider">⟳ 演出回放</div>
            <select v-model="selectedReplay" class="select-full">
              <option value="">最近完成的演绎</option>
              <option v-for="run in replays" :key="run.run_id" :value="run.run_id">
                {{ run.run_id }} · {{ run.scenario || '当前场景' }}
              </option>
            </select>
            <button class="btn-apply mt8" @click="handleReplay(selectedReplay)">播放回放</button>
            <div v-if="cfgMsg" class="cfg-msg">{{ cfgMsg }}</div>
          </div>
        </section>

      </aside>
    </div>

    <div class="bottom-bar">
      <div class="oracle-zone">
        <span class="oracle-label">⚡ {{ uiText('intervention_label', '世界干预') }}</span>
        <select v-model="oracleTarget" class="oracle-select">
          <option value="all">全体</option>
          <option v-for="a in snapshot.agents" :key="a.agent_id" :value="a.agent_id">{{ a.name }}</option>
        </select>
        <input v-model="oracleText" class="oracle-input" :placeholder="uiText('intervention_placeholder', '输入一条世界事件，回车发送…')" @keyup.enter="sendOracle" />
        <button class="oracle-send" @click="sendOracle">注入</button>
      </div>
      <div class="vars-zone" v-if="worldVariables.length">
        <span class="vars-label">{{ uiText('variables_label', '世界变量') }}</span>
        <button v-for="v in worldVariables" :key="v.id" class="var-btn" @click="triggerWorldVar(v)">{{ v.icon }} {{ v.label }}</button>
      </div>
    </div>

    <div v-if="showNotice" class="notice-overlay" @click.self="closeScenarioNotice">
      <section class="notice-panel">
        <header class="notice-head">
          <div>
            <span class="notice-kicker">场景档案</span>
            <h2>{{ scenarioDisplayName || uiText('notice_label', '场景说明') }}</h2>
          </div>
          <button class="notice-close" @click="closeScenarioNotice">×</button>
        </header>
        <div v-if="noticeTTSStatus" class="notice-voice-status">
          <span class="notice-voice-dot"></span>{{ noticeTTSStatus }}
        </div>
        <div ref="noticeBodyEl" class="notice-body">
          <article class="notice-section">
            <h3>故事背景</h3>
            <div v-if="noticeChunksFor('background').length" class="notice-spoken-copy">
              <span
                v-for="chunk in noticeChunksFor('background')"
                :key="chunk.index"
                :data-notice-chunk="chunk.index"
                :class="noticeChunkClass(chunk)"
              >{{ chunk.text }}</span>
            </div>
            <p v-else>{{ displayBackgroundText || '场景包暂未提供背景说明。' }}</p>
          </article>
          <article class="notice-section">
            <h3>本局目标</h3>
            <div v-if="noticeChunksFor('goal').length" class="notice-spoken-copy">
              <span
                v-for="chunk in noticeChunksFor('goal')"
                :key="chunk.index"
                :data-notice-chunk="chunk.index"
                :class="noticeChunkClass(chunk)"
              >{{ chunk.text }}</span>
            </div>
            <p v-else>{{ displayGoalText || '场景包暂未提供目标说明。' }}</p>
          </article>
          <article class="notice-section">
            <h3>胜负规则</h3>
            <div v-if="noticeChunksFor('rules').length" class="notice-spoken-copy">
              <span
                v-for="chunk in noticeChunksFor('rules')"
                :key="chunk.index"
                :data-notice-chunk="chunk.index"
                :class="noticeChunkClass(chunk)"
              >{{ chunk.text }}</span>
            </div>
            <ul v-else>
              <li v-for="line in victoryRuleLines" :key="line">{{ line }}</li>
            </ul>
          </article>
          <article class="notice-section">
            <h3>参演角色</h3>
            <div class="notice-roles">
              <span v-for="role in scenarioRoles" :key="role.id" :style="{ '--role-color': role.color || '#7dd3fc' }">
                <i></i>{{ role.name }}
              </span>
            </div>
          </article>
        </div>
      </section>
    </div>

  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, shallowRef, nextTick, computed, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { CSS2DRenderer, CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js'
import { createWSClient } from '@/core/wsClient'
import { authedFetch, hasPermission } from '@/core/authStore.js'
import UserAccountMenu from '@/components/UserAccountMenu.vue'
import {
  applyLinkPayload,
  copyToClipboard,
  createAgentLink,
  normalizeAgentConfig,
  patchAgentDriver,
  revokeAgentLink,
} from '@/core/agentGatewayApi.js'
import { createPresentationExecutor } from './presentationExecutor'
import { createAudioEngine } from './audioEngine'
import { createEffectEngine } from './effectEngine'
import { navigateView } from '@/core/viewNav.js'
import {
  saveNarrativeFeed,
  loadNarrativeFeed,
  clearNarrativeFeed,
} from '@/core/narrativeFeedStore.js'

defineOptions({ name: 'Renderer' })

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001'

// 有运营台权限时，观众端顶部露出一个直达入口——同源共享登录态，切换不用重新登录
const canAccessOperator = hasPermission('access_operator')
const canEditModelConfig = hasPermission('edit_model_config')
const skillDocUrl = computed(() => `${API_BASE}/agent/skill.md`)
function goToOperator() {
  navigateView('operator')
}

const mountEl = ref(null), feedEl = ref(null), noticeBodyEl = ref(null)
const snapshot = ref({ tick: 0, is_running: false, is_game_over: false, agents: [], artifacts: [] })
const recapCollapsed = ref(false)
const narrativeFeed = ref([]), showConfig = ref(false), showNotice = ref(false)
const agentConfigs = ref([]), availableProviders = ref(['mock','openai','deepseek','anthropic','minimax','huggingface'])
const scenarios = ref([]), selectedScenario = ref(''), cfgMsg = ref('')
const scenarioFileInput = ref(null), uploadMsg = ref('')
const replays = ref([]), selectedReplay = ref('')
const oracleText = ref(''), oracleTarget = ref('all')
let feedIdCtr = 0, lastAddedTick = -1
let currentTTSAudio = null  // 跟踪当前播放的 TTS Audio
let currentTTSItem = null
const ttsQueue = []

// Buffer 状态
const bufferHealth = ref('good')
const bufferSize = ref(0)
const bufferAheadMs = ref(0)
const speedFactor = ref(1.0)
const isComputing = ref(false)
const waitingMessage = ref('')
const scenarioSwitching = ref(false)
const simulationComplete = ref(false)
const wsConnected = ref(false)
const isReplaying = ref(false)
const isResetting = ref(false)
const noticeTTSStatus = ref('')
const noticeSpeechChunks = ref([])
const noticeActiveChunk = ref(-1)
const settlementTrends = ref({})
const computedTick = ref(0)

const LEDGER_LABELS = { action:'行动', state_delta:'状态', metric_derivation:'派生', tool:'工具', evidence:'证据', settlement:'结算' }
const sceneState = computed(() => snapshot.value.scene_state || {})
const ledgerCounts = computed(() => sceneState.value.ledger_counts || {})
const hasRuleWorld = computed(() => Object.keys(ledgerCounts.value).length > 0)

// ── 目标进展仪表盘 ──
let metricDefinitions = {}
const settlementConfig = ref({})

function metricLabel(key) {
  const normalized = String(key ?? '')
  const settlementLabel = settlementConfig.value?.display_values?.[normalized]
  if (settlementLabel) return settlementLabel
  const declared = metricDefinitions?.[normalized] || metricDefs.value?.[normalized] || {}
  return declared.label || declared.name || normalized.replace(/^metric_/, '').replace(/_/g, ' ')
}

function formatMetricCard(card) {
  const raw = String(card || '').trim()
  if (!raw) return ''
  const matched = raw.match(/^(metric_[A-Za-z0-9_]+)\s*([+-]?\d+(?:\.\d+)?)/)
  if (!matched) {
    return raw.replace(/([+-]?\d+\.\d{2,})/g, value => {
      const n = Number(value)
      return Number.isFinite(n) ? n.toFixed(1) : value
    })
  }
  const label = metricLabel(matched[1])
  const value = Number(matched[2])
  const delta = Number.isFinite(value) ? `${value >= 0 ? '+' : ''}${value.toFixed(1)}` : matched[2]
  return `${label} ${delta}`
}

function roundDisplayNumber(value, digits = 2) {
  const num = Number(value)
  if (!Number.isFinite(num)) return 0
  const factor = 10 ** digits
  return Math.round((num + Number.EPSILON) * factor) / factor
}

function formatDisplayNumber(value, digits = 2) {
  const rounded = roundDisplayNumber(value, digits)
  return rounded.toLocaleString('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
}

function settlementScores(data = {}) {
  return Object.fromEntries(
    (data.settlement_standings || []).map(item => [
      item.agent_id,
      Number(item.value || 0),
    ])
  )
}

const settlementStandings = computed(() => {
  const settlementRows = new Map(
    (snapshot.value.settlement_standings || []).map(item => [item.agent_id, item])
  )
  const definitions = Object.entries(metricDefinitions || {}).map(([id, item]) => ({
    id,
    label: item?.name || item?.label || metricLabel(id),
    min: Number(item?.min ?? 0),
    max: Number(item?.max ?? 100),
    risk: Boolean(item?.risk),
  }))
  const riskDefinition = definitions.find(item => item.risk) || null
  const eliminatedOrder = (snapshot.value.eliminated || [])
    .filter(e => e && e.agent_id).map(e => e.agent_id)
  const items = (snapshot.value.agents || []).map(agent => {
    const aid = agent.agent_id
    const settlement = settlementRows.get(aid) || { value: 0, values: {}, pending: true }
    const currentMetrics = snapshot.value.agent_metrics?.[aid] || {}
    const isElim = eliminatedOrder.includes(aid)
    return {
      agentId: aid,
      name: agent.name || aid,
      color: agent.color || '#7dd3fc',
      isAlive: agent.is_alive,
      eliminated: isElim,
      elimOrder: isElim ? eliminatedOrder.indexOf(aid) : -1,
      score: roundDisplayNumber(settlement.value ?? 0),
      scoreLabel: settlement.pending ? '待结算' : formatDisplayNumber(settlement.value ?? 0),
      scoreCaption: settlement.label || '场景结算',
      settlementRank: Number(settlement.rank || 9999),
      pending: Boolean(settlement.pending),
      trend: roundDisplayNumber(settlementTrends.value[aid] ?? 0),
      metricHighlights: Object.entries(settlement.values || {})
        .filter(([, value]) => Number.isFinite(Number(value)))
        .slice(0, 3)
        .map(([id, value]) => ({ id, label: metricLabel(id), value: formatDisplayNumber(value) })),
      holdings: normalizeHoldings(settlement.holdings || settlement.details),
      riskMetric: riskDefinition,
      danger: riskDefinition
        ? Math.max(riskDefinition.min, Math.min(riskDefinition.max, Math.round(Number(currentMetrics[riskDefinition.id] ?? 0))))
        : 0,
    }
  }).sort((a, b) => {
    // 出局者一律垫底，后出局的排前面；存活者按分数
    if (a.eliminated !== b.eliminated) return a.eliminated ? 1 : -1
    if (a.eliminated && b.eliminated) return b.elimOrder - a.elimOrder
    return a.settlementRank - b.settlementRank || a.name.localeCompare(b.name)
  })
  const leaderScore = items.find(i => !i.eliminated)?.score ?? 0
  const finiteScores = items.map(item => Math.abs(Number(item.score || 0)))
  const scoreScale = Math.max(1, ...finiteScores)
  return items.map((item, index) => ({
    ...item,
    rank: index + 1,
    gap: roundDisplayNumber(Math.abs(item.score - leaderScore)),
    gapLabel: formatDisplayNumber(Math.abs(item.score - leaderScore)),
    scorePct: Math.max(2, Math.min(100, Math.abs(item.score) / scoreScale * 100)),
      detail: Object.entries(settlementRows.get(item.agentId)?.values || {})
      .filter(([, value]) => typeof value === 'number')
      .map(([key, value]) => `${metricLabel(key)} ${Math.round(value)}`)
      .join(' · '),
  }))
})
// ── 演绎形态：由场景包 presentation.render_mode 声明。dashboard=数据仪表盘 ──
const renderMode = ref('scene_3d')
const dashboardMode = computed(() => renderMode.value === 'dashboard')
const dashboardPrimaryLabel = computed(() => {
  const m = uiConfig?.metrics || {}
  const pid = m.primary
  return (pid && (m.labels?.[pid] || metricLabel(pid))) || uiText('ranking_score_label', '组合总资产')
})
// 两位经理各占一区：形象 + 总资产 + 盈亏 + 独白 + 投资策略（全部来自场景数据）
const dashboardAgents = computed(() => {
  const agents = snapshot.value.agents || []
  const monoMap = new Map(agents.map(a => [a.agent_id, a]))
  const palette = ['#4cc9f0', '#ffbe0b', '#68f7a5', '#c792ea']
  let rows = settlementStandings.value
  if (!rows.length) rows = agents.map((a, i) => ({
    agentId: a.agent_id, name: a.name || a.agent_id, color: a.color || palette[i % palette.length],
    rank: i + 1, scoreLabel: '待入场', metricHighlights: [], holdings: [], eliminated: false,
  }))
  if (!rows.length) rows = (scenarioRoles.value || []).map((r, i) => ({
    agentId: r.id || r.slot_id, name: r.name || r.display_name || r.id, color: r.color || palette[i % palette.length],
    rank: i + 1, scoreLabel: '待入场', metricHighlights: [], holdings: [], eliminated: false,
  }))
  return rows.map(s => {
    const a = monoMap.get(s.agentId) || {}
    const role = scenarioRoles.value.find(r => (r.id || r.slot_id) === s.agentId) || {}
    return {
      agentId: s.agentId,
      name: s.name,
      color: s.color,
      rank: s.rank,
      leading: s.rank === 1 && !s.eliminated,
      eliminated: s.eliminated,
      scoreLabel: s.scoreLabel,
      metrics: (s.metricHighlights || []).map(m => ({
        ...m,
        tone: /pnl|盈亏|return|收益|profit/i.test(`${m.id} ${m.label}`)
          ? (String(m.value).trim().startsWith('-') ? 'down' : 'up')
          : 'neutral',
      })),
      holdings: Array.isArray(s.holdings) ? s.holdings.slice(0, 6) : [],
      // 操盘思路 = 角色独白（模型输出）；投资策略 = 公开策略摘要（思维链）
      monologue: String(a.character_monologue || '').trim(),
      strategy: String(a.public_reasoning_summary || '').trim(),
      roleTitle: role.role_title || role.public_persona || '',
      badge: (s.name || '?').slice(0, 1),
      avatarUrl: agentAvatarUrl(s.agentId),
      status: a.external_status?.status,
    }
  })
})

function agentAvatarUrl(agentId) {
  const cfg = renderCharacterForAgent(agentId)
  const asset = cfg?.asset || ''
  return asset ? resolveAsset(asset) : ''
}
function normalizeHoldings(raw) {
  if (Array.isArray(raw)) {
    return raw
      .filter(item => item && item.asset_id && Math.abs(Number(item.quantity || 0)) > 1e-9)
      .map(item => ({
        asset_id: String(item.asset_id),
        name: String(item.name || item.display_name || '').trim(),
        quantity: Number(item.quantity || 0),
        mark_price: Number(item.mark_price ?? item.price ?? 0),
        avg_cost: Number(item.avg_cost ?? item.mark_price ?? item.price ?? 0),
      }))
  }
  if (!raw || typeof raw !== 'object') return []
  const positions = raw.positions || {}
  const prices = raw.prices || {}
  const avgCosts = raw.avg_costs || {}
  const names = raw.asset_names || raw.names || {}
  return Object.entries(positions)
    .filter(([, qty]) => Math.abs(Number(qty || 0)) > 1e-9)
    .map(([assetId, qty]) => ({
      asset_id: String(assetId),
      name: String(names[assetId] || '').trim(),
      quantity: Number(qty || 0),
      mark_price: Number(prices[assetId] || 0),
      avg_cost: Number(avgCosts[assetId] ?? prices[assetId] ?? 0),
    }))
    .sort((a, b) => Math.abs(b.quantity) - Math.abs(a.quantity))
}
function formatHoldingName(assetId) {
  const raw = String(assetId || '').trim()
  if (!raw) return '—'
  // 展示简洁代码：600036.SH → 600036.SH（保留市场后缀便于区分 A/H）
  return raw.length > 14 ? `${raw.slice(0, 12)}…` : raw
}
function formatHoldingQty(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return Math.abs(n - Math.round(n)) < 1e-6 ? String(Math.round(n)) : n.toFixed(2)
}
function formatHoldingPrice(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '—'
  return n >= 100 ? n.toFixed(2) : n.toFixed(3)
}

function sourceMixText(mix = {}) {
  const entries = Object.entries(mix || {})
  return entries.length
    ? entries.map(([key, value]) => `${key} ${formatDisplayNumber(value)}`).join(' · ')
    : '由当前场景结算规则决定'
}
function trendLabel(value) {
  const rounded = roundDisplayNumber(value)
  if (rounded > 0) return `▲${formatDisplayNumber(rounded)}`
  if (rounded < 0) return `▼${formatDisplayNumber(Math.abs(rounded))}`
  return '—'
}
function numericAttrs(attrs) { if (!attrs) return []; return Object.entries(attrs).filter(([,v]) => typeof v === 'number') }
function shortKey(k) { return k.replace(/_/g,' ').replace(/([a-z]+) ([a-z]+)/g,(_,a,b)=>a[0].toUpperCase()+b[0].toUpperCase()).replace(/([a-z])([A-Z])/g,'$1 $2').substring(0,12) }

const ws = createWSClient('viewer')
const scene = shallowRef(null), camera = shallowRef(null), renderer = shallowRef(null), labelRdr = shallowRef(null), composer = shallowRef(null), controls = shallowRef(null)
const agentMeshes = {}, artifactMeshes = {}, mixers = [], glbCache = {}
const presentedTicks = new Set()
let presentationExecutor = null
let audioEngine = null      // P2-B3：BGM 状态机 + SFX 路由
let effectEngine = null     // P2-B2：粒子 + 屏幕特效
let defaultGLBUrl = '', envObjects = [], presentation = null, roleModels = {}
let renderCfg = null, worldLocations = [], sceneConfig = null, sceneTheme = null, uiConfig = null
let agentSlots = [], agentFallbackCfg = {}, locMarkerCfg = {}, uiTheme = {}
const locMarkerMap = {}  // locId -> { group, labelEl, ring, position }
let SPAWN_POSITIONS = []
let spawnIdx = 0, scenarioName = ''
const worldVariables = ref([])
const metricDefs = ref({})  // render/ui.yaml 的 metrics 定义
const goalText = ref('')
const backgroundText = ref('')
const scenarioDisplayName = ref('')
const auditConfig = ref({})
const scenarioRoles = ref([])
const availableActions = ref([])
function cleanScenarioText(value) {
  return String(value || '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '• ')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
function uiText(key, fallback='') {
  return presentation?.ui_text?.[key] || fallback
}
const displayBackgroundText = computed(() => cleanScenarioText(backgroundText.value))
const displayGoalText = computed(() => cleanScenarioText(goalText.value))
const victoryRuleLines = computed(() => {
  const audit = auditConfig.value || {}
  const settlement = settlementConfig.value || {}
  const lines = []
  const declaredRule = cleanScenarioText(
    audit.world_goals_footer || uiText('victory_rule', '')
  )
  if (declaredRule) lines.push(declaredRule)
  const termination = audit.termination?.any || []
  for (const item of termination) {
    if (item.type === 'tick_limit') lines.push(`演绎进行至第 ${item.value} 回合后进入终局结算。`)
    else lines.push(`终局条件：${item.type || '场景条件'} ${item.value ?? ''}`.trim())
  }
  if (settlement.victory?.label) {
    lines.push(`胜负口径：${settlement.victory.label}，由 ${settlement.victory.provider_id} 结算。`)
  }
  const disqualifications = audit.disqualification?.conditions || []
  if (disqualifications.length) lines.push('触发场景包声明的淘汰条件将失去获胜资格。')
  lines.push('角色不能自行宣告胜利，最终结果只由当前场景声明的结算规则产生。')
  return lines.length ? [...new Set(lines)] : ['胜负规则由当前场景包声明，并由对应结算器确认。']
})

function initScene() {
  const el = mountEl.value; const w = el.clientWidth, h = el.clientHeight
  const rdr = new THREE.WebGLRenderer({ antialias: true }); rdr.setPixelRatio(Math.min(window.devicePixelRatio, 2)); rdr.setSize(w, h); rdr.shadowMap.enabled = true; rdr.shadowMap.type = THREE.PCFSoftShadowMap; rdr.toneMapping = THREE.ACESFilmicToneMapping; rdr.toneMappingExposure = 1.35
  el.appendChild(rdr.domElement); renderer.value = rdr
  const lr = new CSS2DRenderer(); lr.setSize(w, h); lr.domElement.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none'; el.appendChild(lr.domElement); labelRdr.value = lr
  const env = presentation?.environment || {}
  const sc = new THREE.Scene(); sc.background = makeSky(env.sky_gradient); sc.fog = new THREE.FogExp2(new THREE.Color(env.fog_color||'#071522').getHex(), env.fog_density??0.008); scene.value = sc
  const initialCamera = renderCfg?.cameras?.camera_main || {}
  const initialPosition = initialCamera.position || {}
  const initialLookAt = initialCamera.look_at || {}
  const cam = new THREE.PerspectiveCamera(presentation?.camera?.fov || 50, w/h, 0.1, 500)
  cam.position.set(initialPosition.x ?? 0, initialPosition.y ?? 12, initialPosition.z ?? 18)
  cam.lookAt(initialLookAt.x ?? 0, initialLookAt.y ?? 0, initialLookAt.z ?? 6)
  camera.value = cam
  const ctrl = new OrbitControls(cam, rdr.domElement); ctrl.target.set(initialLookAt.x ?? 0, initialLookAt.y ?? 0, initialLookAt.z ?? 6); ctrl.enableDamping = true; ctrl.dampingFactor = 0.08; controls.value = ctrl
  buildLighting(sc, env); buildGround(sc, env); buildProps(sc, env); buildLocationSceneAssets(sc); buildLocationMarkers(sc); buildAtmosphere(sc, env)
  const cmp = new EffectComposer(rdr); cmp.addPass(new RenderPass(sc, cam)); cmp.addPass(new UnrealBloomPass(new THREE.Vector2(w, h), 0.78, 0.45, 0.82)); cmp.addPass(makeVignette()); cmp.addPass(new OutputPass()); composer.value = cmp
  window.addEventListener('resize', onResize)
}

function makeSky(stops) { const colors = stops?.length ? stops : ['#02050b','#07111d','#0b1b2a','#102c3b']; const c=document.createElement('canvas'); c.width=2; c.height=256; const ctx=c.getContext('2d'); const g=ctx.createLinearGradient(0,0,0,256); colors.forEach((col,i)=>g.addColorStop(i/(colors.length-1),col)); ctx.fillStyle=g; ctx.fillRect(0,0,2,256); const tex=new THREE.CanvasTexture(c); tex.colorSpace=THREE.SRGBColorSpace; return tex }

function buildLighting(sc, env={}) {
  const lights = env.lighting || []
  if (!lights.length) {
    sc.add(new THREE.HemisphereLight(0xb9e6ff, 0x07111f, 1.1))
    sc.add(new THREE.AmbientLight(0xffffff, 0.38))
    return
  }
  for(const cfg of lights) {
    const t = cfg.type
    if(t==='directional') {
      const l=new THREE.DirectionalLight(new THREE.Color(cfg.color||'#fff').getHex(), cfg.intensity??1)
      if(cfg.position)l.position.set(...cfg.position)
      if(cfg.cast_shadow){l.castShadow=true;const ss=cfg.shadow_map_size||2048;l.shadow.mapSize.set(ss,ss);const[s0,s1,s2,s3]=cfg.shadow_camera||[-25,25,25,-25];l.shadow.camera.left=s0;l.shadow.camera.right=s1;l.shadow.camera.top=s2;l.shadow.camera.bottom=s3;l.shadow.bias=-0.0004}
      sc.add(l)
    } else if(t==='hemisphere') {
      sc.add(new THREE.HemisphereLight(new THREE.Color(cfg.sky_color||'#fff').getHex(), new THREE.Color(cfg.ground_color||'#000').getHex(), cfg.intensity??1))
    } else if(t==='ambient') {
      sc.add(new THREE.AmbientLight(new THREE.Color(cfg.color||'#fff').getHex(), cfg.intensity??1))
    } else if(t==='point') {
      const l=new THREE.PointLight(new THREE.Color(cfg.color||'#fff').getHex(), cfg.intensity??1, cfg.distance??0, cfg.decay??2)
      if(cfg.position)l.position.set(...cfg.position)
      sc.add(l)
    }
  }
}

function makeRadialFloorTexture(baseColor='#07111f', ringColor='#4cc9f0') {
  // 通用程序化径向纹理；是否启用及颜色完全由场景包声明。
  const S=1024, c=document.createElement('canvas'); c.width=c.height=S
  const ctx=c.getContext('2d'), cx=S/2, cy=S/2
  ctx.fillStyle=baseColor; ctx.fillRect(0,0,S,S)
  // 细噪点（石面质感）
  for(let i=0;i<2600;i++){
    const x=Math.random()*S, y=Math.random()*S, r=Math.random()*1.8+0.4
    ctx.fillStyle=`rgba(${Math.random()>0.5?255:0},${Math.random()>0.5?230:10},${Math.random()>0.5?190:20},${(Math.random()*0.045).toFixed(3)})`
    ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fill()
  }
  // 同心金环
  for(let r=64;r<S/2;r+=64){
    ctx.strokeStyle=ringColor
    ctx.lineWidth=r%128===0?3:1.4
    ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2); ctx.stroke()
  }
  // 放射砖缝
  ctx.globalAlpha=0.22; ctx.strokeStyle=ringColor; ctx.lineWidth=1.2
  for(let i=0;i<28;i++){
    const a=(i/28)*Math.PI*2
    ctx.beginPath(); ctx.moveTo(cx+Math.cos(a)*70, cy+Math.sin(a)*70)
    ctx.lineTo(cx+Math.cos(a)*S/2, cy+Math.sin(a)*S/2); ctx.stroke()
  }
  // 中心藻井光晕
  ctx.globalAlpha=1
  const g=ctx.createRadialGradient(cx,cy,0,cx,cy,150)
  g.addColorStop(0,ringColor); g.addColorStop(1,'rgba(0,0,0,0)')
  ctx.fillStyle=g; ctx.beginPath(); ctx.arc(cx,cy,150,0,Math.PI*2); ctx.fill()
  const tex=new THREE.CanvasTexture(c); tex.colorSpace=THREE.SRGBColorSpace
  tex.anisotropy=4
  return tex
}

function buildGround(sc, env={}) {
  const g = env.ground || {}
  const shape = g.shape || 'circle'
  const radius = g.radius || 50
  const matOpts = {color:new THREE.Color(g.color||'#07111f').getHex(), roughness:g.roughness??1}
  if(g.metalness!==undefined)matOpts.metalness=g.metalness
  if(g.pattern==='radial'){ matOpts.map=makeRadialFloorTexture(g.color||'#07111f',g.pattern_color||'#4cc9f0'); matOpts.color=0xffffff }
  const mat = new THREE.MeshStandardMaterial(matOpts)
  const mesh = shape==='circle' ? new THREE.Mesh(new THREE.CircleGeometry(radius,64),mat) : new THREE.Mesh(new THREE.PlaneGeometry(radius*2,radius*2),mat)
  mesh.rotation.x=-Math.PI/2; mesh.receiveShadow=true; sc.add(mesh); envObjects.push(mesh)
  const d = g.detail
  if(d && d.count) {
    const dc=new THREE.Color(d.color||'#5a2e2a').getHex()
    for(let i=0;i<d.count;i++){
      const r=(d.min_radius||6)+Math.random()*((d.max_radius||34)-(d.min_radius||6)),a=Math.random()*Math.PI*2
      const sz=(d.min_size||0.3)+Math.random()*((d.max_size||0.8)-(d.min_size||0.3))
      const p=new THREE.Mesh(new THREE.CircleGeometry(sz,5),new THREE.MeshStandardMaterial({color:dc,roughness:1}))
      p.rotation.x=-Math.PI/2; p.position.set(Math.cos(a)*r,.01,Math.sin(a)*r); sc.add(p); envObjects.push(p)
    }
  }
}

// ── 大气层：星空 / 月亮 / 烛烬粒子（由 presentation.environment.atmosphere 配置驱动）──
let atmos = { stars: null, embers: null, emberData: null, moon: null }

function makeGlowSprite(inner='#fff6d8', outer='rgba(240,200,120,0)') {
  const S=128, c=document.createElement('canvas'); c.width=c.height=S
  const ctx=c.getContext('2d')
  const g=ctx.createRadialGradient(S/2,S/2,0,S/2,S/2,S/2)
  g.addColorStop(0,inner); g.addColorStop(0.35,inner); g.addColorStop(1,outer)
  ctx.fillStyle=g; ctx.fillRect(0,0,S,S)
  const tex=new THREE.CanvasTexture(c); tex.colorSpace=THREE.SRGBColorSpace
  return tex
}

function buildAtmosphere(sc, env={}) {
  const cfg = env.atmosphere || {}
  atmos = { stars: null, embers: null, emberData: null, moon: null }
  // 星空穹顶
  const starCfg = cfg.stars
  if (starCfg) {
    const n = starCfg.count || 600
    const pos = new Float32Array(n*3), sz = new Float32Array(n)
    for(let i=0;i<n;i++){
      // 上半球均匀分布，压低到地平线以上 8°
      const a=Math.random()*Math.PI*2
      const e=Math.asin(Math.random()*0.92+0.08)
      const r=170+Math.random()*40
      pos[i*3]=Math.cos(a)*Math.cos(e)*r
      pos[i*3+1]=Math.sin(e)*r
      pos[i*3+2]=Math.sin(a)*Math.cos(e)*r
      sz[i]=Math.random()
    }
    const geo=new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pos,3))
    const mat=new THREE.PointsMaterial({
      color:new THREE.Color(starCfg.color||'#cfd8ff').getHex(),
      size:starCfg.size??1.6, sizeAttenuation:false,
      transparent:true, opacity:0.85,
      blending:THREE.AdditiveBlending, depthWrite:false, fog:false,
    })
    const pts=new THREE.Points(geo,mat)
    pts.renderOrder=-1
    sc.add(pts); envObjects.push(pts); atmos.stars=pts
  }
  // 月亮（光晕 + 亮核双 sprite）
  const moonCfg = cfg.moon
  if (moonCfg) {
    const grp=new THREE.Group()
    const halo=new THREE.Sprite(new THREE.SpriteMaterial({
      map:makeGlowSprite(moonCfg.color||'#f5e6c8','rgba(240,200,120,0)'),
      transparent:true, opacity:0.5, blending:THREE.AdditiveBlending, depthWrite:false, fog:false,
    }))
    halo.scale.setScalar((moonCfg.size||5)*3.2)
    const core=new THREE.Sprite(new THREE.SpriteMaterial({
      map:makeGlowSprite('#fffdf2','rgba(255,250,230,0)'),
      transparent:true, opacity:0.95, depthWrite:false, fog:false,
    }))
    core.scale.setScalar(moonCfg.size||5)
    grp.add(halo); grp.add(core)
    grp.position.set(...(moonCfg.position||[26,34,-42]))
    sc.add(grp); envObjects.push(grp); atmos.moon=grp
  }
  // 烛烬/流萤粒子：从地面缓缓升起
  const emberCfg = cfg.embers
  if (emberCfg) {
    const n=emberCfg.count||100, R=emberCfg.radius||40
    const pos=new Float32Array(n*3)
    const data=[]
    for(let i=0;i<n;i++){
      const a=Math.random()*Math.PI*2, r=Math.sqrt(Math.random())*R
      pos[i*3]=Math.cos(a)*r; pos[i*3+1]=Math.random()*10; pos[i*3+2]=Math.sin(a)*r
      data.push({ vy:0.25+Math.random()*0.6, phase:Math.random()*Math.PI*2, amp:0.15+Math.random()*0.35 })
    }
    const geo=new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(pos,3))
    const mat=new THREE.PointsMaterial({
      color:new THREE.Color(emberCfg.color||'#ffb066').getHex(),
      size:emberCfg.size??0.14, sizeAttenuation:true,
      transparent:true, opacity:0.75,
      blending:THREE.AdditiveBlending, depthWrite:false,
    })
    const pts=new THREE.Points(geo,mat)
    sc.add(pts); envObjects.push(pts); atmos.embers=pts; atmos.emberData=data
  }
}

function updateAtmosphere(t, dt) {
  // 星光闪烁（整体呼吸 + 极慢自转）
  if (atmos.stars) {
    atmos.stars.material.opacity = 0.72 + Math.sin(t*0.0005)*0.18
    atmos.stars.rotation.y += dt*0.004
  }
  // 烛烬上升 + 横向摆动
  if (atmos.embers && atmos.emberData) {
    const attr = atmos.embers.geometry.getAttribute('position')
    const arr = attr.array
    for(let i=0;i<atmos.emberData.length;i++){
      const d=atmos.emberData[i]
      arr[i*3+1]+=d.vy*dt
      arr[i*3]+=Math.sin(t*0.001+d.phase)*d.amp*dt
      if(arr[i*3+1]>11){ arr[i*3+1]=0.05 }
    }
    attr.needsUpdate=true
    atmos.embers.material.opacity = 0.6 + Math.sin(t*0.0012)*0.15
  }
}

function safeNum(v, fallback) { const n = Number(v); return (isFinite(n) && n > 0) ? n : fallback }

function buildPrimitive(prim) {
  const shape = prim.shape || 'box'
  const sz = prim.size || [1,1,1]
  // 防御性参数清洗：所有几何体参数必须为有限正数，否则 fallback 到安全默认值
  const s0 = safeNum(sz[0], 1), s1 = safeNum(sz[1], 1), s2 = safeNum(sz[2], 1)
  const matOpts = { color:new THREE.Color(prim.color||'#888').getHex(), roughness:prim.roughness??0.8 }
  if(prim.metalness!==undefined)matOpts.metalness=prim.metalness
  if(prim.emissive)matOpts.emissive=new THREE.Color(prim.emissive).getHex()
  if(prim.emissive_intensity!==undefined)matOpts.emissiveIntensity=prim.emissive_intensity
  if(prim.flat_shading)matOpts.flatShading=true
  const mat = new THREE.MeshStandardMaterial(matOpts)
  let geo
  try {
    if(shape==='box') geo=new THREE.BoxGeometry(s0,s1,s2)
    else if(shape==='cylinder') geo=new THREE.CylinderGeometry(s0,s1,s2,12)
    else if(shape==='sphere') geo=new THREE.SphereGeometry(s0,12,10)
    else if(shape==='cone') geo=new THREE.ConeGeometry(s0,s1,6)
    else if(shape==='torus') {
      // TorusGeometry(radius, tube, radialSegments, tubularSegments)
      // sz[2] 如果是整数则用作 tubularSegments，否则用默认 24
      const tubularSeg = Number.isInteger(sz[2]) ? Math.max(3, sz[2]) : 24
      geo=new THREE.TorusGeometry(s0, s1, 8, tubularSeg)
    }
    else geo=new THREE.BoxGeometry(s0,s1,s2)
  } catch(e) {
    console.warn('[buildPrimitive] geometry creation failed, using fallback box:', shape, e.message)
    geo=new THREE.BoxGeometry(1,1,1)
  }
  const mesh=new THREE.Mesh(geo,mat)
  if(prim.position)mesh.position.set(...prim.position)
  if(prim.rotation)mesh.rotation.set(...prim.rotation)
  mesh.castShadow=true; mesh.receiveShadow=true
  return mesh
}

function buildPropFromConfig(sc, p) {
  const grp=new THREE.Group()
  const[x,y,z]=p.position||[0,0,0]
  grp.position.set(x,y,z)
  if(p.rotation)grp.rotation.y=p.rotation
  if(p.scale&&p.scale!==1)grp.scale.setScalar(p.scale)
  // repeat 模式：沿圆环排列多个相同图元
  if(p.repeat) {
    try {
      const rp=p.repeat, n=rp.count||8, r=rp.radius||10, yo=rp.y_offset||0
      for(let i=0;i<n;i++){
        const a=(i/n)*Math.PI*2
        const mesh=buildPrimitive(rp)
        mesh.position.set(Math.cos(a)*r, yo, Math.sin(a)*r)
        grp.add(mesh)
      }
    } catch(e) { console.warn('[buildPropFromConfig] repeat build failed:', p?.name, e.message) }
  }
  // primitives 列表
  if(p.primitives) {
    for(const prim of p.primitives) {
      try { grp.add(buildPrimitive(prim)) }
      catch(e) { console.warn('[buildPropFromConfig] primitive build failed:', p?.name, e.message) }
    }
  }
  // 光源
  if(p.light) {
    const lt=p.light.type||'point'
    if(lt==='point'){
      const l=new THREE.PointLight(new THREE.Color(p.light.color||'#fff').getHex(), p.light.intensity??1, p.light.distance??0, p.light.decay??2)
      if(p.light.position)l.position.set(...p.light.position)
      grp.add(l)
    }
  }
  sc.add(grp); envObjects.push(grp)
  return grp
}

function buildProps(sc, env={}) {
  sc.userData=sc.userData||{}
  for(const p of (env.props||[])) {
    try {
      const grp=buildPropFromConfig(sc, p)
      // GLB asset 优先加载（如果有非空GLB则替换primitives）
      if(p.asset) {
        const url=resolveAsset(p.asset)
        if(glbCache[url]) {
          if(hasGLBContent(glbCache[url])) { replaceGroupWithGLB(grp, glbCache[url], p) }
        } else {
          loadGLB(url, gltf=>{ if(hasGLBContent(gltf)) replaceGroupWithGLB(grp, gltf, p) }, true)
        }
      }
    } catch(e) {
      console.warn('[buildProps] prop build failed, skipping:', p?.name||p?.asset||'unknown', e.message)
    }
  }
}

function replaceGroupWithGLB(grp, gltf, p) {
  while(grp.children.length>0)grp.remove(grp.children[0])
  const clone=SkeletonUtils.clone(gltf.scene)
  clone.traverse(c=>{ if(c.isMesh){c.castShadow=true} })
  grp.add(clone)
}

function makeVignette(){ return new ShaderPass({ uniforms:{tDiffuse:{value:null},offset:{value:1.1},darkness:{value:1.2}}, vertexShader:`varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`, fragmentShader:`uniform sampler2D tDiffuse;uniform float offset;uniform float darkness;varying vec2 vUv;void main(){vec4 t=texture2D(tDiffuse,vUv);vec2 uv=(vUv-.5)*offset;float v=clamp(1.0-dot(uv,uv)*darkness,0.0,1.0);t.rgb*=v;gl_FragColor=t;}` }) }

const loader = new GLTFLoader()

// ━━ GLB 角色 + 动作库（含骨骼 Mixamo，离线 assimp 转换）━━
// character_base.glb（Jogging）：含骨骼蒙皮 + jog 动画，作为可视基础角色
// anim_celebrate/shoved.glb：仅取 animations[0] 作动作 clip；三者共享 mixamorig 骨架，
// AnimationMixer 按骨名重定向，缺失的骨骼轨道自动忽略。
// 均为米制（~1.8m），无需缩放；落地偏移让脚底贴 y=0。
let fbxBundle = null            // { base: Object3D, clips: {jog,celebrate,shoved,idle}, groundOffset }
let fbxBundlePromise = null
const GLB_CHAR_ASSETS = {
  base: '/models/glb/character_base.glb',
  animations: {
    celebrate: '/models/glb/anim_celebrate.glb',
    shoved: '/models/glb/anim_shoved.glb',
    angry: '/models/glb/anim_angry.glb',
    sad_idle: '/models/glb/anim_sad_idle.glb',
    sitting_talking: '/models/glb/anim_sitting_talking.glb',
    taunt: '/models/glb/anim_taunt.glb',
    walking: '/models/glb/anim_walking.glb',
  },
}

function hasFBXMesh(obj) {
  if (!obj) return false
  let found = false
  obj.traverse(c => { if (c.isMesh || c.isSkinnedMesh) found = true })
  return found
}

function loadFBXBundle() {
  if (fbxBundle) return Promise.resolve(fbxBundle)
  if (fbxBundlePromise) return fbxBundlePromise
  const loadOne = url => new Promise((resolve, reject) => {
    loader.load(url, resolve, undefined, reject)
  })
  // 去根位移（原地播放）：只把根骨 Hips 的"水平位移"锁定到首帧，保留 Y 起伏与其余所有轨道。
  // 关键：这些 assimp 导出的 Mixamo 骨架依赖各骨的 position 轨道维持骨长，整条剔除会让蒙皮塌成
  // 一点（人物消失）。所以只动 Hips 的 X/Z，既消除"人物漂走、名字留原地"，又保住骨架完整。
  const inPlace = (clip, name) => {
    const c = clip.clone()
    for (const t of c.tracks) {
      if (!t.name.endsWith('.position') || !/Hips/i.test(t.name)) continue
      const v = t.values            // [x,y,z, x,y,z, ...]
      const x0 = v[0], z0 = v[2]
      for (let i = 0; i < v.length; i += 3) { v[i] = x0; v[i + 2] = z0 }
    }
    c.name = name
    return c
  }
  fbxBundlePromise = (async () => {
    try {
      const [baseGltf, celebrateGltf, shovedGltf, angryGltf, sadIdleGltf, sittingGltf, tauntGltf, walkingGltf] = await Promise.all([
        loadOne(GLB_CHAR_ASSETS.base),
        loadOne(GLB_CHAR_ASSETS.animations.celebrate).catch(err => { console.warn('[GLB角色] celebrate 加载失败', err.message); return null }),
        loadOne(GLB_CHAR_ASSETS.animations.shoved).catch(err => { console.warn('[GLB角色] shoved 加载失败', err.message); return null }),
        loadOne(GLB_CHAR_ASSETS.animations.angry).catch(err => { console.warn('[GLB角色] angry 加载失败', err.message); return null }),
        loadOne(GLB_CHAR_ASSETS.animations.sad_idle).catch(err => { console.warn('[GLB角色] sad_idle 加载失败', err.message); return null }),
        loadOne(GLB_CHAR_ASSETS.animations.sitting_talking).catch(err => { console.warn('[GLB角色] sitting_talking 加载失败', err.message); return null }),
        loadOne(GLB_CHAR_ASSETS.animations.taunt).catch(err => { console.warn('[GLB角色] taunt 加载失败', err.message); return null }),
        loadOne(GLB_CHAR_ASSETS.animations.walking).catch(err => { console.warn('[GLB角色] walking 加载失败', err.message); return null }),
      ])
      const base = baseGltf.scene
      if (!hasFBXMesh(base)) throw new Error('character_base.glb 无可视 mesh')

      // 落地偏移：脚底贴 y=0（Mixamo 原点在头顶，min.y 为负）
      const box = new THREE.Box3().setFromObject(base)
      const groundOffset = -box.min.y

      const clips = {}
      if (baseGltf.animations?.length) clips.jog = inPlace(baseGltf.animations[0], 'jog')
      if (celebrateGltf?.animations?.length) clips.celebrate = inPlace(celebrateGltf.animations[0], 'celebrate')
      if (shovedGltf?.animations?.length) clips.shoved = inPlace(shovedGltf.animations[0], 'shoved')
      if (angryGltf?.animations?.length) clips.angry = inPlace(angryGltf.animations[0], 'angry')
      if (sadIdleGltf?.animations?.length) clips.sad_idle = inPlace(sadIdleGltf.animations[0], 'sad_idle')
      if (sittingGltf?.animations?.length) clips.sitting_talking = inPlace(sittingGltf.animations[0], 'sitting_talking')
      if (tauntGltf?.animations?.length) clips.taunt = inPlace(tauntGltf.animations[0], 'taunt')
      if (walkingGltf?.animations?.length) clips.walking = inPlace(walkingGltf.animations[0], 'walking')
      if (clips.jog) clips.idle = clips.jog
      if (clips.sad_idle) clips.idle = clips.sad_idle   // 优先用悲伤待机作默认 idle

      fbxBundle = { base, clips, groundOffset }
      console.log(
        '[GLB角色] bundle ready, clips:', Object.keys(clips),
        ', groundOffset:', groundOffset.toFixed(2)
      )
      // 已就位角色：fallback → FBX 升级（各自 GLB 的 clip 由 playAnimation 动态注入）
      for (const e of Object.values(agentMeshes)) {
        if (e?.usedFallback) upgradeAgentToFBX(e)
      }
      return fbxBundle
    } catch (err) {
      console.error('[GLB角色] 基础角色加载失败:', err.message)
      throw err
    }
  })()
  return fbxBundlePromise
}

function applyFBXToGroup(group, color) {
  if (!fbxBundle || !hasFBXMesh(fbxBundle.base)) return false
  const clone = SkeletonUtils.clone(fbxBundle.base)
  // assimp 转出的 GLB 已是米制（~1.8m），无需缩放。
  // 落地/对齐（系统性结论）：这套 Mixamo 动作的「绑定姿势(bind pose)」顶点被烘焙在 x≈69 处，
  // 但那一帧从不渲染 —— 一旦动作播放，clip 的骨骼轨道会把人物驱动回原点、脚底自然落在 y=0：
  //   bind pose:      x∈[68.6,69.6]            （不渲染）
  //   jog 播放后:     x∈[-0.32,0.33] y∈[0,1.88]（居中 + 落地）
  // 故绝不能按 bind pose 的包围盒去偏移：之前 +3 的 Y 抬升 → 悬空；-69 的 X 平移 → 飞出视野不可见。
  // 正确做法：不加任何偏移，让动作自身定位。Hips 的 X/Z 已在 inPlace 里锁定，不会水平漂移。
  clone.scale.setScalar(1)
  clone.position.set(0, 0, 0)
  clone.updateMatrixWorld(true)
  // 染色（复用 GLB 的逻辑）
  tintGLBClone(clone, color)
  group.add(clone)
  // 阵营脚灯
  const li = new THREE.PointLight(color, 0.25, 2.0)
  li.position.set(0, 0.15, -0.3)
  group.add(li)
  // 动作 mixer
  const mx = new THREE.AnimationMixer(clone)
  // clips 含 idle(=jog) 别名，去重后作为可切换动作集
  const allClips = []
  const seen = new Set()
  for (const c of Object.values(fbxBundle.clips)) { if (c && !seen.has(c)) { seen.add(c); allClips.push(c) } }
  let initialAction = null
  const idleClip = fbxBundle.clips.idle || fbxBundle.clips.jog || allClips[0]
  if (idleClip) {
    initialAction = mx.clipAction(idleClip)
    initialAction.play()
  }
  mixers.push(mx)
  group.userData.mixer = mx
  group.userData.gltfAnimations = allClips
  group.userData.currentAction = initialAction
  group.userData.fbxClone = clone   // 升级时区分 mesh
  group.userData.labelFollowTarget = selectLabelFollowTarget(clone)
  // 关闭视锥剔除：这套 assimp/Mixamo 蒙皮的几何包围球被烘焙在 bind pose(x≈69)，
  // 动作播放把顶点驱回原点后 three.js 不会重算包围球，于是按 x≈69 的陈旧包围球做
  // 视锥裁剪可能让角色身体消失而标签仍在，因此禁用角色网格剔除。
  // 直接禁用 frustumCulled，保证蒙皮恒可见。
  clone.traverse(c => { if (c.isMesh) { c.castShadow = true; c.frustumCulled = false } })
  return true
}

// 已有 fallback 占位角色：FBX 就绪后才尝试替换；
// 替换失败（FBX 无 mesh / 异常）保持 fallback 可见，绝不让角色凭空消失。
function upgradeAgentToFBX(entry) {
  if (!entry?.group || !fbxBundle) return
  const g = entry.group
  // 先在临时 group 上验证 FBX 能否成功应用
  const probeGroup = new THREE.Group()
  const color = g.userData.__color || new THREE.Color('#fff')
  const ok = applyFBXToGroup(probeGroup, color)
  if (!ok) {
    console.warn('[FBX] 升级失败，保留 fallback mesh:', entry.labelEl?.textContent)
    return
  }
  // FBX 成功 → 清掉 fallback mesh，把 FBX clone 迁移到 g
  const toRemove = []
  for (const child of g.children) {
    if (child.isMesh && !child.userData.__keep) toRemove.push(child)
  }
  for (const m of toRemove) g.remove(m)
  // 把 probeGroup 的内容移到 g（保留原 g 的 ring/label）
  while (probeGroup.children.length) {
    const child = probeGroup.children[0]
    probeGroup.remove(child)
    g.add(child)
  }
  g.userData.mixer = probeGroup.userData.mixer
  g.userData.gltfAnimations = probeGroup.userData.gltfAnimations
  g.userData.currentAction = probeGroup.userData.currentAction
  g.userData.fbxClone = probeGroup.userData.fbxClone
  entry.usedFallback = false
  g.userData.usedFallback = false
}
function resolveAsset(path) {
  if (!path) return ''
  if (path.startsWith('/') || path.startsWith('http')) return path
  // 场景包允许写 assets/foo.glb 或 foo.glb，两者都只拼一次 assets/。
  const normalized = String(path).replace(/^\.?\//, '').replace(/^assets\//, '')
  return `${API_BASE}/scenario-assets/${scenarioName}/assets/${normalized}`
}
function modelUrlFor(agent) {
  // 角色形象完全由场景包角色配置提供。OS/前端不认识任何具体场景角色 ID。
  return resolveAsset(roleModels[agent.agent_id])
    || defaultGLBUrl
    || '/models/default_character.glb'
}

function hasGLBContent(gltf) { let meshCount=0; gltf.scene.traverse(c=>{ if(c.isMesh)meshCount++ }); return meshCount>0 }

function loadGLB(url, cb, suppressWarn) { if(!url)return; if(glbCache[url]){ cb(glbCache[url]); return } loader.load(url, gltf=>{ glbCache[url]=gltf; cb(gltf) }, undefined, err=>{ if(!suppressWarn) console.warn('GLB fail:',url,err.message) }) }

// 角色染色：克隆 GLB 后按场景声明的 agent.color 染色。
function tintGLBClone(clone, color) {
  clone.traverse(c => {
    if (!c.isMesh || !c.material) return
    // 克隆材质避免污染原 GLB cache 共享的同一份 material
    c.material = c.material.clone()
    // 有贴图的模型只做极轻微染色，保留原贴图细节；无贴图的才按 agent.color 重染
    const hasMap = !!c.material.map
    if (c.material.color) {
      const base = c.material.color.clone()
      const tinted = base.lerp(color, hasMap ? 0.06 : 0.55)
      c.material.color.copy(tinted)
    }
    // 发射光仅作微弱阵营点缀；有贴图时几乎不加，避免泛色糊面
    if (c.material.emissive) {
      c.material.emissive = new THREE.Color(color).multiplyScalar(hasMap ? 0.04 : 0.12)
    }
  })
}

function makeClipInPlace(clip, name = clip.name) {
  const c = clip.clone()
  for (const t of c.tracks || []) {
    if (!t.name.endsWith('.position')) continue
    if (!/(^|[./])(hips|mixamorighips|root|armature)([./]|$)/i.test(t.name)) continue
    const v = t.values
    const x0 = v[0], z0 = v[2]
    for (let i = 0; i < v.length; i += 3) {
      v[i] = x0
      v[i + 2] = z0
    }
  }
  c.name = name || clip.name
  return c
}

function selectLabelFollowTarget(root) {
  let head = null
  let neck = null
  let hips = null
  root?.traverse?.(obj => {
    if (!obj.isBone && !obj.isObject3D) return
    const name = obj.name || ''
    if (!head && /(^|[_-])head($|[_-])|mixamorighead/i.test(name)) head = obj
    else if (!neck && /neck/i.test(name)) neck = obj
    else if (!hips && /hips|pelvis/i.test(name)) hips = obj
  })
  return head || neck || hips || root || null
}

const _labelWorldPos = new THREE.Vector3()
const _labelLocalPos = new THREE.Vector3()
function syncAgentLabel(entry) {
  const group = entry?.group
  const label = entry?.labelObject || group?.userData?.labelObject
  if (!group || !label) return
  const target = group.userData.labelFollowTarget
  if (!target) {
    label.position.set(0, 2.6, 0)
    return
  }
  target.updateWorldMatrix(true, false)
  target.getWorldPosition(_labelWorldPos)
  group.worldToLocal(_labelLocalPos.copy(_labelWorldPos))
  const isHeadLike = /head|neck/i.test(target.name || '')
  label.position.set(_labelLocalPos.x, _labelLocalPos.y + (isHeadLike ? 0.38 : 1.45), _labelLocalPos.z)
}

function applyGLB(group, color, gltf) {
  if (!hasGLBContent(gltf)) { console.warn('[GLB] 模型无网格内容，跳过'); return false }
  const clone = SkeletonUtils.clone(gltf.scene)
  // 自动缩放：根据包围盒把模型统一拉到 ~1.8m 身高
  const box = new THREE.Box3().setFromObject(clone)
  const height = box.max.y - box.min.y
  if (height > 0.01 && (height < 0.5 || height > 3.0)) {
    const targetHeight = 1.8
    const scale = targetHeight / height
    clone.scale.setScalar(scale)
    console.log(`[GLB] 自动缩放: height=${height.toFixed(2)} → ${targetHeight}, scale=${scale.toFixed(2)}`)
  }
  tintGLBClone(clone, color)
  group.add(clone)
  // 微弱阵营脚灯：低强度、置于脚下偏后，避免贴脸打爆面部（仅作地面色晕点缀）
  const li = new THREE.PointLight(color, .25, 2.0); li.position.set(0, .15, -.3); group.add(li)
  const mx = new THREE.AnimationMixer(clone)
  const clips = (gltf.animations || []).map(c => makeClipInPlace(c))
  const clip = THREE.AnimationClip.findByName(clips, 'Idle')
    || clips.find(c => /idle|stand|breath/i.test(c.name || ''))
  const act = clip ? mx.clipAction(clip) : (clips.length ? mx.clipAction(clips[0]) : null)
  if (act) act.play()
  mixers.push(mx)
  // 每个角色起步只挂自己 GLB 的 clip，共享动画按剧情动态注入
  group.userData.mixer = mx
  group.userData.gltfAnimations = clips
  group.userData.currentAction = act
  group.userData.labelFollowTarget = selectLabelFollowTarget(clone)
  // 同 FBX：禁用蒙皮视锥剔除，避免 bind-pose 陈旧包围球导致角色随机消失
  clone.traverse(c => { if (c.isMesh) { c.castShadow = true; c.frustumCulled = false } })
  return true
}

function buildAgentMesh(agent) {
  const slot = agentSlots.find(s => s.id === agent.agent_id)
  const color = new THREE.Color(agent.color || slot?.color || '#fff')
  const group = new THREE.Group()
  const sp = SPAWN_POSITIONS[spawnIdx % Math.max(1, SPAWN_POSITIONS.length)] || new THREE.Vector3(0, 0, 0)
  spawnIdx++
  group.position.copy(sp)
  group.userData = { targetPos: sp.clone(), isAlive: true, __color: color.clone() }
  const characterRender = renderCharacterForAgent(agent.agent_id)
  const flatAsset = characterRender
    && ['svg', 'png', 'jpg', 'jpeg', 'webp'].includes(String(characterRender.format || '').toLowerCase())
      ? resolveAsset(characterRender.asset)
      : ''
  // 按场景声明选择媒介：2D 角色平面 → GLB → FBX → 程序化兜底。
  const url = modelUrlFor(agent)
  console.log(`[AgentModel] ${agent.agent_id} url=${url} inCache=${!!glbCache[url]} hasFBX=${!!fbxBundle}`)
  if (flatAsset) {
    applyFlatCharacter(group, flatAsset, characterRender.scale || 1)
    group.userData.usedFallback = false
  } else if (glbCache[url]) {
    const ok = applyGLB(group, color, glbCache[url])
    console.log(`[AgentModel] ${agent.agent_id} per-agent GLB ok=${ok}`)
    group.userData.usedFallback = !ok
    if (!ok) buildFallback(group, color)
  } else if (fbxBundle && !url) {
    // 无专属 GLB 时退回 FBX 共享骨骼
    applyFBXToGroup(group, color)
    group.userData.usedFallback = false
  } else {
    // 两者都未就绪：先用程序化兜底，异步加载 GLB
    buildFallback(group, color)
    group.userData.usedFallback = true
    if (url) {
      loadGLB(url, gltf => {
        const e = agentMeshes[agent.agent_id]
        if (e && e.usedFallback && hasGLBContent(gltf)) replaceGLB(e, agent, gltf)
      })
    }
  }
  const ld = document.createElement('div')
  ld.className = 'agent-label'
  ld.textContent = agent.name || slot?.name || agent.agent_id
  const lb = new CSS2DObject(ld)
  lb.position.y = 2.6
  group.add(lb)
  group.userData.labelObject = lb
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(.5, .7, 32),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .7, side: THREE.DoubleSide })
  )
  ring.rotation.x = -Math.PI / 2
  ring.position.y = .02
  ring.userData.__keep = true   // 升级时不要清掉 ring
  group.add(ring)
  group.userData.ring = ring
  scene.value.add(group)
  agentMeshes[agent.agent_id] = { group, labelEl: ld, labelObject: lb, usedFallback: group.userData.usedFallback }
  return group
}

function renderCharacterForAgent(agentId) {
  const slot = agentSlots.find(item => item.id === agentId) || {}
  const bindings = renderCfg?.bindings?.characters || {}
  const candidate = slot.character_id || slot.capability_profile?.character_id || agentId
  const binding = bindings[candidate] || bindings[agentId] || candidate
  return renderCfg?.characters?.[binding] || null
}

function applyFlatCharacter(group, assetUrl, scale = 1) {
  const material = new THREE.SpriteMaterial({
    map: new THREE.TextureLoader().load(assetUrl),
    transparent: true,
    depthWrite: false,
  })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(1.6 * scale, 2.2 * scale, 1)
  sprite.position.y = 1.1 * scale
  sprite.userData.cameraIgnore = true
  group.add(sprite)
  group.userData.labelFollowTarget = sprite
}

function buildFallback(group, color) {
  const c = agentFallbackCfg || {}
  const mat = c.material || {}
  const sk = new THREE.MeshStandardMaterial({color, roughness:mat.body_roughness??0.6, metalness:mat.body_metalness??0.1})
  const dk = new THREE.MeshStandardMaterial({color:new THREE.Color(mat.legs_color||'#2a2530').getHex(), roughness:mat.legs_roughness??0.8})
  const fc = new THREE.MeshStandardMaterial({color:new THREE.Color(mat.face_color||'#f2d2b6').getHex(), roughness:mat.face_roughness??0.7, flatShading:true})
  const bsz = c.body_size||[0.32,0.7]
  const bo = new THREE.Mesh(new THREE.CapsuleGeometry(bsz[0],bsz[1],4,8), sk)
  bo.position.y = c.body_y??0.95; bo.castShadow=true
  const hsz = c.head_size||0.28
  const he = new THREE.Mesh(new THREE.IcosahedronGeometry(hsz,0), fc)
  he.position.y = c.head_y??1.6; he.castShadow=true
  const lsz = c.legs_size||[0.11,0.6]
  const ll = new THREE.Mesh(new THREE.CylinderGeometry(lsz[0],lsz[0],lsz[1],6), dk)
  ll.position.set(-0.15, c.legs_y??0.3, 0); ll.castShadow=true
  const lr = ll.clone(); lr.position.x=0.15
  group.add(bo,he,ll,lr); group.userData.legL=ll; group.userData.legR=lr
  group.userData.labelFollowTarget = he
}

function replaceGLB(entry, agent, gltf) { const rm=[]; entry.group.traverse(c=>{ if(c===entry.group||c.element||c===entry.group.userData.ring)return; rm.push(c) }); rm.forEach(c=>entry.group.remove(c)); const ok=applyGLB(entry.group, new THREE.Color(agent.color||'#fff'), gltf); if(!ok){ buildFallback(entry.group, new THREE.Color(agent.color||'#fff')); entry.usedFallback=true }else{ entry.usedFallback=false } }

function updateAgentMeshes(agents, agentLocations) {
  if(!scene.value) return;
  for(const a of agents) {
    let e = agentMeshes[a.agent_id];
    if(!e) { buildAgentMesh(a); e = agentMeshes[a.agent_id] }
    if(e.labelEl && e.labelEl.textContent !== (a.name||a.agent_id)) e.labelEl.textContent = a.name||a.agent_id;
    // 出局（活死人）视觉与"淘汰"一致：倒地退场。圈禁者环圈转灰。
    const down = !a.is_alive || isEliminated(a.agent_id);
    const c = new THREE.Color(down ? '#5a5f6b' : (a.color||'#fff'));
    if(e.group.userData.ring) e.group.userData.ring.material.color.set(c);
    if(down && e.group.userData.isAlive) { e.group.userData.isAlive=false; e.group.rotation.z=Math.PI/2; e.group.position.y=-.3 }
    else if(!down && !e.group.userData.isAlive) { e.group.userData.isAlive=true; e.group.rotation.z=0; e.group.position.y=Math.max(0,e.group.position.y) }
  }
  if(agentLocations) {
    // 构建完整的位置映射：包含 world_position + spawn_points
    // spawn_points 是场景包为同一地点内不同角色定义的独立站位
    const locMap = {};
    for(const [key, lr] of Object.entries(renderCfg?.locations||{})) {
      const wp = lr.world_position||{};
      const locId = key.replace('_render','');
      locMap[locId] = {
        worldPos: new THREE.Vector3(wp.x||0, wp.y||0, wp.z||0),
        spawnPoints: lr.spawn_points || {}
      };
    }
    if(agents.length === 0 && Object.keys(agentLocations).length > 0) {
      for(const slot of agentSlots) {
        const locId = agentLocations[slot.id];
        if(!locId || agentMeshes[slot.id]) continue;
        const fakeAgent = { agent_id: slot.id, name: slot.name, color: slot.color, is_alive: true };
        buildAgentMesh(fakeAgent);
      }
    }
    const allAgentIds = agents.length > 0 ? agents.map(a=>a.agent_id) : Object.keys(agentLocations);
    for(const aid of allAgentIds) {
      const e = agentMeshes[aid];
      if(!e || !e.group.userData.isAlive) continue;
      const locId = agentLocations[aid];
      if(!locId) continue;
      const locInfo = locMap[locId];
      if(!locInfo) continue;

      // 优先用 spawn_points 中对应 agent_id 的独立站位，fallback 到 default，再 fallback 到 地点中心
      let targetPos;
      const sp = (locInfo.spawnPoints && locInfo.spawnPoints[aid])
                || (locInfo.spawnPoints && locInfo.spawnPoints['default']);
      if(sp && (sp.x !== undefined || sp.y !== undefined || sp.z !== undefined)) {
        targetPos = new THREE.Vector3(sp.x||0, sp.y||0, sp.z||0);
      } else {
        targetPos = locInfo.worldPos;
      }

      if(targetPos && !targetPos.equals(e.group.userData.targetPos)) {
        e.group.userData.targetPos = targetPos.clone();
        e.group.userData.moving = true
      }
    }
    const mc = locMarkerCfg||{};
    const idleCol = new THREE.Color(mc.idle_color||'#c9a85c').getHex();
    const activeCol = new THREE.Color(mc.active_color||'#00d4ff').getHex();
    const idleOp = mc.idle_opacity??0.08, activeOp = mc.active_opacity??0.28;
    const occupied = new Set();
    for(const aid of Object.keys(agentLocations)) {
      const locId = agentLocations[aid];
      if(locId) occupied.add(locId)
    }
    for(const [locId, mk] of Object.entries(locMarkerMap)) {
      if(mk.labelEl) mk.labelEl.style.opacity = occupied.has(locId) ? '0.85' : '0';
      if(mk.ring) {
        mk.ring.material.opacity = occupied.has(locId) ? activeOp : idleOp;
        mk.ring.material.color.setHex(occupied.has(locId) ? activeCol : idleCol)
      }
    }
  }
}

function resolveLocationPosition(locId, agentId) {
  if (!locId) return null
  const direct = renderCfg?.locations?.[locId]
    || renderCfg?.locations?.[`${locId}_render`]
  if (!direct) return locMarkerMap[locId]?.position?.clone() || null
  const spawn = direct.spawn_points?.[agentId] || direct.spawn_points?.default
  const value = spawn || direct.world_position
  if (!value) return null
  return new THREE.Vector3(value.x || 0, value.y || 0, value.z || 0)
}

function resolveObjectPosition(objectId, objectRender = {}) {
  const position = objectRender.position || {}
  const locationId = position.location
  const locationBinding = renderCfg?.bindings?.locations?.[locationId]
  const location = renderCfg?.locations?.[locationBinding]
    || renderCfg?.locations?.[locationId]
    || renderCfg?.locations?.[`${locationId}_render`]
  const value = location?.anchors?.[position.anchor] || location?.world_position
  if (value) return new THREE.Vector3(value.x || 0, value.y || 0, value.z || 0)
  return new THREE.Vector3(0, 0, 0)
}

let animId=null, lastT=0
function animate(t=0){ animId=requestAnimationFrame(animate); const dt=Math.min(.05,(t-lastT)/1000); lastT=t; for(const mx of mixers)mx.update(dt); const wa=agentFallbackCfg?.walk_animation||{}; const ws=wa.leg_swing??0.3, wsp=wa.speed??0.003; for(const e of Object.values(agentMeshes)){ if(e.usedFallback&&e.group.userData.isAlive){ const ll=e.group.userData.legL,lr=e.group.userData.legR; if(ll)ll.rotation.x=Math.sin(t*wsp)*ws; if(lr)lr.rotation.x=-Math.sin(t*wsp)*ws } if(e.group.userData.moving&&e.group.userData.targetPos){ const tp=e.group.userData.targetPos; e.group.position.lerp(tp, Math.min(1,dt*3)); if(e.group.position.distanceTo(tp)<.05){ e.group.position.copy(tp); e.group.userData.moving=false } } syncAgentLabel(e) }; presentationExecutor?.update(t); effectEngine?.update(dt); updateAtmosphere(t,dt); controls.value?.update(); composer.value?.render(); labelRdr.value?.render(scene.value,camera.value) }

function onResize(){ const el=mountEl.value; if(!el)return; const w=el.clientWidth,h=el.clientHeight; camera.value.aspect=w/h; camera.value.updateProjectionMatrix(); renderer.value.setSize(w,h); labelRdr.value.setSize(w,h); composer.value.setSize(w,h) }

function agentName(id){ return snapshot.value.agents?.find(a=>a.agent_id===id)?.name||id }
function agentColor(id){ return snapshot.value.agents?.find(a=>a.agent_id===id)?.color||'#ccc' }
function isEliminated(id){ return (snapshot.value.eliminated||[]).some(e=>e&&e.agent_id===id) }
// 角色内心 / 投资策略同步：写进对应卡片。
// 关键修复：首回合 world_snapshot 还没到达（它挂在本 tick 最后一个 segment 上），
// snapshot.agents 仍为空，导致「等待角色出场」。这里若卡片不存在则用 agentSlots 兜底创建，
// 保证「角色先开口」时内心面板一定有内容。
function upsertAgentCardFields(actorId, { monologue, strategy } = {}) {
  if (!actorId) return
  const nextMono = monologue !== undefined ? String(monologue || '').trim() : undefined
  const nextStrategy = strategy !== undefined ? String(strategy || '').trim() : undefined
  if (!nextMono && !nextStrategy) return
  const agents = snapshot.value.agents || []
  if (agents.some(a => a.agent_id === actorId)) {
    snapshot.value = {
      ...snapshot.value,
      agents: agents.map((a) => {
        if (a.agent_id !== actorId) return a
        return {
          ...a,
          ...(nextMono ? { character_monologue: nextMono } : {}),
          ...(nextStrategy ? { public_reasoning_summary: nextStrategy } : {}),
        }
      }),
    }
  } else {
    const slot = (agentSlots || []).find(s => s.id === actorId) || {}
    snapshot.value = {
      ...snapshot.value,
      agents: [...agents, {
        agent_id: actorId,
        name: slot.name || actorId,
        color: slot.color || '#7dd3fc',
        is_alive: true,
        character_monologue: nextMono || '',
        public_reasoning_summary: nextStrategy || '',
      }],
    }
  }
}
function upsertAgentMonologue(actorId, monologue) {
  upsertAgentCardFields(actorId, { monologue })
}
function upsertAgentStrategy(actorId, strategy) {
  upsertAgentCardFields(actorId, { strategy })
}
function getMetricValue(mid){ const a=snapshot.value.agents||[]; for(const ag of a){ if(ag.public_attrs?.[mid]!==undefined) return ag.public_attrs[mid] } return 0 }
function isAgentAtLocation(locId){ const a=snapshot.value.agents||[]; return a.some(ag=>ag.public_attrs?.location===locId||ag.public_attrs?.current_location===locId) }

function pushFeed(e){
  const prev = narrativeFeed.value[narrativeFeed.value.length - 1]
  if (
    prev &&
    prev.tick === e.tick &&
    prev.type === e.type &&
    prev.speaker === e.speaker &&
    (prev.content || '').trim() === (e.content || '').trim()
  ) {
    return
  }
  narrativeFeed.value.push({ ...e, id: feedIdCtr++ });
  if(narrativeFeed.value.length>120)narrativeFeed.value.splice(0,20);
  persistNarrativeFeed()
  nextTick(()=>{ const el=feedEl.value; if(el)el.scrollTop=el.scrollHeight })
}

function persistNarrativeFeed() {
  saveNarrativeFeed({
    scenario: scenarioName || scenarioDisplayName.value || '',
    tick: snapshot.value.tick || 0,
    entries: narrativeFeed.value,
    feedIdCtr,
  })
}

function restoreNarrativeFeedIfNeeded() {
  if (narrativeFeed.value.length) return
  const cached = loadNarrativeFeed({
    scenario: scenarioName || scenarioDisplayName.value || '',
  })
  if (!cached?.entries?.length) return
  feedIdCtr = Math.max(Number(cached.feedIdCtr || 0), 0)
  narrativeFeed.value = cached.entries.map((item) => ({
    ...item,
    id: feedIdCtr++,
  }))
  nextTick(() => {
    const el = feedEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function importanceLabel(level){
  return {
    low: '略过',
    mid: '短演',
    high: '高光',
    critical: '关键',
  }[level] || '编排'
}

// 去重键：同一条旁白 chunk(source+tick+index)只播一次。
// 防止导演声音叠播两遍：按「音频内容指纹 + 时间窗」去重，能抓住同一段音频
// 以不同标签(intro/tick、full/chunk)或经 HMR 双连接、后端重发多次到达的情况。
const ttsRecentFP = new Map()   // 指纹 → 最近入队时间戳
const TTS_DEDUP_MS = 15000
function ttsFingerprint(b64){
  const s = String(b64 || '')
  return s.length + '|' + s.slice(0, 32) + '|' + s.slice(-32)
}
function playTTS(msg){
  if(!msg.audio_b64)return
  const fp = ttsFingerprint(msg.audio_b64)
  const now = Date.now()
  const last = ttsRecentFP.get(fp)
  if(last && now - last < TTS_DEDUP_MS) return   // 短时间内相同音频，丢弃重复
  ttsRecentFP.set(fp, now)
  if(ttsRecentFP.size > 64){
    for(const [k,t] of ttsRecentFP){ if(now - t > TTS_DEDUP_MS) ttsRecentFP.delete(k) }
  }
  ttsQueue.push({
    audio_b64: msg.audio_b64,
    source: msg.source || 'director',
    index: msg.index ?? -1,
    text: msg.text || '',
    onStart: msg.onStart,
    onEnd: msg.onEnd,
  })
  drainTTSQueue()
}

function drainTTSQueue(){
  if(currentTTSAudio || !ttsQueue.length)return
  const item=ttsQueue.shift()
  try{
    const audio=new Audio('data:audio/mp3;base64,'+item.audio_b64)
    audio.volume=0.8
    currentTTSAudio=audio
    currentTTSItem=item
    item.onStart?.(item)
    const finish=()=>{
      if(currentTTSAudio!==audio)return
      currentTTSAudio=null
      currentTTSItem=null
      item.onEnd?.(item)
      drainTTSQueue()
    }
    audio.onended=finish
    audio.onerror=finish
    audio.play().catch(e=>{console.warn('[tts] 播放失败',e.message);finish()})
  }catch(e){
    currentTTSAudio=null
    currentTTSItem=null
    console.warn('[tts] 创建Audio失败',e)
    drainTTSQueue()
  }
}

function clearTTSQueue(){
  ttsQueue.splice(0)
  if(currentTTSAudio){
    try{
      currentTTSAudio.onended=null
      currentTTSAudio.onerror=null
      currentTTSAudio.pause()
      currentTTSAudio.currentTime=0
    }catch(e){}
    currentTTSAudio=null
    currentTTSItem=null
  }
}

function stopTTSBySource(source) {
  for (let index = ttsQueue.length - 1; index >= 0; index--) {
    if (ttsQueue[index].source === source) ttsQueue.splice(index, 1)
  }
  if (currentTTSAudio && currentTTSItem?.source === source) {
    try {
      currentTTSAudio.onended = null
      currentTTSAudio.onerror = null
      currentTTSAudio.pause()
      currentTTSAudio.currentTime = 0
    } catch (error) {}
    currentTTSAudio = null
    currentTTSItem = null
    drainTTSQueue()
  }
}

function focusNoticeChunk(index) {
  noticeActiveChunk.value = index
  nextTick(() => {
    const body = noticeBodyEl.value
    const line = body?.querySelector(`[data-notice-chunk="${index}"]`)
    if (!body || !line) return
    const top = line.offsetTop - body.clientHeight * 0.36
    body.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  })
}

function noticeChunksFor(section) {
  return noticeSpeechChunks.value.filter(chunk => chunk.section === section)
}

function noticeChunkClass(chunk) {
  return ['notice-spoken-chunk', {
    active: noticeActiveChunk.value === chunk.index,
    played: chunk.index < noticeActiveChunk.value,
  }]
}

function queueNoticeSpeech() {
  stopTTSBySource('scenario_notice')
  noticeActiveChunk.value = -1
  const playable = noticeSpeechChunks.value.filter(chunk => chunk.audio_b64)
  if (!playable.length) {
    noticeTTSStatus.value = '当前未启用导演语音'
    return
  }
  noticeTTSStatus.value = `导演正在播报 · 0/${playable.length}`
  playable.forEach((chunk, order) => {
    playTTS({
      ...chunk,
      source: 'scenario_notice',
      onStart: () => {
        if (!showNotice.value) return
        noticeTTSStatus.value = `导演正在播报 · ${order + 1}/${playable.length}`
        focusNoticeChunk(chunk.index)
      },
      onEnd: () => {
        if (order === playable.length - 1 && showNotice.value) {
          noticeTTSStatus.value = '场景公告播报完毕'
          noticeActiveChunk.value = chunk.index
        }
      },
    })
  })
}

function closeScenarioNotice() {
  showNotice.value = false
  stopTTSBySource('scenario_notice')
  noticeActiveChunk.value = -1
  noticeTTSStatus.value = ''
}

function buildScenarioAnnouncementSections() {
  return [
    { section: 'background', text: displayBackgroundText.value },
    { section: 'goal', text: displayGoalText.value },
    { section: 'rules', text: victoryRuleLines.value.join('') },
  ].filter(item => item.text)
}

async function openScenarioNotice() {
  showNotice.value = true
  if (noticeSpeechChunks.value.length) {
    queueNoticeSpeech()
    return
  }
  const sections = buildScenarioAnnouncementSections()
  if (!sections.length) return
  noticeTTSStatus.value = '导演正在准备场景公告'
  try {
    const responses = await Promise.all(sections.map(async item => {
      const response = await authedFetch(`${API_BASE}/scenario/announcement/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: item.text }),
      })
      if (!response.ok) throw new Error(await response.text())
      return { section: item.section, data: await response.json() }
    }))
    let globalIndex = 0
    noticeSpeechChunks.value = responses.flatMap(({ section, data }) =>
      (data.chunks || [])
        .filter(item => item?.text)
        .map(item => ({ ...item, section, index: globalIndex++ }))
    )
    if (showNotice.value) queueNoticeSpeech()
  } catch (error) {
    noticeTTSStatus.value = '场景公告语音暂不可用'
    console.warn('[notice-tts] 合成失败', error)
  }
}

function handleReset(){
  if (isResetting.value) return
  isResetting.value = true;
  // 清除本地状态
  narrativeFeed.value = [];
  feedIdCtr = 0;
  lastAddedTick = -1;
  clearNarrativeFeed()
  snapshot.value = { tick: 0, is_running: false, is_game_over: false, agents: [], artifacts: [] };
  isComputing.value = false;
  waitingMessage.value = '正在重置本局…';
  simulationComplete.value = false;
  isReplaying.value = false;
  presentedTicks.clear();
  computedTick.value = 0;
  // 停止 TTS
  clearTTSQueue();
  // 发送 reset 命令
  ws.commands.reset();
}

function handlePause() {
  if (isResetting.value) return
  waitingMessage.value = ''
  isComputing.value = false
  ws.commands.pause()
}

function handlePlay() {
  if (isResetting.value) return
  // 回放模式（配置面板触发）：只恢复播放缓冲
  if (isReplaying.value) {
    waitingMessage.value = ''
    ws.commands.play()
    return
  }
  // 终局后不应静默跳进回放；需先重置再开新局
  if (snapshot.value.is_game_over) {
    isComputing.value = false
    waitingMessage.value = ''
    pushFeed({
      tick: snapshot.value.tick || 0,
      type: 'error',
      speaker: '系统',
      color: uiTheme?.error_color || '#ff6b6b',
      content: '本局已结束，请先点「重置」再开始新一局',
    })
    return
  }
  waitingMessage.value = wsConnected.value
    ? (snapshot.value.tick > 0 ? '正在继续推演…' : '正在启动推演…')
    : '正在连接引擎，开始命令已排队…'
  simulationComplete.value = false
  isComputing.value = true
  ws.commands.play()
}

function handleReplay(runId = null) {
  waitingMessage.value = '正在载入已完成演绎…'
  simulationComplete.value = false
  isReplaying.value = true
  ws.commands.replay(runId || selectedReplay.value || null)
}

function processEvents(events){
  for(const evt of events){
    if(evt.tick<=lastAddedTick) continue
    const meta = evt.metadata || {}
    // 事件语义与声音/特效绑定全部由当前场景包声明；OS 不识别业务事件名。
    audioEngine?.dispatchEvent(evt.event_type, meta)
    effectEngine?.dispatchEvent(evt.event_type, { ...meta, actorId: evt.source_id })
    // 不再把 evt.summary 推到剧情演绎面板。
    // 事件结果由 3D 视觉效果（脉冲光环 / 粒子）和导演旁白共同呈现，
    // 避免机械动作日志混入导演视角的剧情演绎区。
  }
}

// 挑战卡片：中央浮出 4 秒，醒目展示当前挑战
const currentMilestone = ref(null)
let challengeBannerTimer = null
function showMilestoneBanner(challenge){
  currentMilestone.value = challenge
  if(challengeBannerTimer) clearTimeout(challengeBannerTimer)
  challengeBannerTimer = setTimeout(() => { currentMilestone.value = null }, 4500)
}

function showActionEffects(events, agentLocations){ if(!events||events.length===0)return; for(const evt of events){ if(evt.tick<=lastAddedTick)continue; showAgentActionEffect(evt, agentLocations) } }

function showAgentActionEffect(evt, agentLocations){
  const aid=evt.source_id; if(!aid)return;
  const e=agentMeshes[aid]; if(!e||!e.group)return;
  const evtType=evt.event_type||'action';
  // 根据事件类型选择视觉效果
  let effectColor='#00d4ff'; let scale=1.3;
  if(evtType==='success'){ effectColor='#00ff88'; scale=1.4 }
  else if(evtType==='backlash'){ effectColor='#ff4444'; scale=1.2 }
  else if(evtType==='no_effect'){ effectColor='#888888'; scale=1.1 }
  else if(evtType==='invalid'){ effectColor='#ff6600'; scale=1.15 }
  // 创建脉冲光环
  try{
    const ring=new THREE.Mesh(new THREE.RingGeometry(0.8,1.0,32),new THREE.MeshBasicMaterial({color:new THREE.Color(effectColor),transparent:true,opacity:0.8,side:THREE.DoubleSide}));
    ring.rotation.x=-Math.PI/2; ring.position.y=0.05; ring.position.copy(e.group.position); ring.position.y=0.05;
    scene.value.add(ring);
    const startTime=performance.now(); const duration=1500;
    const animPulse=(now)=>{ const elapsed=now-startTime; if(elapsed>=duration){ scene.value.remove(ring); return } const t=elapsed/duration; ring.scale.setScalar(1+t*scale); ring.material.opacity=0.8*(1-t); requestAnimationFrame(animPulse) };
    requestAnimationFrame(animPulse);
  }catch(err){ /* ignore */ }
}

async function fetchConfig(){
  try{
    const r=await authedFetch(`${API_BASE}/config`);
    const d=await r.json();
    agentConfigs.value=(d.agents||[]).map(a=>normalizeAgentConfig({ ...a }, API_BASE));
    availableProviders.value=d.available_providers||['mock','openai','deepseek','anthropic','minimax','huggingface'];
  } catch(e){ console.warn('config fetch fail',e) }
}

async function setAgentDriver(agent, driver){
  if(!canEditModelConfig) return;
  cfgMsg.value='';
  try{
    await patchAgentDriver(API_BASE, agent.id, { driver });
    agent.driver=driver;
    if(driver==='agent'){
      if(!agent.join_url && !agent.has_join_token){
        const link=await createAgentLink(API_BASE, agent.id);
        applyLinkPayload(agent, link);
      }
      cfgMsg.value=`✅ ${agent.name} 已切换为外部 Agent 驱动`;
    }else{
      agent.join_url='';
      agent.copy_bundle='';
      agent.has_join_token=false;
      cfgMsg.value=`✅ ${agent.name} 已切换为 LLM 驱动`;
    }
    await fetchConfig();
  }catch(e){
    cfgMsg.value=`❌ ${e.message}`;
  }
}

async function regenerateAgentLink(agent){
  if(!canEditModelConfig) return;
  cfgMsg.value='';
  try{
    const link=await createAgentLink(API_BASE, agent.id);
    applyLinkPayload(agent, link);
    agent.driver='agent';
    cfgMsg.value=`✅ ${agent.name} 接入链接已${agent.join_url ? '更新' : '生成'}`;
    await fetchConfig();
  }catch(e){
    cfgMsg.value=`❌ ${e.message}`;
  }
}

async function revokeAgentLinkAction(agent){
  if(!canEditModelConfig) return;
  cfgMsg.value='';
  try{
    await revokeAgentLink(API_BASE, agent.id);
    agent.driver='llm';
    agent.join_url='';
    agent.copy_bundle='';
    agent.has_join_token=false;
    cfgMsg.value=`✅ ${agent.name} 链接已作废，已回落 LLM`;
    await fetchConfig();
  }catch(e){
    cfgMsg.value=`❌ ${e.message}`;
  }
}

async function copyJoinLink(agent){
  try{
    await copyToClipboard(agent.join_url);
    cfgMsg.value='✅ 接入链接已复制';
  }catch(e){
    cfgMsg.value=`❌ ${e.message}`;
  }
}

async function copyFullBundle(agent){
  try{
    const text=agent.copy_bundle || `Read ${agent.skill_url || skillDocUrl.value}, then connect with: ${agent.join_url}`;
    await copyToClipboard(text);
    cfgMsg.value='✅ 完整说明已复制';
  }catch(e){
    cfgMsg.value=`❌ ${e.message}`;
  }
}

let agentStatusTimer=null;
function startAgentStatusPoll(){
  stopAgentStatusPoll();
  agentStatusTimer=setInterval(()=>{ if(showConfig.value) fetchConfig(); }, 4000);
}
function stopAgentStatusPoll(){
  if(agentStatusTimer){ clearInterval(agentStatusTimer); agentStatusTimer=null; }
}
watch(showConfig,(open)=>{ if(open) startAgentStatusPoll(); else stopAgentStatusPoll(); });
async function fetchScenarios(){ try{ const r=await authedFetch(`${API_BASE}/scenarios`); const d=await r.json(); scenarios.value=d.scenarios||[]; selectedScenario.value=d.current||scenarios.value[0]||'' } catch(e){ console.warn('scenarios fetch fail',e) } }
async function onScenarioFileChosen(evt){
  const file = evt.target.files?.[0]
  evt.target.value = ''
  if(!file) return
  const name = file.name.replace(/\.zip$/i, '').replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 64) || `scenario_${Date.now()}`
  uploadMsg.value = '上传中…'
  try{
    const form = new FormData()
    form.append('file', file)
    const r = await authedFetch(`${API_BASE}/scenarios/upload?scenario_name=${encodeURIComponent(name)}`, { method:'POST', body: form })
    const data = await r.json().catch(()=>({}))
    if(!r.ok) throw new Error(data.detail || `上传失败(${r.status})`)
    uploadMsg.value = `✅ 已上传：${data.manifest_name || name}`
    await fetchScenarios()
    selectedScenario.value = name
  }catch(e){
    uploadMsg.value = `❌ ${e.message}`
  }
}
async function fetchReplays(){ try{ const r=await authedFetch(`${API_BASE}/replays`); const d=await r.json(); replays.value=d.replays||[]; if(!selectedReplay.value&&replays.value.length)selectedReplay.value=replays.value[0].run_id } catch(e){ console.warn('replays fetch fail',e) } }
async function fetchScenario(){ try{ const r=await authedFetch(`${API_BASE}/scenario`); const d=await r.json(); scenarioName=d.dir_name||d.name||''; scenarioDisplayName.value=d.name||scenarioName; backgroundText.value=d.background_text||''; auditConfig.value=d.audit_cfg||{}; settlementConfig.value=d.settlement_cfg||{}; stopTTSBySource('scenario_notice'); noticeSpeechChunks.value=[]; noticeActiveChunk.value=-1; noticeTTSStatus.value=''; presentation=d.presentation||null; renderMode.value=presentation?.render_mode||'scene_3d'; roleModels=d.role_models||{}; worldVariables.value=d.world_variables||[]; defaultGLBUrl=resolveAsset(presentation?.default_character_glb)||'/models/default_character.glb'; const sp=presentation?.spawns; if(sp?.length)SPAWN_POSITIONS=sp.map(p=>new THREE.Vector3(p[0],p[1]??0,p[2])); renderCfg=presentation?.render||null; worldLocations=d.world_locations||[]; sceneConfig=d.scene_config||null; sceneTheme=d.scene_theme||null; uiConfig=renderCfg?.ui||null; metricDefs.value=uiConfig?.metrics||{}; const declaredMetrics=d.metrics_cfg?.metrics||[]; metricDefinitions=declaredMetrics.length?Object.fromEntries(declaredMetrics.map(item=>[item.id,item])):Object.fromEntries(Object.entries(metricDefs.value).map(([id,item])=>[id,{id,min:item.min??0,max:item.max??100}])); goalText.value=d.goal_text||''; availableActions.value=d.actions_cfg||[]; agentSlots=d.agent_slots||[]; scenarioRoles.value=d.agent_slots||[]; agentFallbackCfg=presentation?.agent_fallback||{}; locMarkerCfg=presentation?.location_marker||{}; uiTheme=presentation?.ui_theme||{}; applyUiTheme(uiTheme); if(sceneConfig){ const t=sceneConfig.ui_text||{}; if(t.title)document.title=t.title } console.log('[scenario] agents:',agentSlots.length,'render.locations:',Object.keys(renderCfg?.locations||{}).length,'worldLocations:',worldLocations.length,'actions:',availableActions.value.length) } catch(e){ console.warn('scenario fetch fail',e) } }

const NEUTRAL_UI_THEME = {
  accent_primary:'#4cc9f0', accent_secondary:'#68f7a5', director_color:'#f3c969',
  error_color:'#ff647c', success_color:'#68f7a5',
  shell_background:'linear-gradient(160deg,#030711 0%,#07111d 48%,#061018 100%)',
  shell_glow:'radial-gradient(700px 420px at 22% 10%,rgba(76,201,240,.10),transparent 70%)',
  panel_background:'rgba(5,11,22,.94)', panel_border:'rgba(125,211,252,.12)',
}
function applyUiTheme(theme={}){ const root=document.documentElement; const merged={...NEUTRAL_UI_THEME,...theme}; const map={'accent_primary':'--ui-accent','accent_secondary':'--ui-accent2','director_color':'--ui-director','error_color':'--ui-error','success_color':'--ui-success','shell_background':'--scene-shell-bg','shell_glow':'--scene-shell-glow','panel_background':'--scene-panel-bg','panel_border':'--scene-panel-border'}; for(const[k,v]of Object.entries(merged)){ const cssVar=map[k]; if(cssVar)root.style.setProperty(cssVar,v) } }

function agentStatusText(agent){
  if(isEliminated(agent.agent_id)) return uiConfig?.status_labels?.eliminated || '已退出'
  return agent.is_alive ? (uiConfig?.status_labels?.active || '在线') : (uiConfig?.status_labels?.inactive || '已淘汰')
}

function milestoneEyebrow(item){
  const cfg = uiConfig?.milestone_banner || {}
  if(item?.eyebrow) return item.eyebrow
  if(item?.order) return String(cfg.order_template || '第 {order} 节点').replace('{order}', item.order)
  return cfg.eyebrow || '世界事件'
}
function milestoneSubline(item){
  const cfg = uiConfig?.milestone_banner || {}
  return item?.subline || cfg.subline || `${scenarioRoles.value.length} 位智能体正在应对`
}

async function saveAgentConfig(agent){ cfgMsg.value=''; try{ const body={ provider:agent.provider, model:agent.model }; if(agent.api_key)body.api_key=agent.api_key; const r=await authedFetch(`${API_BASE}/config/agents/${agent.id}`,{ method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }); if(!r.ok)throw new Error(await r.text()); cfgMsg.value=`✅ ${agent.name} → ${agent.provider} / ${agent.model}` } catch(e){ cfgMsg.value=`❌ ${e.message}` } }

async function sendOracle(){ const t=oracleText.value.trim(); if(!t)return; ws.commands.oracle(oracleTarget.value,t); oracleText.value='' }
async function triggerWorldVar(v){ if(v?.text)ws.commands.oracle('all',v.text,v.effects||[]) }

async function switchScenario(){
  if(!selectedScenario.value || scenarioSwitching.value) return
  scenarioSwitching.value = true
  cfgMsg.value='切换中…'
  narrativeFeed.value=[]
  clearNarrativeFeed()
  try{
    const r=await authedFetch(`${API_BASE}/control/load-scenario`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ scenario_name:selectedScenario.value })
    })
    if(!r.ok) throw new Error(await r.text())
    sessionStorage.setItem('aiworld:last-scenario-switch', selectedScenario.value)
    window.location.reload()
  } catch(e){
    scenarioSwitching.value = false
    cfgMsg.value=`切换失败：${e.message}`
  }
}

function clearEnv(){ const sc=scene.value; for(const o of envObjects)sc?.remove(o); envObjects=[] }
function rebuildEnv(){ const sc=scene.value; if(!sc)return; const env=presentation?.environment||{}; clearEnv(); sc.background=makeSky(env.sky_gradient); sc.fog=new THREE.FogExp2(new THREE.Color(env.fog_color||'#071522').getHex(),env.fog_density??0.008); buildLighting(sc,env); buildGround(sc,env); buildProps(sc,env); buildLocationSceneAssets(sc); buildLocationMarkers(sc); buildAtmosphere(sc,env) }

function buildLocationSceneAssets(sc) {
  const imageFormats = new Set(['svg', 'png', 'jpg', 'jpeg', 'webp'])
  for (const location of Object.values(renderCfg?.locations || {})) {
    if (!location.scene_asset || !imageFormats.has(String(location.format || '').toLowerCase())) continue
    const width = Number(location.size?.width || 10)
    const height = Number(location.size?.height || 4)
    const position = location.world_position || {}
    const material = new THREE.MeshBasicMaterial({
      map: new THREE.TextureLoader().load(resolveAsset(location.scene_asset)),
      transparent: true,
      side: THREE.DoubleSide,
      depthWrite: false,
    })
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material)
    plane.position.set(Number(position.x || 0), height / 2, Number(position.z || 0) + 3)
    plane.userData.cameraIgnore = true
    sc.add(plane)
    envObjects.push(plane)
  }
}

// A 地点差异化（极简版）：只用地面色环 + 一个低矮中心点缀
//   旧版加了 4 根柱子 + 围合墙 + 八角基座 + 龙椅/书架/兵器架，整个画面堆得太满太丑。
//   现在改为：地面一圈淡色环（颜色按 type 区分） + 中心一个低矮 0.3m 高的扁圆台。
//   要识别地点身份靠 CSS2D 文字标签，不靠 3D 物件。
function buildLocationLandmark(locId, type) {
  const grp = new THREE.Group()
  const palette = {
    neutral:    '#c9a85c',
    public:     '#7c8fc2',
    restricted: '#5a6c8f',
  }
  const color = palette[type] || palette.neutral
  // 极简中心标记：扁圆台
  const center = new THREE.Mesh(
    new THREE.CylinderGeometry(0.8, 1.0, 0.25, 24),
    new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.1, transparent: true, opacity: 0.55 }),
  )
  center.position.y = 0.13
  grp.add(center)

  // 标记可被相机射线忽略，避免遮挡镜头
  grp.traverse(c => { if (c.isMesh) c.userData.cameraIgnore = true })
  return grp
}

function buildLocationMarkers(sc) {
  if (!renderCfg?.locations || !worldLocations.length) return
  Object.keys(locMarkerMap).forEach(k => delete locMarkerMap[k])
  const mc = locMarkerCfg || {}
  const idleCol = new THREE.Color(mc.idle_color || '#c9a85c').getHex()
  const locMap = {}
  for (const wl of worldLocations) locMap[wl.id] = wl

  for (const [key, lr] of Object.entries(renderCfg.locations)) {
    const wp = lr.world_position || {}
    const x = wp.x || 0, z = wp.z || 0
    const locId = key.replace('_render', '')
    const wl = locMap[locId]
    const sz = lr.size || {}
    const radius = Math.max(2.5, (sz.width || 10) / 2 * 0.5)
    if (x === 0 && z === 0) {
      locMarkerMap[locId] = { group: null, labelEl: null, ring: null, position: new THREE.Vector3(x, 0, z) }
      continue
    }
    const grp = new THREE.Group()
    // 地面环（原有）
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(radius - 0.05, radius, 64),
      new THREE.MeshBasicMaterial({ color: idleCol, transparent: true, opacity: mc.idle_opacity ?? 0.08, side: THREE.DoubleSide }),
    )
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.02
    grp.add(ring)
    // 新增：地标几何（按地点性质和 id 生成）
    const landmark = buildLocationLandmark(locId, wl?.type || 'neutral')
    grp.add(landmark)
    // 标签
    const ld = document.createElement('div')
    ld.className = 'loc-label loc-label-subtle'
    ld.textContent = wl?.name || locId
    ld.style.opacity = '0'; ld.style.transition = 'opacity 0.4s ease'
    const lb = new CSS2DObject(ld)
    lb.position.y = 2.5
    grp.add(lb)
    grp.position.set(x, 0, z)
    sc.add(grp)
    envObjects.push(grp)
    locMarkerMap[locId] = { group: grp, labelEl: ld, ring, position: new THREE.Vector3(x, 0, z) }
  }
}

onMounted(async ()=>{
  // FBX 骨骼素材预加载（保留作动画库）
  loadFBXBundle().catch(err => console.warn('[FBX] 预加载失败，将使用 GLB 兜底:', err.message))
  await fetchScenario();
  restoreNarrativeFeedIfNeeded()
  // 按当前场景包声明预加载角色模型，不假定角色数量、ID 或资源目录。
  const glbUrls = [...new Set(
    Object.values(roleModels || {})
      .map(resolveAsset)
      .filter(url => url && /\.glb(?:$|\?)/i.test(url)),
  )]
  await Promise.all(
    glbUrls.map(url => new Promise((resolve) => loadGLB(url, resolve, true)))
  )
  initScene();
  // 不等 WS 快照，预建三个角色模型到出生位置
  for (const slot of agentSlots) {
    const fakeAgent = {
      agent_id: slot.id,
      name: slot.name || slot.id,
      color: slot.color || '#fff',
      is_alive: true,
    }
    buildAgentMesh(fakeAgent)
    // 初始位置：从角色各自的 start_location 取 spawn_point
    const locationBinding = renderCfg?.bindings?.locations?.[slot.start_location]
    const locCfg = renderCfg?.locations?.[locationBinding]
      || renderCfg?.locations?.[slot.start_location]
      || renderCfg?.locations?.[`${slot.start_location}_render`]
    if (locCfg) {
      const sp = locCfg.spawn_points?.[slot.id] || locCfg.spawn_points?.default
      if (sp) {
        const e = agentMeshes[slot.id]
        if (e?.group) {
          e.group.position.set(sp.x || 0, sp.y || 0, sp.z || 0)
          e.group.userData.targetPos = e.group.position.clone()
        }
      }
    }
  }
  presentationExecutor = createPresentationExecutor({
    getAgentEntry: id => id === '__all__' ? agentMeshes : agentMeshes[id],
    getScene: () => scene.value,
    getCamera: () => camera.value,
    getControls: () => controls.value,
    getRenderConfig: () => renderCfg,
    getFBXClips: () => fbxBundle?.clips || null,
    resolveLocationPosition,
    resolveObjectPosition,
    resolveAsset,
    playSound: (key, parameters) => audioEngine?.playSFX(key, parameters),
    playMusic: (state, parameters) => audioEngine?.setBGMState(state, parameters),
  })

  // P2-B：音频引擎 + 特效引擎
  // 资源根：场景包 assets/audio/，由 backend StaticFiles 在 /scenario-assets 挂载
  const audioBase = scenarioName
    ? `${API_BASE}/scenario-assets/${scenarioName}/assets/audio`
    : ''
  audioEngine = createAudioEngine({
    assetBaseUrl: audioBase,
    files: renderCfg?.audio?.files,
    eventSfxMap: renderCfg?.audio?.event_sfx,
    eventBgmMap: renderCfg?.audio?.event_bgm,
  })
  audioEngine.preloadAll()
  // 首次任意点击/键盘事件才能解锁 Web Audio
  const unlockAudio = () => { audioEngine?.unlock(); audioEngine?.setBGMState('idle') }
  window.addEventListener('pointerdown', unlockAudio, { once: true })
  window.addEventListener('keydown', unlockAudio, { once: true })

  effectEngine = createEffectEngine({
    getScene: () => scene.value,
    getCamera: () => camera.value,
    getAgentEntry: id => agentMeshes[id],
    eventEffectsMap: renderCfg?.audio?.event_effects || {},
  })

  animate();
  await Promise.all([fetchConfig(),fetchScenarios(),fetchReplays()]); 
  
  // ── 统一状态管理：避免 computing/waiting 闪烁 ──
  let hasActiveContent = false;  // 跟踪是否已有内容播放

  function syncComputedTick(msg = {}) {
    const playbackTick = Number(snapshot.value.tick || 0)
    const bufferedTicks = Number(msg.buffer_size || 0)
    const nextTick = Number(msg.next_tick || 0)
    const msgTick = Number(msg.tick || 0)
    const bufferedHighWater = playbackTick + Math.max(0, bufferedTicks)
    computedTick.value = Math.max(
      computedTick.value,
      playbackTick,
      msgTick,
      nextTick > 0 ? nextTick - 1 : 0,
      bufferedHighWater,
    )
  }

  ws.on('connected', () => {
    wsConnected.value = true
    if (waitingMessage.value.includes('正在连接引擎')) {
      waitingMessage.value = '引擎已连接，正在启动推演…'
    }
  })

  ws.on('disconnected', () => {
    wsConnected.value = false
    isComputing.value = false
    waitingMessage.value = '引擎连接已断开，正在重连…'
  })

  ws.on('connection_error', () => {
    wsConnected.value = false
    isComputing.value = false
    waitingMessage.value = '无法连接后端引擎，请确认 8001 端口服务已启动'
  })

  ws.on('command_queued', msg => {
    if (msg.cmd?.cmd === 'play') {
      waitingMessage.value = '正在连接引擎，开始命令已排队…'
    }
  })
  
  // OBS 模型：把 world_snapshot 应用逻辑独立出来，
  // presentation_segment 内嵌的同锚点快照也会调用这个函数，
  // 保证「画面更新」和「字幕/旁白」共用同一个时间锚点。
  function applyWorldSnapshot(msg) {
    if (!msg || !msg.tick) return
    syncComputedTick(msg)
    const pt = snapshot.value.tick;
    const previousScores = settlementScores(snapshot.value)
    const nextScores = settlementScores(msg)
    if (msg.tick > pt && pt > 0) {
      settlementTrends.value = Object.fromEntries(
        Object.entries(nextScores).map(([agentId, score]) => [
          agentId,
          roundDisplayNumber(score - (previousScores[agentId] ?? score)),
        ])
      )
    }
    // ━━ 心声 / 策略保留 ━━
    // character_monologue / public_reasoning_summary 段可能已注入；
    // world_snapshot 若带空字段，不能覆盖已有内容。
    const preservedMonos = {}
    const preservedStrategies = {}
    for (const a of snapshot.value.agents || []) {
      if (a.character_monologue) preservedMonos[a.agent_id] = a.character_monologue
      if (a.public_reasoning_summary) preservedStrategies[a.agent_id] = a.public_reasoning_summary
    }
    const mergedAgents = (msg.agents || []).map(a => {
      let next = a
      const incomingMono = (a.character_monologue || '').trim()
      if (!incomingMono) {
        const kept = preservedMonos[a.agent_id]
        if (kept) next = { ...next, character_monologue: kept }
      }
      const incomingStrategy = (a.public_reasoning_summary || '').trim()
      if (!incomingStrategy) {
        const kept = preservedStrategies[a.agent_id]
        if (kept) next = { ...next, public_reasoning_summary: kept }
      }
      return next
    })
    snapshot.value = { ...msg, agents: mergedAgents };
    updateAgentMeshes(mergedAgents, msg.agent_locations);
    if (msg.tick > pt) {
      processEvents(msg.recent_public_events||[]);
      if (!presentedTicks.has(msg.tick)) {
        showActionEffects(msg.recent_public_events||[], msg.agent_locations||{});
      }
      presentedTicks.delete(msg.tick)
      lastAddedTick = msg.tick;
      hasActiveContent = true;
      if (!waitingMessage.value) {
        isComputing.value = false;
      }
    }
  }

  ws.on('world_snapshot', msg => {
    // 兼容旧链路：独立 world_snapshot 仍然支持，但 OBS 模型下主路径
    // 是通过 presentation_segment.world_snapshot 内嵌同锚点应用。
    applyWorldSnapshot(msg);
  });

  ws.on('presentation_tick_start', msg => {
    syncComputedTick(msg)
    presentedTicks.add(msg.tick)
    hasActiveContent = true
    if (!simulationComplete.value) waitingMessage.value = ''
    isComputing.value = false
    // 不再在 tick 开头清空角色内心：RenderCommand / monologue 段到达前
    // 会留下「思考中…」空窗，且若注入失败会整拍空白。
    // 新独白到达时由 upsertAgentMonologue 覆盖即可。
  })

  ws.on('replay_started', msg => {
    isReplaying.value = true
    narrativeFeed.value = []
    feedIdCtr = 0
    lastAddedTick = -1
    clearNarrativeFeed()
    presentedTicks.clear()
    settlementTrends.value = {}
    computedTick.value = 0
    waitingMessage.value = ''
    isComputing.value = false
    if (msg.initial_snapshot) {
      snapshot.value = msg.initial_snapshot
      syncComputedTick(msg.initial_snapshot)
      updateAgentMeshes(
        msg.initial_snapshot.agents || [],
        msg.initial_snapshot.agent_locations || {},
      )
    }
    presentationExecutor?.resetCamera()
    pushFeed({
      tick: 0,
      type: 'director',
      speaker: '系统',
      color: uiTheme?.director_color || '#ffd060',
      content: `开始回放 ${msg.run_id || ''}`,
    })
  })

  ws.on('playout_complete', msg => {
    simulationComplete.value = false
    waitingMessage.value = ''
    if (isReplaying.value) {
      isReplaying.value = false
      pushFeed({
        tick: msg.tick || snapshot.value.tick,
        type: 'director',
        speaker: '系统',
        color: uiTheme?.director_color || '#ffd060',
        content: '回放结束，可再次点击 ⟳ 从头播放',
      })
    } else {
      fetchReplays()
    }
  })

  ws.on('simulation_complete', msg => {
    syncComputedTick(msg)
    simulationComplete.value = true
    isComputing.value = false
    bufferSize.value = msg.buffer_size ?? bufferSize.value
    bufferAheadMs.value = msg.buffer_ahead_ms ?? bufferAheadMs.value
    if ((msg.buffer_size ?? 0) > 0 || (msg.buffer_ahead_ms ?? 0) > 0) {
      waitingMessage.value = '计算已完成，正在播放剩余演绎…'
    } else {
      waitingMessage.value = ''
    }
  })

  ws.on('presentation_segment', msg => {
    hasActiveContent = true
    presentationExecutor?.executeSegment(msg.segment)
    // OBS 同锚点：segment 可能携带 world_snapshot
    if (msg.world_snapshot) {
      applyWorldSnapshot(msg.world_snapshot);
    }
    const payload = msg.segment?.payload || {}
    if (msg.segment?.kind === 'render_command') {
      const commandType = payload.command_type
      const text = payload.parameters?.text
      if ((commandType === 'subtitle' || commandType === 'ui') && text) {
        pushFeed({
          tick: msg.tick || 0,
          type: 'director',
          speaker: '导演',
          color: uiTheme?.director_color || '#ffd060',
          content: text,
          source_refs: [
            ...(payload.source_event_refs || []),
            ...(payload.source_settlement_refs || []),
          ],
        })
      }
    }
    // 保留：把 character_monologue / public_reasoning_summary 注入 snapshot。
    // character_monologue 段（角色先开口）走这条路；卡片不存在时兜底创建。
    if (payload.actor_id && payload.character_monologue) {
      upsertAgentMonologue(payload.actor_id, payload.character_monologue)
    }
    const activity = payload.activity || {}
    const activityAgentId = payload.actor_id || activity.agent_id
    const activityStrategy = String(
      activity.public_reasoning_summary
      || payload.public_reasoning_summary
      || ''
    ).trim()
    if (activityAgentId && activityStrategy) {
      upsertAgentStrategy(activityAgentId, activityStrategy)
    }
    // 关键修复：不再把 Agent 的 character_monologue / public_reasoning_summary
    // 当作"发言"推到剧情演绎面板——那里只属于导演旁白（type='director'）。
    // 后端 _action_speech_for_feed() 会把 monologue 当 speech 塞进 payload，
    // 这是源头病灶；这里前端层面直接屏蔽，剧情演绎保持纯净导演视角。
  })
  
  ws.on('narration', msg => { 
    playTTS(msg); 
  }); 

  ws.on('narration_chunk', msg => {
    // 仅在剧情流仍为空时用 chunk.text 兜底，避免与字幕命令重复。
    if (msg.text && narrativeFeed.value.length === 0) {
      pushFeed({
        tick: msg.tick || 0,
        type: 'director',
        speaker: '导演',
        color: uiTheme?.director_color || '#ffd060',
        content: msg.text,
      })
    }
    playTTS(msg)
  })
  
  ws.on('engine_error', msg => { 
    if (msg.action === 'reset') isResetting.value = false
    if (msg.action === 'replay') {
      isReplaying.value = false
    }
    if (['play', 'start_rejected', 'pause', 'reset', 'replay'].includes(msg.action)) {
      waitingMessage.value = ''
      isComputing.value = false
    }
    pushFeed({ 
      tick: msg.tick||0, 
      type: 'error', 
      speaker: '⚠ 系统', 
      color: uiTheme?.error_color||'#ff6b6b', 
      content: `${msg.action} 失败: ${msg.error}` 
    }); 
  }); 

  ws.on('command_completed', msg => {
    if (msg.action === 'reset') {
      isResetting.value = false
      snapshot.value = { ...snapshot.value, tick: 0, is_running: false, is_game_over: false }
      waitingMessage.value = ''
      isComputing.value = false
    }
    if (msg.action === 'play' || msg.action === 'pause') {
      // play 成功后等待 tick / buffer 事件更新状态；pause 立即清掉“启动中”提示
      if (msg.action === 'pause') {
        waitingMessage.value = ''
        isComputing.value = false
      }
    }
  })
  
  // 关键修复：tick_computing 仅在 buffer 为空且无内容时显示
  ws.on('tick_computing', msg => { 
    syncComputedTick(msg);
    bufferSize.value = msg.buffer_size ?? 0;
    // 只在首次启动或 buffer 完全空时才显示计算中
    if (!hasActiveContent && msg.buffer_size === 0) {
      isComputing.value = true;
    }
  }); 
  
  // buffer_health 不再直接控制 isComputing，只更新健康度
  ws.on('buffer_health', msg => { 
    syncComputedTick(msg);
    bufferHealth.value = msg.health || 'good'; 
    bufferSize.value = msg.buffer_size ?? 0; 
    bufferAheadMs.value = msg.buffer_ahead_ms ?? bufferAheadMs.value;
    speedFactor.value = msg.speed_factor ?? 1.0; 
    // 不在此处设置 isComputing = false，由 presentation_segment/world_snapshot 控制
  }); 

  ws.on('playout_status', msg => {
    syncComputedTick(msg)
    bufferAheadMs.value = msg.buffer_ahead_ms ?? 0
    if (msg.state === 'preparing') {
      isComputing.value = true
      // 优先按 tick 数显示（跟实际生产节拍一致，避免数字卡住）
      if (msg.startup_buffer_ticks && msg.startup_buffer_ticks > 0) {
        const current = msg.buffer_size || 0
        const target = msg.startup_buffer_ticks
        const pct = Math.min(100, Math.round((current / target) * 100))
        waitingMessage.value = `正在准备演出 · 已就绪 ${current}/${target} 回合 (${pct}%)`
      } else {
        // 兜底：按时长显示
        const aheadSec = Math.round((msg.buffer_ahead_ms || 0) / 1000)
        const targetSec = Math.round((msg.startup_buffer_ms || 30000) / 1000)
        const pct = Math.round((msg.startup_progress ?? 0) * 100)
        waitingMessage.value = `正在准备演出 · 已缓冲 ${aheadSec}/${targetSec} 秒 (${pct}%)`
      }
    } else if (msg.state === 'rebuffering') {
      waitingMessage.value = '演出缓冲补充中…'
    } else if (msg.state === 'playing') {
      if (!simulationComplete.value) waitingMessage.value = ''
      isComputing.value = false
    }
  })

  // OBS 模型：开播时刻锚点，前端记录用于按 play_at_ms 同步渲染
  ws.on('playout_started', msg => {
    isComputing.value = false
    waitingMessage.value = ''
    console.log(
      `[OBS] 开播 server_start=${msg.playout_started_at_ms} ` +
      `buffered_ahead=${msg.buffered_ahead_ms}ms`
    )
  })
  
  // buffer_waiting 仅在长时间无新数据时显示（由后端控制频率）
  ws.on('buffer_waiting', msg => { 
    // 只有当已经播放过内容且当前不在计算中时才显示等待
    if (hasActiveContent && !isComputing.value && !simulationComplete.value) {
      waitingMessage.value = msg.message || '推演中...'; 
      bufferHealth.value = msg.health || 'empty'; 
    }
  }); 
  
  ws.connect(); 
})
onUnmounted(()=>{ stopAgentStatusPoll(); cancelAnimationFrame(animId); clearTTSQueue(); window.removeEventListener('resize',onResize); presentationExecutor?.dispose(); effectEngine?.dispose(); audioEngine?.dispose(); renderer.value?.dispose(); ws.destroy() })
</script>

<style scoped>
.app-shell{display:flex;flex-direction:column;height:100vh;background:var(--scene-shell-bg,linear-gradient(160deg,#030711,#07111d));color:#e6eefb;font-family:'PingFang SC','Microsoft YaHei',system-ui,sans-serif;overflow:hidden;position:relative}
.app-shell::after{content:'';position:absolute;inset:-20%;pointer-events:none;z-index:0;background:var(--scene-shell-glow,none);animation:aurora-drift 26s ease-in-out infinite alternate}
@keyframes aurora-drift{0%{transform:translate3d(-2.5%,-1.5%,0) scale(1)}100%{transform:translate3d(2.5%,2%,0) scale(1.07)}}
.app-shell::before{content:'';position:absolute;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,212,255,.008) 2px,rgba(0,212,255,.008) 4px);pointer-events:none;z-index:9999;animation:scanline-drift 8s linear infinite}
@keyframes scanline-drift{from{transform:translateY(0)}to{transform:translateY(4px)}}

.main-row{flex:1;display:flex;overflow:hidden;min-height:0}
.canvas-col{flex:1;position:relative;overflow:hidden;min-width:0}
.scene-area{position:absolute;top:0;right:0;bottom:0;left:0}
/* ── 仪表盘演绎形态（render_mode: dashboard）── */
.scene-dashboard{position:absolute;inset:0;z-index:6;display:flex;flex-direction:column;gap:14px;
  padding:clamp(78px,10vh,104px) clamp(16px,2.4vw,36px) clamp(16px,2.4vw,28px);
  overflow:auto;box-sizing:border-box;
  background:var(--scene-shell-bg,radial-gradient(900px 520px at 38% -10%,rgba(76,201,240,.10),transparent 68%),linear-gradient(160deg,#02050b,#07111d 52%,#041019))}
.sd-head{text-align:center;margin-top:0;flex-shrink:0}
.sd-title{font-size:clamp(14px,1.45vw,18px);font-weight:700;letter-spacing:.05em;color:#cfe6f5;line-height:1.25}
.sd-sub{margin-top:4px;font-size:12px;color:#7fa0b6;letter-spacing:.03em}
.sd-zones{flex:1;display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:clamp(12px,1.8vw,22px);align-content:start;max-width:1100px;margin:0 auto;width:100%}
.sd-zone{position:relative;display:flex;flex-direction:column;gap:12px;padding:18px 18px 20px;border-radius:20px;
  background:linear-gradient(180deg,rgba(8,18,30,.92),rgba(3,10,18,.96));
  border:1px solid color-mix(in srgb,var(--z) 32%,transparent);
  box-shadow:0 14px 40px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.04);transition:transform .25s,box-shadow .25s}
.sd-zone.leading{box-shadow:0 16px 46px rgba(0,0,0,.5),0 0 26px color-mix(in srgb,var(--z) 24%,transparent);border-color:color-mix(in srgb,var(--z) 55%,transparent)}
.sd-zone.dead{opacity:.5;filter:grayscale(.6)}
.sd-zone::before{content:'';position:absolute;inset:0;border-radius:20px;pointer-events:none;
  background:radial-gradient(420px 200px at 20% 0%,color-mix(in srgb,var(--z) 12%,transparent),transparent 70%)}
.sd-zone-head{display:flex;align-items:center;gap:12px;position:relative}
.sd-avatar{width:58px;height:58px;border-radius:16px;display:flex;align-items:center;justify-content:center;
  font-size:22px;font-weight:800;color:#04121c;box-shadow:0 6px 18px rgba(0,0,0,.4);overflow:hidden;flex-shrink:0;
  background:rgba(255,255,255,.06);border:1px solid color-mix(in srgb,var(--z) 35%,transparent)}
.sd-avatar-img{width:100%;height:100%;object-fit:cover;display:block}
.sd-id{flex:1;min-width:0}
.sd-name{font-size:18px;font-weight:800;color:#f2fbff}
.sd-role{font-size:12px;color:#89a9bf;margin-top:2px}
.sd-rank{font-size:12px;font-weight:700;padding:5px 12px;border-radius:999px;color:#a9c6d8;
  background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08)}
.sd-rank.hot{color:#04121c;background:color-mix(in srgb,var(--z) 82%,white);border-color:transparent}
.sd-primary{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:12px 14px;border-radius:14px;
  background:linear-gradient(180deg,color-mix(in srgb,var(--z) 12%,transparent),transparent);border:1px solid color-mix(in srgb,var(--z) 20%,transparent)}
.sd-primary-label{font-size:12px;color:#8fb2c8;letter-spacing:.04em}
.sd-primary-val{font-size:clamp(22px,2.4vw,30px);font-weight:800;color:#eaf6ff;font-variant-numeric:tabular-nums}
.sd-metrics{display:flex;flex-wrap:wrap;gap:8px}
.sd-metric{display:flex;flex-direction:column;gap:2px;padding:7px 12px;border-radius:11px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06)}
.sd-metric-label{font-size:11px;color:#7fa0b6}
.sd-metric-val{font-size:15px;font-weight:700;color:#dcecf6;font-variant-numeric:tabular-nums}
.sd-metric.up .sd-metric-val{color:#57e39a}
.sd-metric.down .sd-metric-val{color:#ff6b83}
.sd-holdings{padding:10px 12px;border-radius:13px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06)}
.sd-holdings-label{font-size:11px;font-weight:700;letter-spacing:.08em;color:color-mix(in srgb,var(--z) 65%,#9ab);margin-bottom:8px}
.sd-holdings-list{display:flex;flex-direction:column;gap:6px}
.sd-holding-row{display:grid;grid-template-columns:minmax(0,1.2fr) auto auto;gap:8px;align-items:center;
  padding:6px 8px;border-radius:9px;background:rgba(0,0,0,.22)}
.sd-holding-name{min-width:0;display:flex;flex-direction:column;gap:1px}
.sd-holding-name b{font-size:13px;font-weight:700;color:#e7f4fc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sd-holding-name i{font-size:10.5px;font-style:normal;color:#7fa0b6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sd-holding-qty{font-size:12px;color:#9bb6c8;font-variant-numeric:tabular-nums;white-space:nowrap}
.sd-holding-cost{font-size:12px;font-weight:650;color:#d7ebf6;font-variant-numeric:tabular-nums;white-space:nowrap}
.sd-holdings-empty{font-size:12.5px;color:#6f8ba0}
.sd-strategy{margin-top:2px;padding:12px 14px;border-radius:13px;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.06)}
.sd-strategy.sd-invest{background:rgba(76,201,240,.06);border-color:rgba(76,201,240,.14)}
.sd-strategy-label{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:700;letter-spacing:.08em;color:color-mix(in srgb,var(--z) 70%,#bcd);margin-bottom:6px}
.sd-strategy-label em{font-style:normal;font-size:10px;font-weight:600;letter-spacing:.04em;padding:2px 7px;border-radius:999px;color:#7ec8e8;background:rgba(76,201,240,.12)}
.sd-strategy-text{margin:0;font-size:13.5px;line-height:1.6;color:#d3e4f0;white-space:pre-line}
.sd-strategy-empty{margin:0;font-size:13px;color:#6f8ba0;font-style:italic}

/* ── 场景加载覆盖层 ── */
.scene-loading-overlay{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;z-index:5;background:radial-gradient(circle at center,rgba(4,8,20,.4) 0%,rgba(2,4,12,.75) 100%);backdrop-filter:blur(4px);animation:fade-in .3s ease}
.loading-orb{position:relative;width:80px;height:80px}
.loading-ring{position:absolute;inset:0;border-radius:50%;border:2px solid transparent}
.loading-ring.r1{border-top-color:var(--ui-accent,#4cc9f0);animation:spin 1.2s linear infinite}
.loading-ring.r2{inset:8px;border-top-color:var(--ui-accent2,#68f7a5);animation:spin 1.8s linear infinite reverse}
.loading-ring.r3{inset:16px;border-top-color:var(--ui-director,#f3c969);animation:spin 2.4s linear infinite}
.loading-core{position:absolute;inset:28px;border-radius:50%;background:radial-gradient(circle,var(--ui-accent,#4cc9f0) 0%,transparent 70%);animation:pulse-core 2s ease infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse-core{0%,100%{transform:scale(.8);opacity:.6}50%{transform:scale(1.2);opacity:1}}
.loading-text{font-size:14px;font-weight:600;color:var(--ui-accent,#4cc9f0);letter-spacing:.05em;text-shadow:0 0 12px color-mix(in srgb,var(--ui-accent,#4cc9f0) 35%,transparent)}
.loading-hint{font-size:11px;color:rgba(255,255,255,.4);letter-spacing:.02em}

/* ── 场景右下角迷你加载器 ── */
.scene-mini-loader{position:absolute;right:22px;bottom:60px;display:flex;align-items:center;gap:8px;z-index:6;padding:6px 14px;background:linear-gradient(135deg,rgba(4,8,20,.85),rgba(2,4,14,.75));border:1px solid rgba(0,212,255,.2);border-radius:20px;backdrop-filter:blur(12px);font-size:11px;color:rgba(130,200,255,.85);animation:fade-in .3s ease}
.mini-loader-dots{display:flex;gap:3px}
.mini-loader-dots span{width:5px;height:5px;border-radius:50%;background:var(--ui-accent,#4cc9f0);animation:dot-bounce 1.4s ease infinite}
.mini-loader-dots span:nth-child(2){animation-delay:.2s}
.mini-loader-dots span:nth-child(3){animation-delay:.4s}
@keyframes dot-bounce{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}
@keyframes fade-in{from{opacity:0}to{opacity:1}}
.hud-tl{position:absolute;top:20px;left:24px;display:flex;align-items:center;gap:12px;z-index:10;pointer-events:none}
.brand-mark{position:relative;display:flex;align-items:center;gap:14px;padding:5px 8px 5px 3px;background:transparent;border:0;border-radius:0;box-shadow:none;overflow:visible}
.brand-glyph{width:50px;height:50px;flex-shrink:0;filter:drop-shadow(0 0 12px rgba(0,212,255,.32));position:relative;z-index:1}
.brand-glyph svg{display:block;width:100%;height:100%;overflow:visible}
.brand-orbit{transform-origin:32px 32px}
.orbit-a{animation:brand-orbit-spin 16s linear infinite}
.orbit-b{animation:brand-orbit-spin 11s linear infinite reverse}
.brand-core-dot{animation:brand-core-pulse 2.8s ease-in-out infinite;transform-origin:32px 32px}
.brand-text{position:relative;z-index:1;display:flex;flex-direction:column;gap:6px}
.brand-name{font-size:18px;font-weight:650;letter-spacing:4.8px;color:#dff9ff;line-height:1;white-space:nowrap;text-shadow:0 0 18px rgba(0,212,255,.18)}
.brand-name b{font-weight:850;background:linear-gradient(135deg,#d9fbff,#00d4ff 60%,#7c3aed);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.brand-sub{font-size:8px;font-weight:650;letter-spacing:2.8px;color:rgba(130,211,244,.46);line-height:1;text-transform:uppercase;white-space:nowrap}
@keyframes brand-orbit-spin{to{transform:rotate(360deg)}}
@keyframes brand-core-pulse{50%{transform:scale(1.65);opacity:.55;filter:drop-shadow(0 0 5px #00d4ff)}}
.tick-pill{font-size:12px;font-weight:600;color:rgba(255,255,255,.58);display:flex;align-items:center;gap:6px;background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.08);box-shadow:0 2px 10px rgba(0,0,0,.3);backdrop-filter:blur(10px);padding:6px 12px;border-radius:10px;pointer-events:none}
.tick-pill-engine{color:rgba(255,221,128,.76);border-color:rgba(255,208,96,.18);background:linear-gradient(180deg,rgba(255,208,96,.08),rgba(255,255,255,.02));padding-inline:10px}
.tick-dot{width:6px;height:6px;border-radius:50%;background:var(--ui-accent,#4cc9f0);box-shadow:0 0 8px color-mix(in srgb,var(--ui-accent,#4cc9f0) 60%,transparent);animation:pulse-alive 2s ease infinite}
.tick-label{font-size:10px;font-weight:400;color:rgba(255,255,255,.3);letter-spacing:1px;margin-right:-2px}
.win-pill{font-size:13px;font-weight:700;color:#1a1206;display:flex;align-items:center;gap:6px;background:linear-gradient(135deg,#ffe39a,#ffc24d);border:1px solid rgba(255,228,150,.6);padding:6px 16px;border-radius:10px;box-shadow:0 4px 18px rgba(255,180,60,.35);animation:pulse-gold 1.5s ease infinite}
.win-icon{width:14px;height:14px}
@keyframes pulse-gold{0%,100%{box-shadow:0 0 0 0 rgba(255,208,96,0)}50%{box-shadow:0 0 16px 4px rgba(255,208,96,.25)}}
.hud-tr{position:absolute;top:16px;right:18px;display:flex;align-items:center;gap:4px;z-index:10;padding:4px;background:linear-gradient(135deg,rgba(4,8,20,.8),rgba(2,4,14,.7));border:1px solid rgba(0,212,255,.15);border-radius:12px;backdrop-filter:blur(12px);box-shadow:0 4px 16px rgba(0,0,0,.35),0 0 12px rgba(0,212,255,.06)}
.hud-btn{width:36px;height:34px;display:flex;align-items:center;justify-content:center;border:none;border-radius:8px;background:transparent;color:rgba(255,255,255,.7);cursor:pointer;font-size:15px;transition:all .18s ease}
.hud-btn:hover{background:rgba(0,212,255,.12);color:#fff;transform:scale(1.08);box-shadow:0 0 12px rgba(0,212,255,.3)}
.hud-btn:active{transform:scale(0.95)}
.hud-sep{width:1px;height:20px;background:rgba(0,212,255,.15);margin:0 2px}
.btn-cfg:hover,.btn-cfg.active{background:rgba(124,58,237,.35);color:#c8a8ff;box-shadow:0 0 12px rgba(124,58,237,.4)}
.hud-switch{position:relative;overflow:hidden;width:auto;height:34px;padding:0 12px;margin-left:2px;display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;letter-spacing:.06em;white-space:nowrap;color:#a8ebff;background:linear-gradient(135deg,rgba(105,220,255,.10) 0%,rgba(139,91,255,.10) 100%);border:1px solid rgba(105,220,255,.22)}
.hud-switch:hover{background:linear-gradient(135deg,rgba(105,220,255,.20) 0%,rgba(139,91,255,.20) 100%);color:#eafaff;border-color:rgba(105,220,255,.5);box-shadow:0 4px 16px rgba(105,220,255,.25);transform:translateY(-1px)}
.hud-switch:hover .hud-switch-arrow{transform:translateX(3px)}
.hud-switch-arrow{transition:transform .2s}
.hud-switch-shine{position:absolute;top:0;left:-60%;width:40%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.28),transparent);transform:skewX(-20deg);transition:left .5s ease;pointer-events:none}
.hud-switch:hover .hud-switch-shine{left:120%}
.scene-notice-book{position:absolute;top:82px;right:20px;z-index:11;display:flex;align-items:center;gap:8px;padding:8px 12px 8px 9px;border:1px solid rgba(255,208,96,.24);border-radius:12px;background:linear-gradient(135deg,rgba(15,12,20,.82),rgba(5,8,18,.72));color:rgba(255,224,154,.86);box-shadow:0 8px 24px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,255,255,.06);backdrop-filter:blur(12px);cursor:pointer;transition:all .2s ease}
.scene-notice-book svg{width:23px;height:23px;fill:rgba(255,208,96,.08);stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.scene-notice-book span{font-size:11px;font-weight:700;letter-spacing:.08em}
.scene-notice-book:hover{color:#ffe7aa;border-color:rgba(255,208,96,.5);background:linear-gradient(135deg,rgba(55,38,18,.82),rgba(8,10,20,.8));transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,0,0,.4),0 0 18px rgba(255,208,96,.12)}

/* ── 场景公告 ── */
.notice-overlay{position:fixed;inset:0;z-index:10020;display:flex;align-items:center;justify-content:center;padding:40px;background:rgba(1,3,10,.72);backdrop-filter:blur(9px);animation:fade-in .2s ease}
.notice-panel{width:min(760px,82vw);max-height:82vh;overflow:hidden;border-radius:18px;background:linear-gradient(155deg,rgba(10,16,34,.98),rgba(3,6,16,.99));border:1px solid rgba(0,212,255,.22);box-shadow:0 30px 100px rgba(0,0,0,.72),0 0 40px rgba(0,212,255,.08)}
.notice-head{display:flex;align-items:flex-start;justify-content:space-between;padding:24px 28px 18px;border-bottom:1px solid rgba(255,255,255,.07);background:linear-gradient(90deg,rgba(0,212,255,.07),transparent)}
.notice-kicker{font-size:9px;letter-spacing:3px;color:rgba(0,212,255,.58)}
.notice-head h2{margin:7px 0 0;font-size:23px;color:#f4f8ff;letter-spacing:.04em}
.notice-close{width:34px;height:34px;border-radius:9px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.04);color:rgba(255,255,255,.62);font-size:22px;cursor:pointer}
.notice-close:hover{background:rgba(255,255,255,.1);color:#fff}
.notice-voice-status{display:flex;align-items:center;gap:8px;padding:9px 28px;color:rgba(255,224,154,.72);font-size:11px;background:rgba(255,208,96,.035);border-bottom:1px solid rgba(255,255,255,.045)}
.notice-voice-dot{width:6px;height:6px;border-radius:50%;background:#ffd060;box-shadow:0 0 9px rgba(255,208,96,.65);animation:pulse-alive 1.4s ease infinite}
.notice-body{max-height:calc(82vh - 92px);overflow-y:auto;padding:8px 28px 28px}
.notice-section{padding:18px 0;border-bottom:1px solid rgba(255,255,255,.055)}
.notice-section:last-child{border-bottom:none}
.notice-section h3{margin:0 0 10px;color:#7dd3fc;font-size:12px;letter-spacing:.12em}
.notice-section p,.notice-section li{color:rgba(235,242,255,.7);font-size:14px;line-height:1.85}
.notice-section p{margin:0;white-space:pre-line}
.notice-section ul{margin:0;padding-left:20px}
.notice-spoken-copy{color:rgba(235,242,255,.7);font-size:14px;line-height:1.85;white-space:pre-line}
.notice-spoken-chunk{display:inline;border-radius:5px;padding:2px 1px;transition:color .3s ease,background .3s ease,box-shadow .3s ease}
.notice-spoken-chunk::after{content:' '}
.notice-spoken-chunk.played{color:rgba(235,242,255,.62)}
.notice-spoken-chunk.active{color:#fff2bd;background:rgba(255,208,96,.14);box-shadow:0 0 0 3px rgba(255,208,96,.06),0 0 16px rgba(255,208,96,.08)}
.notice-roles{display:flex;flex-wrap:wrap;gap:9px}
.notice-roles span{display:flex;align-items:center;gap:7px;padding:7px 11px;border-radius:8px;background:rgba(255,255,255,.04);color:rgba(255,255,255,.72);font-size:12px}
.notice-roles i{width:7px;height:7px;border-radius:50%;background:var(--role-color);box-shadow:0 0 8px var(--role-color)}

/* ── 场景内综合态势 ── */
.scene-standings{
  position:absolute;left:22px;bottom:20px;z-index:10;
  display:flex;gap:8px;pointer-events:auto
}
.standing-card{
  --ag-color:#7dd3fc;
  width:150px;min-height:66px;display:flex;align-items:center;gap:9px;
  padding:8px 11px 8px 8px;border-radius:13px;
  background:linear-gradient(145deg,rgba(6,10,24,.9),rgba(2,5,14,.78));
  border:1px solid color-mix(in srgb,var(--ag-color) 25%,transparent);
  box-shadow:0 8px 24px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.04);
  backdrop-filter:blur(14px) saturate(1.25);transition:transform .2s ease,border-color .2s ease
}
.standing-card:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--ag-color) 55%,transparent)}
.standing-card.leader{box-shadow:0 8px 28px rgba(0,0,0,.42),0 0 18px color-mix(in srgb,var(--ag-color) 18%,transparent)}
.standing-card.dead{opacity:.42;filter:grayscale(.5)}
.standing-card.eliminated{opacity:.45;filter:grayscale(1)}
.standing-card.eliminated .standing-state{color:#c0563f;font-weight:600}
.standing-rank{
  width:25px;height:25px;flex-shrink:0;display:flex;align-items:center;justify-content:center;
  border-radius:8px;background:color-mix(in srgb,var(--ag-color) 17%,rgba(0,0,0,.35));
  color:var(--ag-color);font-size:12px;font-weight:900;
  border:1px solid color-mix(in srgb,var(--ag-color) 30%,transparent)
}
.standing-card.leader .standing-rank::before{content:'◆';font-size:8px;margin-right:3px}
.standing-main{flex:1;min-width:0}
.standing-head{display:flex;align-items:center;gap:5px}
.standing-name{font-size:11px;font-weight:700;color:var(--ag-color);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.standing-state{font-size:8px;color:rgba(255,255,255,.32);white-space:nowrap}
.standing-score-row{display:flex;align-items:baseline;gap:5px;margin-top:2px}
.standing-score-row strong{font-size:19px;line-height:1;color:#fff;font-family:ui-monospace,monospace;letter-spacing:-1px}
.standing-score-row span{font-size:8px;color:rgba(255,255,255,.28)}
.standing-score-row em{margin-left:auto;font-size:8px;font-style:normal;color:rgba(255,255,255,.22)}
.standing-score-row em.up{color:#55e69a}.standing-score-row em.down{color:#ff7a83}
.standing-track{height:4px;margin-top:5px;border-radius:3px;background:rgba(255,255,255,.06);overflow:hidden;display:flex;gap:1px}
.src-bar{display:block;height:100%;transition:width .7s cubic-bezier(.2,.8,.2,1)}
.standing-source-legend{display:flex;align-items:center;gap:9px;margin-top:4px;height:10px}
.standing-source-legend span{display:inline-flex;align-items:center;gap:3px;font-size:8px;line-height:1;color:rgba(255,255,255,.46);white-space:nowrap}
.standing-source-legend span.muted{opacity:.25}
.src-dot{width:5px;height:5px;border-radius:50%;display:inline-block;box-shadow:0 0 6px currentColor}
.danger-row{display:flex;align-items:center;gap:6px;margin-top:5px}
.danger-tag{font-size:8px;font-weight:800;color:#ff5f52;letter-spacing:.5px;white-space:nowrap}
.danger-track{position:relative;flex:1;height:5px;border-radius:3px;background:rgba(255,95,82,.12);overflow:hidden}
.danger-track i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:linear-gradient(90deg,#a83a30,#ff5f52);box-shadow:0 0 8px rgba(255,95,82,.5);transition:width .5s ease}
.danger-threshold{position:absolute;left:85%;top:-1px;bottom:-1px;width:1px;background:rgba(255,255,255,.55)}
.danger-num{font-size:10px;font-weight:800;color:#ff5f52;min-width:16px;text-align:right}
.danger-row.hot .danger-tag,.danger-row.hot .danger-num{animation:dangerPulse 1s ease-in-out infinite}
.danger-row.hot .danger-track i{animation:dangerGlow 1s ease-in-out infinite}
@keyframes dangerPulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes dangerGlow{0%,100%{box-shadow:0 0 8px rgba(255,95,82,.5)}50%{box-shadow:0 0 16px rgba(255,95,82,.95)}}
.victory-recap{position:absolute;left:50%;top:72px;transform:translateX(-50%);z-index:14;width:min(560px,86%);background:linear-gradient(180deg,rgba(8,12,26,.96),rgba(4,6,16,.97));border:1px solid rgba(255,208,96,.35);border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.55),0 0 24px rgba(255,208,96,.12);backdrop-filter:blur(10px);overflow:hidden}
.vr-head{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;font-size:13px;font-weight:800;color:#ffd060;cursor:pointer;user-select:none}
.vr-head em{font-size:10px;color:rgba(255,255,255,.4);font-style:normal}
.vr-body{max-height:52vh;overflow-y:auto;padding:0 14px 12px;display:flex;flex-direction:column;gap:10px}
.vr-card{border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 12px;background:rgba(255,255,255,.03)}
.vr-card.champ{border-color:rgba(255,208,96,.45);background:rgba(255,208,96,.06)}
.vr-headline{font-size:13px;font-weight:800;color:#fff;margin-bottom:6px}
.vr-line{font-size:11px;line-height:1.7;color:rgba(255,255,255,.75)}
.vr-line.plus{color:#8be28b}
.vr-line.weak{color:#e0b36a}
.vr-line.fatal{color:#ff5f52;font-weight:700}
.vr-mix{margin-top:6px;font-size:10px;color:rgba(255,255,255,.42)}
.hud-ledger{position:absolute;right:22px;bottom:24px;display:flex;align-items:center;gap:6px;z-index:10;pointer-events:none;background:linear-gradient(180deg,rgba(4,8,20,.78),rgba(2,4,14,.68));border:1px solid rgba(0,212,255,.12);border-radius:20px;padding:5px 12px;backdrop-filter:blur(8px);box-shadow:0 4px 14px rgba(0,0,0,.35),0 0 8px rgba(0,212,255,.05)}
.hl-title{font-size:11px;font-weight:800;color:#00d4ff;margin-right:2px}
.hl-badge{font-size:10px;color:rgba(255,255,255,.55);display:inline-flex;align-items:center;gap:3px}
.hl-badge b{color:#7dd3fc;font-size:11px}

.right-sidebar{width:360px;flex-shrink:0;display:flex;flex-direction:column;background:var(--scene-panel-bg,rgba(5,11,22,.94));border-left:1px solid var(--scene-panel-border,rgba(125,211,252,.12));overflow:hidden;box-sizing:border-box}
.zone{display:flex;flex-direction:column;min-height:0}
.zone-hd{display:flex;align-items:center;gap:8px;padding:11px 18px 9px 16px;flex-shrink:0;border-bottom:1px solid rgba(255,255,255,.05)}
.zone-title{font-size:12px;font-weight:600;color:rgba(255,255,255,.45);letter-spacing:.06em;text-transform:uppercase;flex:1}
.zone-source{padding:2px 7px;border-radius:8px;background:rgba(0,212,255,.07);color:rgba(125,211,252,.42);font-size:8px;letter-spacing:.08em}
.zone-count{font-size:10px;color:rgba(255,255,255,.2);background:rgba(255,255,255,.04);padding:1px 7px;border-radius:8px;font-weight:500}

/* ── Narration Timeline ── */
.zone-narration{flex:2;min-height:0;border-bottom:1px solid rgba(255,255,255,.06)}
.feed-scroll{flex:1;overflow-y:auto;padding:0 0 6px;scroll-behavior:smooth}
.feed-scroll::-webkit-scrollbar{width:2px}
.feed-scroll::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:2px}

.timeline{padding:4px 18px 8px 12px;display:flex;flex-direction:column;box-sizing:border-box}
.tl-entry{display:flex;gap:8px;padding:6px 0 10px;position:relative;border-bottom:1px solid rgba(255,255,255,.03);animation:timeline-scroll-in .32s ease-out}
@keyframes timeline-scroll-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.tl-entry:last-child{border-bottom:none}
.tl-tick{font-size:9px;font-weight:700;color:rgba(255,255,255,.18);width:22px;flex-shrink:0;padding-top:1px;font-family:monospace;letter-spacing:-.02em}
.tl-dot{width:5px;height:5px;border-radius:50%;margin-top:5px;flex-shrink:0;opacity:.65}
.tl-text{font-size:12.5px;line-height:1.55;color:rgba(255,255,255,.55);margin:0;flex:1}
.tl-text b{display:block;margin-bottom:2px;font-size:10px;font-weight:700;letter-spacing:.04em}
.etype-director .tl-dot{background:rgba(255,210,80,.7)}
.etype-director .tl-text{color:rgba(255,220,110,.75)}
.etype-speak .tl-text{color:rgba(160,200,255,.72)}
.etype-attack .tl-text{color:rgba(255,140,120,.78)}
.etype-betray .tl-text{color:rgba(255,90,90,.82)}
.etype-ally .tl-text{color:rgba(110,210,150,.72)}
.etype-error .tl-text{color:rgba(255,100,100,.85)}
.tl-block-entry{align-items:flex-start}
.director-block-card{
  flex:1;min-width:0;
  border:1px solid rgba(255,210,80,.16);
  background:linear-gradient(180deg,rgba(255,210,80,.075),rgba(255,255,255,.025));
  border-radius:8px;
  padding:9px 10px 10px;
  box-shadow:0 10px 24px rgba(0,0,0,.18)
}
.ilevel-critical .director-block-card{border-color:rgba(255,93,93,.32);background:linear-gradient(180deg,rgba(255,93,93,.12),rgba(255,210,80,.03))}
.ilevel-high .director-block-card{border-color:rgba(255,210,80,.26)}
.dbc-head{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.dbc-kicker{flex:1;min-width:0;font-size:9px;color:rgba(255,255,255,.34);font-weight:700;letter-spacing:.08em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dbc-level{font-size:9px;font-weight:800;color:#111;background:rgba(255,210,80,.78);border-radius:5px;padding:1px 5px;flex-shrink:0}
.ilevel-critical .dbc-level{background:rgba(255,93,93,.86);color:#fff}
.director-block-card h4{font-size:13px;line-height:1.35;color:rgba(255,236,174,.92);margin:0 0 4px;font-weight:800}
.dbc-subtitle{font-size:11.5px;line-height:1.45;color:rgba(255,255,255,.48);margin:0 0 7px}
.dbc-body{font-size:12.2px;line-height:1.58;color:rgba(255,255,255,.68);margin:0 0 8px}
.dbc-chip-row{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.dbc-chip{font-size:10px;line-height:1.2;border-radius:5px;padding:3px 6px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.045);color:rgba(255,255,255,.62)}
.dbc-chip.object{color:rgba(125,211,252,.86);background:rgba(56,189,248,.09);border-color:rgba(56,189,248,.16)}
.dbc-chip.metric{color:rgba(134,239,172,.84);background:rgba(74,222,128,.08);border-color:rgba(74,222,128,.15)}
.dbc-chip.ability{color:rgba(253,224,71,.9);background:rgba(250,204,21,.08);border-color:rgba(250,204,21,.16)}
.dbc-hook{margin-top:8px;padding-top:7px;border-top:1px solid rgba(255,255,255,.06);font-size:11px;line-height:1.45;color:rgba(255,255,255,.38);font-style:italic}
.feed-empty{padding:28px 16px;font-size:12.5px;color:rgba(255,255,255,.13);text-align:center;line-height:1.8}
.feed-waiting{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;font-size:12px;color:rgba(0,212,255,.55)}
.fw-pulse{width:6px;height:6px;border-radius:50%;background:#00d4ff;animation:pulse-alive 1.5s ease infinite;flex-shrink:0}

/* ── Thoughts Cards ── */
.zone-thoughts{flex:3;min-height:0}
.thoughts-list{flex:1;overflow-y:auto;padding:10px 16px 10px 12px;box-sizing:border-box}
.thoughts-list::-webkit-scrollbar{width:2px}
.thoughts-list::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:2px}

.thought-card{
  margin-bottom:10px;padding:0;border-radius:12px;
  background:linear-gradient(180deg,rgba(255,255,255,.038),rgba(255,255,255,.012));
  border:1px solid rgba(255,255,255,.06);
  border-left:3px solid var(--ag-color,#666);
  overflow:hidden;transition:all .18s ease
}
.thought-card:hover{
  background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.02));
}
.thought-card.tc-dead{opacity:.35;border-left-color:rgba(255,255,255,.12)}

.tc-head{display:flex;align-items:center;gap:10px;padding:10px 12px 6px}
.tc-avatar{
  width:34px;height:34px;border-radius:9px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:14px;font-weight:800;
  background:var(--ag-color,#888);color:#000;
  opacity:.95;overflow:hidden
}
.tc-avatar-img{width:100%;height:100%;object-fit:cover;display:block}
.tc-info{flex:1;min-width:0}
.tc-name{display:block;font-size:13px;font-weight:600;color:var(--ag-color,#ccc);letter-spacing:.01em}
.tc-status{font-size:9.5px;font-weight:600;letter-spacing:.04em;margin-top:1px;display:inline-block;padding:1px 6px;border-radius:4px}
.tc-status.alive{color:rgba(125,255,154,.7);background:rgba(125,255,154,.08)}
.tc-status.dead{color:rgba(255,130,130,.6);background:rgba(255,100,100,.07)}

.tc-body{padding:4px 12px 11px;display:flex;flex-direction:column;gap:8px}
.tc-block label{display:flex;align-items:center;gap:6px;font-size:10px;font-weight:700;letter-spacing:.06em;color:rgba(180,210,235,.55);margin-bottom:4px}
.tc-block label em{font-style:normal;font-size:9.5px;font-weight:600;padding:1px 6px;border-radius:999px;color:#7ec8e8;background:rgba(76,201,240,.12)}
.tc-block.tc-strategy{padding-top:8px;border-top:1px solid rgba(255,255,255,.06)}
.tc-thought{
  font-size:12.5px;line-height:1.62;color:rgba(255,255,255,.58);
  margin:0
}
.tc-strategy-text{
  font-size:12.5px;line-height:1.62;color:rgba(190,220,245,.72);
  margin:0;white-space:pre-line
}
.tc-speech{font-size:12.5px;line-height:1.62;color:rgba(180,210,255,.65);margin:0}
.tc-silence{font-size:12px;color:rgba(255,255,255,.18);margin:0}
.thoughts-empty{padding:24px;font-size:12.5px;color:rgba(255,255,255,.13);text-align:center;line-height:1.8}

.zone-config{flex-shrink:0;max-height:480px}
.cfg-scroll{flex:1;overflow-y:auto;padding-bottom:12px}
.cfg-scroll::-webkit-scrollbar{width:3px}
.cfg-scroll::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1)}
.acfg-card{margin:10px 12px 0;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:12px 14px}
.acfg-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.acfg-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.acfg-name{font-size:13px;font-weight:700;flex:1}
.acfg-id{font-size:10px;color:rgba(255,255,255,.25)}
.cfg-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.cfg-row label{font-size:11px;color:rgba(255,255,255,.38);width:52px;flex-shrink:0}
.cfg-row select,.cfg-row input{flex:1;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#e8e0f8;font-size:12px;padding:5px 9px;outline:none}
.cfg-row select:focus,.cfg-row input:focus{border-color:#00d4ff;background:rgba(0,212,255,.06)}
.driver-row{align-items:flex-start}
.driver-toggle{display:flex;gap:6px;flex:1}
.driver-btn{flex:1;padding:6px 8px;border-radius:6px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.04);color:rgba(255,255,255,.55);font-size:11px;cursor:pointer;transition:all .15s}
.driver-btn.active{background:rgba(0,212,255,.15);border-color:rgba(0,212,255,.45);color:#b8f0ff;font-weight:700}
.driver-btn:disabled{opacity:.45;cursor:not-allowed}
.btn-inline{width:100%;margin:4px 0 0}
.agent-ext-block{margin-top:4px}
.ext-status-row{margin-bottom:8px}
.ext-badge{display:inline-block;padding:3px 8px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.04em}
.ext-badge.on{background:rgba(52,211,153,.15);color:#6ee7b7;border:1px solid rgba(52,211,153,.35)}
.ext-badge.off{background:rgba(255,255,255,.06);color:rgba(255,255,255,.45);border:1px solid rgba(255,255,255,.12)}
.ext-link{font-size:10px;line-height:1.45;color:rgba(180,210,255,.75);word-break:break-all;background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.08);border-radius:6px;padding:6px 8px;margin-bottom:8px;max-height:52px;overflow:hidden}
.ext-actions{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.ext-btn{padding:5px 8px;border-radius:6px;border:1px solid rgba(139,63,251,.35);background:rgba(139,63,251,.12);color:#d8b4fe;font-size:10px;cursor:pointer}
.ext-btn:hover{background:rgba(139,63,251,.28)}
.ext-btn:disabled{opacity:.4;cursor:not-allowed}
.ext-btn.danger{border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.1);color:#fca5a5}
.ext-hint{font-size:10px;color:rgba(255,255,255,.35);line-height:1.5;margin:0}
.ext-hint a{color:#7dd3fc;text-decoration:none}
.ext-hint a:hover{text-decoration:underline}
.cfg-divider{margin:14px 12px 8px;font-size:11px;font-weight:700;color:rgba(255,255,255,.3);letter-spacing:.07em}
.select-full{display:block;width:calc(100% - 24px);margin:0 12px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#e8e0f8;font-size:12px;padding:6px 9px;outline:none}
.btn-apply{display:block;width:calc(100% - 28px);margin:8px 14px 0;padding:7px;background:rgba(139,63,251,.2);border:1px solid rgba(139,63,251,.45);border-radius:7px;color:#c8a8ff;cursor:pointer;font-size:12px;transition:all .15s}
.btn-apply:hover{background:rgba(139,63,251,.4)}
.mt8{margin-top:8px}
.cfg-msg{margin:8px 14px 0;font-size:12px;color:#7dd3fc;line-height:1.4;font-weight:500}

.bottom-bar{flex-shrink:0;display:flex;align-items:center;gap:0;height:58px;background:linear-gradient(180deg,rgba(4,8,20,.96),rgba(2,4,12,.98));border-top:1px solid rgba(0,212,255,.12);box-shadow:0 -4px 20px rgba(0,0,0,.4),0 -1px 8px rgba(0,212,255,.06);backdrop-filter:blur(12px);padding:0 16px;position:relative}
.bottom-bar::before{content:'';position:absolute;top:0;left:10%;right:10%;height:1px;background:linear-gradient(90deg,transparent,rgba(0,212,255,.3),rgba(124,58,237,.2),transparent)}
.oracle-zone{display:flex;align-items:center;gap:8px;flex:1;min-width:0;padding-right:16px}
.oracle-label{font-size:11px;font-weight:700;color:rgba(0,212,255,.85);letter-spacing:1.5px;white-space:nowrap;padding:4px 8px;background:rgba(0,212,255,.06);border:1px solid rgba(0,212,255,.15);border-radius:6px}
.oracle-select{width:76px;flex-shrink:0;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:6px;color:rgba(255,255,255,.7);font-size:12px;padding:5px 6px;outline:none}
.oracle-input{flex:1;min-width:0;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#e8e0f8;font-size:13px;padding:7px 12px;outline:none;transition:all .15s}
.oracle-input::placeholder{color:rgba(255,255,255,.18)}
.oracle-input:focus{border-color:rgba(0,212,255,.45);background:rgba(0,212,255,.04);box-shadow:0 0 12px rgba(0,212,255,.15)}
.oracle-send{padding:7px 18px;flex-shrink:0;background:linear-gradient(135deg,rgba(0,212,255,.85),rgba(124,58,237,.8));border:none;border-radius:8px;color:#fff;cursor:pointer;font-size:12px;font-weight:700;letter-spacing:.5px;box-shadow:0 2px 10px rgba(0,212,255,.25);transition:all .18s ease;white-space:nowrap}
.oracle-send:hover{transform:translateY(-1px);box-shadow:0 4px 14px rgba(0,212,255,.4)}
.vars-zone{display:flex;align-items:center;gap:6px;padding-left:16px;flex-shrink:0}
.vars-label{font-size:10px;font-weight:600;color:rgba(255,255,255,.2);letter-spacing:.08em;white-space:nowrap;margin-right:2px}
.var-btn{padding:5px 12px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:8px;color:rgba(255,255,255,.65);cursor:pointer;font-size:11px;box-shadow:none;transition:all .18s ease;white-space:nowrap}
.var-btn:hover{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.2);color:#fff;transform:translateY(-1px)}

/* Buffer 状态指示 */
.computing-pill{font-size:11px;font-weight:600;color:rgba(130,200,255,.85);display:flex;align-items:center;gap:6px;background:linear-gradient(180deg,rgba(60,120,255,.12),rgba(60,120,255,.05));border:1px solid rgba(100,160,255,.2);padding:5px 11px;border-radius:9px;pointer-events:none}
.computing-dot{width:6px;height:6px;border-radius:50%;background:#6aafff;box-shadow:0 0 8px rgba(106,175,255,.6);animation:pulse-compute 1.2s ease infinite}
.computing-text{font-size:10px;letter-spacing:1px}
@keyframes pulse-compute{0%,100%{opacity:.5;transform:scale(.8)}50%{opacity:1;transform:scale(1.2)}}

.buffer-pill{font-size:10px;display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);padding:5px 10px;border-radius:9px;pointer-events:none}
.buffer-bar{width:32px;height:4px;border-radius:2px;background:rgba(255,255,255,.1);overflow:hidden}
.buffer-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,#7dff9a,#4ddb7a);transition:width .4s ease}
.bh-warning .buffer-fill{background:linear-gradient(90deg,#ffd060,#ffaa30)}
.bh-critical .buffer-fill{background:linear-gradient(90deg,#ff6b6b,#ff4040)}
.bh-empty .buffer-fill{background:rgba(255,255,255,.15)}
.bh-overflow .buffer-fill{background:linear-gradient(90deg,#a78bfa,#7c3aed)}
.buffer-label{color:rgba(255,255,255,.4);font-weight:500}

/* 等待消息 */
.feed-waiting{display:flex;align-items:center;gap:10px;padding:12px 16px;margin:8px 0;background:linear-gradient(135deg,rgba(100,160,255,.06),rgba(100,160,255,.02));border:1px solid rgba(100,160,255,.12);border-radius:10px;animation:fade-in-wait .5s ease}
.world-object-card{display:flex;flex-direction:column;gap:3px;min-width:116px;max-width:220px;padding:8px 10px;border:1px solid rgba(125,211,252,.42);border-radius:6px;background:rgba(7,13,25,.9);box-shadow:0 8px 24px rgba(0,0,0,.3);color:#eaf6ff;font-size:12px;line-height:1.35;pointer-events:none}.world-object-card strong{font-size:13px;color:#fff}.world-object-card span{color:rgba(210,228,241,.72)}
.fw-pulse{width:8px;height:8px;border-radius:50%;background:#6aafff;box-shadow:0 0 12px rgba(106,175,255,.5);animation:pulse-compute 1.5s ease infinite;flex-shrink:0}
.fw-text{font-size:12px;color:rgba(180,210,255,.8);font-weight:500}
@keyframes fade-in-wait{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}

/* 通用挑战里程碑卡片 */
.challenge-banner{
  position:absolute; left:50%; top:30%; transform:translate(-50%,-50%);
  z-index:20; pointer-events:none;
  min-width:380px; max-width:520px;
  padding:28px 48px;
  background:linear-gradient(135deg,rgba(35,20,60,.92),rgba(15,10,30,.95));
  border:1px solid rgba(255,210,96,.55);
  border-radius:14px;
  box-shadow:0 20px 60px rgba(0,0,0,.7),0 0 80px rgba(255,210,96,.25),inset 0 1px 0 rgba(255,255,255,.08);
  text-align:center;
  backdrop-filter:blur(6px);
  font-family:'PingFang SC','Microsoft YaHei',sans-serif;
}
.challenge-banner .challenge-order{
  font-size:13px; letter-spacing:6px; color:rgba(255,210,96,.85);
  font-weight:500; text-transform:uppercase; margin-bottom:10px;
}
.challenge-banner .challenge-title{
  font-size:26px; color:#fff; font-weight:700; letter-spacing:2px; line-height:1.3;
  text-shadow:0 2px 12px rgba(255,210,96,.4);
}
.challenge-banner .challenge-subline{
  font-size:11px; color:rgba(200,180,255,.6); letter-spacing:3px; margin-top:14px;
}
.challenge-fade-enter-active,.challenge-fade-leave-active{transition:opacity .5s ease,transform .5s ease}
.challenge-fade-enter-from{opacity:0;transform:translate(-50%,-60%) scale(.92)}
.challenge-fade-leave-to{opacity:0;transform:translate(-50%,-40%) scale(.98)}
</style>

<style>
.agent-label{background:linear-gradient(180deg,rgba(28,20,46,.85),rgba(8,5,16,.9));color:#fff;padding:3px 10px;border-radius:6px;font-size:12px;font-weight:600;pointer-events:none;white-space:nowrap;border:1px solid rgba(255,255,255,.14);box-shadow:0 2px 8px rgba(0,0,0,.5);font-family:'PingFang SC',sans-serif}
.loc-label{background:rgba(8,16,28,.55);color:rgba(125,211,252,.75);padding:1px 7px;border-radius:4px;font-size:10px;font-weight:500;pointer-events:none;white-space:nowrap;border:1px solid rgba(0,212,255,.18);font-family:'PingFang SC',sans-serif;backdrop-filter:blur(3px)}
.loc-label-subtle{background:rgba(40,30,16,.6);color:rgba(201,168,92,.85);padding:1px 8px;border-radius:4px;font-size:10px;font-weight:500;pointer-events:none;white-space:nowrap;border:1px solid rgba(201,168,92,.2);font-family:'PingFang SC',sans-serif;backdrop-filter:blur(2px)}
.agent-dialogue{box-sizing:border-box;width:clamp(220px,18vw,300px);min-width:220px;max-width:300px;padding:10px 14px;border-radius:12px 12px 12px 3px;background:linear-gradient(145deg,rgba(12,20,38,.96),rgba(5,8,18,.94));border:1px solid rgba(125,211,252,.45);box-shadow:0 8px 26px rgba(0,0,0,.5),0 0 18px rgba(0,212,255,.12);color:#eef8ff;font-size:13px;font-weight:500;line-height:1.6;letter-spacing:.01em;white-space:normal;word-break:normal;overflow-wrap:anywhere;writing-mode:horizontal-tb;text-orientation:mixed;text-align:left;pointer-events:none;font-family:'PingFang SC','Microsoft YaHei',system-ui,sans-serif;animation:dialogue-in .22s ease-out}
@keyframes dialogue-in{from{opacity:0;transform:translateY(8px) scale(.94)}to{opacity:1;transform:translateY(0) scale(1)}}
</style>
