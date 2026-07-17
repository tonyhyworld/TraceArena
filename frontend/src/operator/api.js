/**
 * 运营后台 HTTP 客户端（只读）。
 * base 与 wsClient 同源：WS 走 8001，HTTP 也走 8001。
 */
import { authedFetch } from '../core/authStore.js'

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8001'

export async function apiGet(path, params) {
  const url = new URL(API_BASE + path)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    }
  }
  const resp = await authedFetch(url.toString())
  if (!resp.ok) {
    let detail = ''
    try { detail = (await resp.json()).detail } catch (_) { /* ignore */ }
    const err = new Error(detail || `HTTP ${resp.status}`)
    err.status = resp.status
    throw err
  }
  return resp.json()
}

export async function apiPost(path, body) {
  const resp = await authedFetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  if (!resp.ok) {
    let detail = ''
    try { detail = (await resp.json()).detail } catch (_) { /* ignore */ }
    const err = new Error(detail || `HTTP ${resp.status}`)
    err.status = resp.status
    throw err
  }
  return resp.json()
}

export { API_BASE }
