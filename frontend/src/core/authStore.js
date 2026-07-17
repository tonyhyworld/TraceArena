/**
 * 账户体系 · 前端登录态
 *
 * token 存 localStorage（内部工具场景可接受，不追求 httpOnly cookie 那套）。
 * authedFetch 是 window.fetch 的直通封装，自动带 Authorization header，
 * 401 时清空登录态并跳转登录页——所有裸 fetch() 调用点原地替换成它即可。
 */

const STORAGE_KEY = 'aiworld_auth'

function _read() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (_) {
    return null
  }
}

export function getToken() {
  return _read()?.token || ''
}

export function getCurrentUser() {
  const auth = _read()
  if (!auth) return null
  const { token, ...user } = auth
  return user
}

export function setAuth({ token, user_id, username, display_name, is_admin, permissions }) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    token, user_id, username, display_name, is_admin, permissions: permissions || [],
  }))
}

/** 功能权限判断：管理员绕过所有检查 */
export function hasPermission(key) {
  const user = getCurrentUser()
  if (!user) return false
  if (user.is_admin) return true
  return (user.permissions || []).includes(key)
}

export function clearAuth() {
  localStorage.removeItem(STORAGE_KEY)
}

export function logout() {
  clearAuth()
  const params = new URLSearchParams(window.location.search)
  params.set('login', '1')
  params.delete('view')
  window.location.search = params.toString()
  window.location.hash = ''
}

export async function refreshCurrentUser() {
  const token = getToken()
  if (!token) return null
  const base = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8001'
  const resp = await authedFetch(`${base}/auth/me`)
  if (!resp.ok) return null
  const user = await resp.json()
  setAuth({
    token,
    user_id: user.user_id,
    username: user.username,
    display_name: user.display_name,
    is_admin: user.is_admin,
    permissions: user.permissions || [],
  })
  return user
}

export function isLoggedIn() {
  return !!getToken()
}

export function redirectToLogin() {
  clearAuth()
  if (!window.location.search.includes('login=1')) {
    const params = new URLSearchParams(window.location.search)
    params.set('login', '1')
    window.location.search = params.toString()
  }
}

/** fetch 的直通封装：自动带 Authorization header，401 时跳登录页 */
export async function authedFetch(url, options = {}) {
  const token = getToken()
  const headers = { ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(url, { ...options, headers })
  if (resp.status === 401) {
    redirectToLogin()
  }
  return resp
}
