/**
 * AI World WebSocket 客户端
 *
 * 双频道：
 *   viewer   → 渲染层（world_snapshot + presentation_segment）
 *   operator → 运营台（全量数据）
 *
 * 用法：
 *   import { createWSClient } from '@/core/wsClient'
 *   const ws = createWSClient('viewer')
 *   ws.on('world_snapshot', handler)
 *   ws.connect()
 */

import { getToken, redirectToLogin } from './authStore.js'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8001/ws'

// 按频道缓存单例，避免组件重复挂载 / Vite HMR 模块重估时
// 反复 new WebSocket 造成同一频道多条连接、后端重复广播。
const _clients = {}

export function createWSClient(channel = 'viewer') {
  if (_clients[channel]) return _clients[channel]
  const client = _buildWSClient(channel)
  _clients[channel] = client
  return client
}

function _buildWSClient(channel = 'viewer') {
  let socket = null
  let reconnectTimer = null
  const pendingCommands = []
  const handlers = {}
  let isDestroyed = false
  let isConnected = false

  // 每个消息类型支持多个 handler。旧实现是覆盖式赋值——同频道两个组件
  // 订阅同一 type 时，后挂载的会静默顶掉先挂载的。
  function on(type, handler) {
    if (!handlers[type]) handlers[type] = []
    handlers[type].push(handler)
    return () => {  // 返回取消订阅函数（只移除自己这一个）
      const list = handlers[type]
      if (!list) return
      const idx = list.indexOf(handler)
      if (idx >= 0) list.splice(idx, 1)
      if (!list.length) delete handlers[type]
    }
  }

  function emit(type, data) {
    // 单个 handler 抛错不能拖死同类型其它订阅者——
    // HMR / 旧闭包异常时，否则会出现「TTS 仍播、文字流不更新」。
    for (const h of [...(handlers[type] || [])]) {
      try {
        h(data)
      } catch (err) {
        console.error(`[ws] handler error type=${type}`, err)
      }
    }
    for (const h of [...(handlers['*'] || [])]) {
      try {
        h(type, data)
      } catch (err) {
        console.error(`[ws] wildcard handler error type=${type}`, err)
      }
    }
  }

  function send(cmd) {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(cmd))
      emit('command_sent', { cmd })
      return true
    }
    // 页面加载与 WebSocket 握手存在竞态。控制命令不能静默丢弃。
    if (pendingCommands.length >= 20) pendingCommands.shift()
    pendingCommands.push(cmd)
    emit('command_queued', { cmd, pending: pendingCommands.length })
    return false
  }

  function flushPendingCommands() {
    if (socket?.readyState !== WebSocket.OPEN) return
    while (pendingCommands.length) {
      const cmd = pendingCommands.shift()
      socket.send(JSON.stringify(cmd))
      emit('command_sent', { cmd, queued: true })
    }
  }

  function connect() {
    if (isDestroyed) return
    if (
      socket?.readyState === WebSocket.OPEN
      || socket?.readyState === WebSocket.CONNECTING
    ) return
    clearTimeout(reconnectTimer)  // 防止已排队的重连定时器叠加出第二条连接
    const token = getToken()
    if (!token) {
      redirectToLogin()
      return
    }
    socket = new WebSocket(`${WS_URL}?channel=${channel}&token=${encodeURIComponent(token)}`)

    socket.onopen = () => {
      isConnected = true
      console.log(`[ws] 连接成功 channel=${channel}`)
      clearTimeout(reconnectTimer)
      emit('connected', {})
      flushPendingCommands()
    }

    socket.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        emit(msg.type, msg)
      } catch (e) {
        console.warn('[ws] 消息解析失败', e)
      }
    }

    socket.onclose = (evt) => {
      if (isDestroyed) return
      isConnected = false
      if (evt?.code === 4401) {
        // 服务端判定 token 无效/过期，重连也没用，直接跳登录页
        console.log('[ws] 登录已失效')
        redirectToLogin()
        return
      }
      if (evt?.code === 4403) {
        // 用户仍是登录状态，只是没有这个频道(viewer/operator)的功能权限——
        // 不清登录态、不重连，交给上层 UI 显示"无权限"提示
        console.log('[ws] 当前账号没有此频道的访问权限')
        emit('forbidden', {})
        return
      }
      console.log('[ws] 断开，3s 后重连...')
      emit('disconnected', {})
      reconnectTimer = setTimeout(connect, 3000)
    }

    socket.onerror = (e) => {
      console.error('[ws] 错误', e)
      emit('connection_error', {})
    }
  }

  function destroy() {
    isDestroyed = true
    clearTimeout(reconnectTimer)
    socket?.close()
    // 从单例缓存移除，使下次挂载得到全新可用客户端（而非已销毁的实例）
    if (_clients[channel] === api) delete _clients[channel]
  }

  // 控制命令快捷方法
  const commands = {
    play:  () => send({ cmd: 'play' }),
    pause: () => send({ cmd: 'pause' }),
    step:  () => send({ cmd: 'step' }),
    reset: () => send({ cmd: 'reset' }),
    replay: (runId = null) => send({ cmd: 'replay', run_id: runId }),
    oracle: (target, text, effects) => send({ cmd: 'oracle', target, text, ...(effects && effects.length ? { effects } : {}) }),
    setSpeed: (interval) => send({ cmd: 'speed', interval }),
  }

  const api = {
    on,
    send,
    connect,
    destroy,
    commands,
    get connected() { return isConnected },
  }
  return api
}
