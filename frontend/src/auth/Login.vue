<template>
  <div class="login-root">
    <!-- AI 风格动效背景：神经网络粒子 + 网格 + 流光 -->
    <canvas ref="canvasRef" class="login-canvas"></canvas>
    <div class="login-grid"></div>
    <div class="login-glow login-glow-1"></div>
    <div class="login-glow login-glow-2"></div>

    <div class="login-locale"><LanguageSwitcher /></div>

    <form class="login-card" @submit.prevent="handleLogin">
      <div class="login-brand">
        <div class="login-logo">
          <svg viewBox="0 0 40 40" width="52" height="52">
            <defs>
              <linearGradient id="lgrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#69dcff" />
                <stop offset="1" stop-color="#8b5bff" />
              </linearGradient>
            </defs>
            <circle cx="20" cy="20" r="12" fill="none" stroke="url(#lgrad)" stroke-width="1.5" opacity=".6">
              <animate attributeName="r" values="10;13;10" dur="3s" repeatCount="indefinite" />
            </circle>
            <circle cx="20" cy="20" r="6" fill="url(#lgrad)" opacity=".9">
              <animate attributeName="r" values="5;7;5" dur="2s" repeatCount="indefinite" />
            </circle>
            <g stroke="url(#lgrad)" stroke-width="1" opacity=".5">
              <line x1="20" y1="20" x2="34" y2="8"><animate attributeName="opacity" values=".2;.9;.2" dur="2.4s" repeatCount="indefinite" /></line>
              <line x1="20" y1="20" x2="6" y2="8"><animate attributeName="opacity" values=".9;.2;.9" dur="2.4s" repeatCount="indefinite" /></line>
              <line x1="20" y1="20" x2="34" y2="32"><animate attributeName="opacity" values=".5;.9;.5" dur="3.1s" repeatCount="indefinite" /></line>
              <line x1="20" y1="20" x2="6" y2="32"><animate attributeName="opacity" values=".9;.4;.9" dur="2.8s" repeatCount="indefinite" /></line>
            </g>
            <circle cx="34" cy="8" r="1.6" fill="#69dcff" />
            <circle cx="6" cy="8" r="1.6" fill="#8b5bff" />
            <circle cx="34" cy="32" r="1.6" fill="#69dcff" />
            <circle cx="6" cy="32" r="1.6" fill="#8b5bff" />
          </svg>
        </div>
        <div class="login-kicker">TRACEARENA · AI WORLD</div>
        <h1>{{ t('login.title') }}</h1>
        <p class="login-tag">{{ t('login.tagline') }}</p>
        <div class="login-values" :aria-label="t('login.value_label')">
          <span>{{ t('login.value_define') }}</span>
          <span>{{ t('login.value_compete') }}</span>
          <span>{{ t('login.value_visible') }}</span>
        </div>
      </div>
      <label>
        <span>{{ t('login.username') }}</span>
        <input v-model="username" autocomplete="username" autofocus required :placeholder="t('login.username_placeholder')" />
      </label>
      <label>
        <span>{{ t('login.password') }}</span>
        <input v-model="password" type="password" autocomplete="current-password" required placeholder="••••••••" />
      </label>
      <p v-if="error" class="login-error" role="alert">{{ error }}</p>
      <button type="submit" :disabled="loading" :aria-busy="loading" class="login-submit">
        <span class="btn-label">{{ loading ? t('login.loading') : t('login.submit') }}</span>
        <span class="btn-shine"></span>
      </button>
      <div class="login-footer">
        <span class="dot"></span>
        <span>{{ t('login.ready') }}</span>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { setAuth } from '../core/authStore.js'
import { t } from '../core/i18n.js'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8001'

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const canvasRef = ref(null)
let rafId = null

async function handleLogin() {
  if (!username.value.trim() || !password.value) {
    error.value = t('login.required')
    return
  }
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value.trim(), password: password.value }),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      throw new Error(data.detail || `${t('login.failed')} (${resp.status})`)
    }
    const data = await resp.json()
    setAuth(data)
    const params = new URLSearchParams(window.location.search)
    params.delete('login')
    const qs = params.toString()
    window.location.href = window.location.pathname + (qs ? `?${qs}` : '')
  } catch (e) {
    error.value = e.message || t('login.failed')
  } finally {
    loading.value = false
  }
}

