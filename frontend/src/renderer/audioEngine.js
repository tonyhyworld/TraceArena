/**
 * 音频引擎 (P2 方案 B · B3)
 *
 * 负责：
 *   - BGM 循环 + 跨段 crossfade
 *   - SFX 一次性触发
 *   - 主音量、独立 BGM/SFX 音量、静音开关
 *
 * 声音文件由场景包提供：
 *   /scenario-assets/<scenario_dir>/assets/audio/bgm_*.mp3
 *   /scenario-assets/<scenario_dir>/assets/audio/sfx_*.mp3
 *
 * 事件到声音的映射完全由场景包声明。
 *
 * 文件不存在不报错——预加载失败时该 sfx/bgm 静默跳过，不阻塞别的音频。
 */

const DEFAULT_FILES = { bgm: {}, sfx: {} }

// 默认事件→音效映射，可被场景包 audio.yaml 覆盖。
const DEFAULT_EVENT_SFX = {}

export function createAudioEngine({ assetBaseUrl = '', files = DEFAULT_FILES, eventSfxMap = DEFAULT_EVENT_SFX, eventBgmMap = {} } = {}) {
  files = files || DEFAULT_FILES
  files.bgm = files.bgm || {}
  files.sfx = files.sfx || {}
  eventSfxMap = eventSfxMap || DEFAULT_EVENT_SFX
  // ────────────────────────────────────────────────────────────────────
  // Web Audio 上下文：浏览器需要用户手势触发才能解锁，所以延迟初始化
  // ────────────────────────────────────────────────────────────────────
  let ctx = null
  let masterGain = null
  let bgmGain = null
  let sfxGain = null

  let masterVolume = 0.8
  let bgmVolume = 0.35
  let sfxVolume = 0.9
  let muted = false

  // 当前 BGM 状态 + 在播的 source（每个 BGM 由 BufferSource + GainNode 组成）
  let currentBgmState = null // null | 'idle' | 'challenge_active' | 'finale'
  let currentBgmTrack = null // { source, gain, key }

  // 预加载缓冲：路径 → AudioBuffer
  const buffers = new Map()
  // 正在解码的 promise（避免重复请求）
  const pending = new Map()

  // 队列：用户解锁前的请求暂存
  let unlocked = false
  const pendingActions = []

  // ────────────────────────────────────────────────────────────────────
  // 初始化（首次用户交互时调用）
  // ────────────────────────────────────────────────────────────────────
  function ensureContext() {
    if (ctx) return ctx
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)()
    } catch (e) {
      console.warn('[audio] AudioContext 不可用', e)
      return null
    }
    masterGain = ctx.createGain()
    masterGain.gain.value = muted ? 0 : masterVolume
    masterGain.connect(ctx.destination)

    bgmGain = ctx.createGain()
    bgmGain.gain.value = bgmVolume
    bgmGain.connect(masterGain)

    sfxGain = ctx.createGain()
    sfxGain.gain.value = sfxVolume
    sfxGain.connect(masterGain)

    return ctx
  }

  /** 用户首次点击触发：解锁 + 排空 pendingActions。 */
  function unlock() {
    if (unlocked) return
    const c = ensureContext()
    if (!c) return
    if (c.state === 'suspended') {
      c.resume().catch(() => {})
    }
    unlocked = true
    // 排空积压
    const queue = pendingActions.slice()
    pendingActions.length = 0
    for (const fn of queue) {
      try { fn() } catch (e) { console.warn('[audio] flush action error', e) }
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // 资源加载
  // ────────────────────────────────────────────────────────────────────
  async function loadBuffer(filename) {
    if (!filename) return null
    if (buffers.has(filename)) return buffers.get(filename)
    if (pending.has(filename)) return pending.get(filename)
    const c = ensureContext()
    if (!c) return null
    const url = assetBaseUrl.replace(/\/$/, '') + '/' + filename
    const p = (async () => {
      try {
        const resp = await fetch(url)
        if (!resp.ok) {
          throw new Error('HTTP ' + resp.status)
        }
        const arr = await resp.arrayBuffer()
        const buf = await c.decodeAudioData(arr)
        buffers.set(filename, buf)
        return buf
      } catch (e) {
        // 静默失败：缺文件不应炸主流程，只 warn 一次
        if (!buffers.has(filename)) {
          buffers.set(filename, null)
          console.warn('[audio] 加载失败 (静默跳过):', filename, e.message || e)
        }
        return null
      }
    })()
    pending.set(filename, p)
    return p
  }

  /** 后台预加载所有声明的 BGM / SFX，不阻塞主流程。 */
  function preloadAll() {
    const all = [
      ...Object.values(files.bgm),
      ...Object.values(files.sfx),
    ].map(item => typeof item === 'string' ? item : item?.file).filter(Boolean)
    for (const f of all) {
      loadBuffer(f).catch(() => {})
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // BGM 状态机
  // ────────────────────────────────────────────────────────────────────
  async function setBGMState(state, { fadeMs = 1500 } = {}) {
    if (!unlocked) {
      pendingActions.push(() => setBGMState(state, { fadeMs }))
      return
    }
    if (state === currentBgmState) return
    currentBgmState = state
    const definition = state ? files.bgm[state] : null
    const filename = typeof definition === 'string' ? definition : definition?.file
    const newBuf = filename ? await loadBuffer(filename) : null

    // 旧 BGM 淡出
    const old = currentBgmTrack
    currentBgmTrack = null
    if (old) {
      try {
        const t = ctx.currentTime
        old.gain.gain.cancelScheduledValues(t)
        old.gain.gain.setValueAtTime(old.gain.gain.value, t)
        old.gain.gain.linearRampToValueAtTime(0, t + fadeMs / 1000)
        old.source.stop(t + fadeMs / 1000 + 0.1)
      } catch (e) { /* 已停 */ }
    }

    // 新 BGM 淡入
    if (newBuf || definition?.synth) {
      const src = newBuf ? ctx.createBufferSource() : ctx.createOscillator()
      if (newBuf) {
        src.buffer = newBuf
        src.loop = true
      } else {
        src.type = definition.synth.waveform || 'sine'
        src.frequency.value = Number(definition.synth.frequency || 110)
      }
      const g = ctx.createGain()
      g.gain.value = 0
      src.connect(g).connect(bgmGain)
      src.start()
      const t = ctx.currentTime
      g.gain.linearRampToValueAtTime(1, t + fadeMs / 1000)
      currentBgmTrack = { source: src, gain: g, key: state }
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // SFX 一次性触发
  // ────────────────────────────────────────────────────────────────────
  async function playSFX(sfxKey, { volume = 1, rate = 1 } = {}) {
    if (!sfxKey) return
    if (!unlocked) {
      pendingActions.push(() => playSFX(sfxKey, { volume, rate }))
      return
    }
    const definition = files.sfx[sfxKey]
    const filename = typeof definition === 'string' ? definition : definition?.file
    if (!filename && !definition?.synth) return
    if (definition?.synth && !filename) {
      const oscillator = ctx.createOscillator()
      const gain = ctx.createGain()
      const now = ctx.currentTime
      const duration = Math.max(0.04, Number(definition.synth.duration_ms || 300) / 1000)
      oscillator.type = definition.synth.waveform || 'sine'
      oscillator.frequency.setValueAtTime(Number(definition.synth.frequency || 440), now)
      if (definition.synth.end_frequency) {
        oscillator.frequency.exponentialRampToValueAtTime(
          Math.max(1, Number(definition.synth.end_frequency)), now + duration,
        )
      }
      gain.gain.setValueAtTime(Math.max(0.001, Number(volume || 1) * 0.3), now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + duration)
      oscillator.connect(gain).connect(sfxGain)
      oscillator.start(now)
      oscillator.stop(now + duration + 0.02)
      return
    }
    const buf = await loadBuffer(filename)
    if (!buf) return
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.playbackRate.value = rate
    const g = ctx.createGain()
    g.gain.value = volume
    src.connect(g).connect(sfxGain)
    src.start()
  }

  /** 事件到 SFX/BGM 的映射完全由场景包声明。 */
  function dispatchEvent(eventType, meta = {}) {
    if (!eventType) return
    const configured = eventSfxMap[eventType]
    const sfxKey = typeof configured === 'string'
      ? configured
      : (meta.passed ? configured?.passed : configured?.failed) || configured?.sfx
    if (sfxKey) playSFX(sfxKey)
    const bgmState = eventBgmMap[eventType]
    if (bgmState) setBGMState(bgmState)
  }

  // ────────────────────────────────────────────────────────────────────
  // 控制接口
  // ────────────────────────────────────────────────────────────────────
  function setMasterVolume(v) {
    masterVolume = Math.max(0, Math.min(1, v))
    if (masterGain && !muted) masterGain.gain.value = masterVolume
  }
  function setBGMVolume(v) { bgmVolume = Math.max(0, Math.min(1, v)); if (bgmGain) bgmGain.gain.value = bgmVolume }
  function setSFXVolume(v) { sfxVolume = Math.max(0, Math.min(1, v)); if (sfxGain) sfxGain.gain.value = sfxVolume }
  function setMuted(m) {
    muted = !!m
    if (masterGain) masterGain.gain.value = muted ? 0 : masterVolume
  }
  function isMuted() { return muted }
  function dispose() {
    try { currentBgmTrack?.source.stop() } catch (e) {}
    currentBgmTrack = null
    if (ctx && ctx.state !== 'closed') ctx.close().catch(() => {})
    ctx = null
  }

  return {
    unlock,
    preloadAll,
    setBGMState,
    playSFX,
    dispatchEvent,
    setMasterVolume,
    setBGMVolume,
    setSFXVolume,
    setMuted,
    isMuted,
    dispose,
  }
}
