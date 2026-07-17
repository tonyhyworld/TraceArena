/**
 * 观众端 / 运营台软切换：用 history.pushState，避免整页刷新清空导演历史。
 */
import { isLoggedIn } from './authStore.js'

const VIEW_EVENT = 'aiworld-viewchange'

export function getViewMode() {
  const params = new URLSearchParams(window.location.search)
  if (params.get('login') === '1' || !isLoggedIn()) return 'login'
  if (params.get('view') === 'operator') return 'operator'
  return 'viewer'
}

export function navigateView(target) {
  const next = target === 'operator' ? 'operator' : 'viewer'
  const params = new URLSearchParams(window.location.search)
  params.delete('login')
  if (next === 'operator') params.set('view', 'operator')
  else params.delete('view')
  const qs = params.toString()
  const url = qs
    ? `${window.location.pathname}?${qs}${window.location.hash}`
    : `${window.location.pathname}${window.location.hash}`
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (url !== current) {
    window.history.pushState({ aiworldView: next }, '', url)
  }
  window.dispatchEvent(new CustomEvent(VIEW_EVENT, { detail: { view: next } }))
}

export function onViewChange(handler) {
  const wrap = () => handler(getViewMode())
  window.addEventListener(VIEW_EVENT, wrap)
  window.addEventListener('popstate', wrap)
  return () => {
    window.removeEventListener(VIEW_EVENT, wrap)
    window.removeEventListener('popstate', wrap)
  }
}
