/**
 * 外部 Agent 接入 API（B 轨）
 */
import { authedFetch } from './authStore.js'

export function apiBase() {
  return import.meta.env.VITE_API_BASE || 'http://localhost:8001'
}

export async function copyToClipboard(text) {
  const value = String(text || '')
  if (!value) throw new Error('无内容可复制')
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const ta = document.createElement('textarea')
  ta.value = value
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}

async function parseJson(resp) {
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    const detail = data.detail || data.message || resp.statusText
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export async function patchAgentDriver(base, slotId, body) {
  const resp = await authedFetch(`${base}/agent/config/agents/${slotId}/driver`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(resp)
}

export async function createAgentLink(base, slotId) {
  const resp = await authedFetch(`${base}/agent/slots/${slotId}/link`, {
    method: 'POST',
  })
  return parseJson(resp)
}

export async function revokeAgentLink(base, slotId) {
  const resp = await authedFetch(`${base}/agent/slots/${slotId}/link`, {
    method: 'DELETE',
  })
  return parseJson(resp)
}

export async function fetchSlotStatus(base, slotId) {
  const resp = await authedFetch(`${base}/agent/slots/${slotId}/status`)
  return parseJson(resp)
}

export function normalizeAgentConfig(agent, base = apiBase()) {
  const slotToken = agent.slot_token || ''
  const joinUrl = agent.join_url
    || (slotToken ? `${base}/agent/join?t=${slotToken}` : '')
  const skillUrl = agent.skill_url || `${base}/agent/skill.md`
  const copyBundle = agent.copy_bundle
    || (joinUrl ? `Read ${skillUrl}, then connect with: ${joinUrl}` : '')
  return {
    ...agent,
    driver: agent.driver || 'llm',
    api_key: agent.api_key || '',
    join_url: joinUrl,
    copy_bundle: copyBundle,
    skill_url: skillUrl,
    slot_token: slotToken,
    external_status: agent.external_status || null,
    has_join_token: Boolean(agent.has_join_token || slotToken),
  }
}

export function applyLinkPayload(agent, payload) {
  if (!payload) return agent
  agent.join_url = payload.join_url || agent.join_url
  agent.copy_bundle = payload.copy_bundle || agent.copy_bundle
  agent.skill_url = payload.skill_url || agent.skill_url
  agent.has_join_token = true
  return agent
}