// 神经网络粒子动效：节点漂移+邻近连线，营造"活着的智能网络"感
onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  let W = 0, H = 0, dpr = window.devicePixelRatio || 1
  const nodes = []
  const N = 60           // 粒子数
  const LINK_DIST = 140  // 连线阈值

  function resize() {
    W = canvas.clientWidth
    H = canvas.clientHeight
    canvas.width = W * dpr
    canvas.height = H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  function seed() {
    nodes.length = 0
    for (let i = 0; i < N; i++) {
      nodes.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        r: 1 + Math.random() * 1.5,
        hue: Math.random() < 0.5 ? 195 : 268, // 蓝/紫
      })
    }
  }

  function tick() {
    ctx.clearRect(0, 0, W, H)
    // 节点漂移
    for (const n of nodes) {
      n.x += n.vx; n.y += n.vy
      if (n.x < 0 || n.x > W) n.vx *= -1
      if (n.y < 0 || n.y > H) n.vy *= -1
    }
    // 连线
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i]
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j]
        const dx = a.x - b.x, dy = a.y - b.y
        const d = Math.hypot(dx, dy)
        if (d < LINK_DIST) {
          const alpha = (1 - d / LINK_DIST) * 0.35
          ctx.strokeStyle = `hsla(${(a.hue + b.hue) / 2}, 80%, 65%, ${alpha})`
          ctx.lineWidth = 0.6
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
        }
      }
    }
    // 节点
    for (const n of nodes) {
      ctx.fillStyle = `hsla(${n.hue}, 90%, 70%, 0.9)`
      ctx.beginPath()
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
      ctx.fill()
      // 光晕
      const grd = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 5)
      grd.addColorStop(0, `hsla(${n.hue}, 100%, 70%, 0.25)`)
      grd.addColorStop(1, 'transparent')
      ctx.fillStyle = grd
      ctx.beginPath()
      ctx.arc(n.x, n.y, n.r * 5, 0, Math.PI * 2)
      ctx.fill()
    }
    rafId = requestAnimationFrame(tick)
  }

  resize(); seed(); tick()
  const onResize = () => { resize(); seed() }
  window.addEventListener('resize', onResize)
  onUnmounted(() => {
    window.removeEventListener('resize', onResize)
    if (rafId) cancelAnimationFrame(rafId)
  })
})
</script>

<style scoped>
.login-root {
  position: relative;
  height: 100vh; width: 100vw;
  overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at 30% 20%, #1a1445 0%, #0a0a24 40%, #04041a 100%);
  font-family: 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
}

.login-locale {
  position: fixed;
  top: 18px;
  right: 18px;
  z-index: 3;
}

/* 神经网络画布 */
.login-canvas {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  opacity: .95;
}

/* 网格底纹 */
.login-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(105,220,255,.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(105,220,255,.06) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
  pointer-events: none;
}

/* 大光晕 */
.login-glow { position: absolute; border-radius: 50%; filter: blur(80px); pointer-events: none; }
.login-glow-1 {
  width: 460px; height: 460px;
  left: -100px; top: -80px;
  background: radial-gradient(circle, rgba(105,220,255,.35), transparent 70%);
  animation: floatA 12s ease-in-out infinite;
}
.login-glow-2 {
  width: 520px; height: 520px;
  right: -120px; bottom: -100px;
  background: radial-gradient(circle, rgba(139,91,255,.35), transparent 70%);
  animation: floatB 14s ease-in-out infinite;
}
@keyframes floatA { 0%,100% { transform: translate(0,0); } 50% { transform: translate(40px, 30px); } }
@keyframes floatB { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-40px, -30px); } }

