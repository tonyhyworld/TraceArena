/**
 * 观众端「盘面演绎」本地缓存：软切换失败或硬刷新时仍可恢复近期导演字幕。
 */
const KEY = 'aiworld.viewer.narrativeFeed.v1'
const MAX_AGE_MS = 6 * 60 * 60 * 1000

export function saveNarrativeFeed({ scenario = '', tick = 0, entries = [], feedIdCtr = 0 } = {}) {
  try {
    const slim = (entries || []).slice(-120).map((item) => ({
      tick: item.tick,
      type: item.type,
      speaker: item.speaker,
      color: item.color,
      content: item.content,
      source_refs: item.source_refs || [],
    }))
    sessionStorage.setItem(KEY, JSON.stringify({
      savedAt: Date.now(),
      scenario: String(scenario || ''),
      tick: Number(tick || 0),
      feedIdCtr: Number(feedIdCtr || 0),
      entries: slim,
    }))
  } catch {
    /* quota / private mode */
  }
}

export function loadNarrativeFeed({ scenario = '' } = {}) {
  try {
    const raw = JSON.parse(sessionStorage.getItem(KEY) || 'null')
    if (!raw || !Array.isArray(raw.entries) || !raw.entries.length) return null
    if (Date.now() - Number(raw.savedAt || 0) > MAX_AGE_MS) return null
    if (scenario && raw.scenario && raw.scenario !== scenario) return null
    return raw
  } catch {
    return null
  }
}

export function clearNarrativeFeed() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}