/* 登录卡片 */
.login-card {
  position: relative;
  box-sizing: border-box;
  width: min(420px, calc(100vw - 32px));
  display: flex; flex-direction: column; gap: 18px;
  padding: 40px 34px 32px;
  border-radius: 22px;
  background: linear-gradient(155deg, rgba(30,26,60,.75), rgba(12,10,32,.85));
  border: 1px solid rgba(255,255,255,.1);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  box-shadow:
    0 20px 60px rgba(0,0,0,.5),
    0 0 80px rgba(105,220,255,.08),
    inset 0 1px 0 rgba(255,255,255,.08);
  animation: cardIn .8s cubic-bezier(.16,.84,.44,1);
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(20px) scale(.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

/* 顶部渐变高光边 */
.login-card::before {
  content: '';
  position: absolute; inset: 0;
  border-radius: 22px;
  padding: 1px;
  background: linear-gradient(135deg, rgba(105,220,255,.5), transparent 40%, transparent 60%, rgba(139,91,255,.4));
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
          mask-composite: exclude;
  pointer-events: none;
}

.login-brand { text-align: center; margin-bottom: 4px; }
.login-logo {
  display: inline-flex;
  padding: 6px;
  filter: drop-shadow(0 0 12px rgba(105,220,255,.5));
  margin-bottom: 10px;
}
.login-kicker {
  font-size: 10px; letter-spacing: .25em; font-weight: 800;
  background: linear-gradient(90deg, #69dcff, #8b5bff);
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
}
.login-brand h1 {
  margin: 9px 0 5px;
  font-size: 22px;
  color: #edf3ff;
  font-weight: 600;
  letter-spacing: .04em;
}
.login-tag {
  max-width: 310px;
  margin: 0 auto;
  font-size: 12px;
  line-height: 1.6;
  color: #9ca8ca;
  letter-spacing: .02em;
}
.login-values {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 15px;
}
.login-values span {
  padding: 5px 9px;
  border: 1px solid rgba(105,220,255,.16);
  border-radius: 999px;
  background: rgba(105,220,255,.055);
  color: #aebadc;
  font-size: 10px;
  line-height: 1;
  letter-spacing: .03em;
}

label {
  display: flex; flex-direction: column; gap: 6px;
  font-size: 11px; color: #8a94b8;
  letter-spacing: .05em;
  font-weight: 600;
}
input {
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 10px;
  background: rgba(0,0,0,.3);
  color: #edf3ff;
  padding: 12px 14px;
  font-size: 14px;
  outline: none;
  transition: all .2s;
  font-family: inherit;
}
input::placeholder { color: rgba(255,255,255,.25); }
input:focus {
  border-color: rgba(105,220,255,.6);
  background: rgba(0,0,0,.4);
  box-shadow: 0 0 0 3px rgba(105,220,255,.12);
}
.login-error {
  margin: -4px 0 0; font-size: 12px; color: #ff6b60;
  padding: 8px 12px;
  background: rgba(255,95,82,.08);
  border: 1px solid rgba(255,95,82,.2);
  border-radius: 8px;
}

.login-submit {
  position: relative;
  overflow: hidden;
  margin-top: 6px;
  padding: 13px 18px;
  border: none; border-radius: 11px;
  background: linear-gradient(135deg, #69dcff 0%, #5b8bff 50%, #8b5bff 100%);
  background-size: 200% 200%;
  color: #06121f;
  font-weight: 800; font-size: 14px;
  letter-spacing: .04em;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  gap: 8px;
  transition: transform .18s, box-shadow .18s;
  box-shadow: 0 4px 20px rgba(105,220,255,.35);
  animation: gradShift 6s ease infinite;
}
@keyframes gradShift { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
.login-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(105,220,255,.5);
}
.login-submit:active:not(:disabled) { transform: translateY(0); }
.login-submit:disabled { opacity: .7; cursor: default; animation: none; }
.btn-shine {
  position: absolute; top: 0; left: -60%;
  width: 40%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.4), transparent);
  transform: skewX(-20deg);
  animation: shine 3s ease-in-out infinite;
}
@keyframes shine {
  0% { left: -60%; }
  50% { left: 120%; }
  100% { left: 120%; }
}

.login-footer {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  font-size: 11px; color: #6b7695;
  letter-spacing: .05em;
  margin-top: 2px;
}
.dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #56d364;
  box-shadow: 0 0 8px #56d364;
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }

@media (max-width: 480px) {
  .login-card { padding: 32px 24px 26px; gap: 16px; }
  .login-locale { top: 12px; right: 12px; }
  .login-brand h1 { font-size: 20px; }
}

@media (prefers-reduced-motion: reduce) {
  .login-card, .login-glow-1, .login-glow-2, .login-submit,
  .btn-shine, .dot { animation: none !important; }
}
</style>
