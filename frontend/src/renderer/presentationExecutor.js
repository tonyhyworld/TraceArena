import * as THREE from 'three'
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js'

/**
 * 场景无关的演出执行器。
 *
 * OS 只下发语义化的 animation/camera/effect 标识；具体资源、坐标和镜头参数
 * 全部从当前场景包 render 配置解析，避免把任何场景动作硬编码进 OS。
 */
export function createPresentationExecutor({
  getAgentEntry,
  getScene,
  getCamera,
  getControls,
  getRenderConfig,
  getFBXClips,
  resolveLocationPosition,
  resolveObjectPosition,
  resolveAsset,
  playSound,
  playMusic,
}) {
  const dialogueTimers = new Map()
  const dialogueObjects = new Map()
  const objectPresentations = new Map()
  let cameraTweenToken = 0
  let lastCameraKey = ''
  let lastCameraAt = 0

  function executeSegment(segment = {}) {
    if (segment.kind === 'world_observation') {
      // 桥接段保持上一镜头，让世界自然呼吸；反复回主镜头会形成循环感。
      return
    }
    if (segment.kind === 'render_command') {
      executeRenderCommand(segment.payload || {}, segment.duration_ms)
      return
    }
    if (segment.kind !== 'agent_action') return
    const payload = segment.payload || {}
    const render = payload.render || {}
    const durationMs = Math.max(300, Number(segment.duration_ms || render.duration_ms || 1800))

    playAnimation(payload.actor_id, render.animation, durationMs)
    applyMovement(payload, render)
    applyCamera(render.camera, payload.actor_id, durationMs)
    // 把目标 agent id 也传给 effect，relation_line 等双角色特效需要
    applyEffect(render.effect, payload.actor_id, durationMs, payload.target_agent_id || payload.target_id)
  }

  function executeRenderCommand(command = {}, segmentDurationMs = 0) {
    const config = getRenderConfig?.() || {}
    const commandType = String(command.command_type || '')
    const semanticAction = String(command.semantic_action || '')
    const targets = Array.isArray(command.target_ids) ? command.target_ids : []
    const actorId = targets[0] || null
    const targetId = targets[1] || null
    const durationMs = Math.max(
      300,
      Number(command.duration_ms || segmentDurationMs || 1800),
    )
    const bindingId = command.binding_id
      || config.bindings?.actions?.[semanticAction]
      || config.bindings?.outcomes?.[command.parameters?.outcome]
      || null
    const render = (bindingId && config.actions?.[bindingId]) || {}

    if (commandType === 'character') {
      playAnimation(actorId, render.animation || semanticAction, durationMs)
      const movementPayload = {
        actor_id: actorId,
        target_object_id: targetId,
      }
      applyMovement(movementPayload, render)
      return
    }
    if (commandType === 'object') {
      const objectId = targetId || actorId
      const objectBinding = bindingId
        || config.bindings?.objects?.[objectId]
        || objectId
      const objectRender = config.objects?.[objectBinding] || {}
      const effect = objectRender.effects?.[command.parameters?.outcome]
        || objectRender.effects?.no_effect
        || 'scan_pulse'
      applyCamera('object_focus', null, durationMs)
      applyEffect(effect, actorId, durationMs, null)
      presentObject(objectId, objectRender, durationMs, command.parameters || {})
      return
    }
    if (commandType === 'camera') {
      applyCamera(bindingId || semanticAction, actorId, durationMs)
      return
    }
    if (commandType === 'effect') {
      applyEffect(bindingId || semanticAction, actorId, durationMs, targetId)
      return
    }
    if (commandType === 'sound') {
      playSound?.(bindingId || semanticAction, command.parameters || {})
      return
    }
    if (commandType === 'music') {
      playMusic?.(bindingId || semanticAction, command.parameters || {})
      return
    }
    if (commandType === 'wait') return
    if (commandType === 'subtitle' || commandType === 'ui') {
      const text = command.parameters?.text || ''
      if (actorId && text) showDialogue(actorId, text, durationMs)
      if (render.camera) applyCamera(render.camera, actorId, durationMs)
      if (render.effect) applyEffect(render.effect, actorId, durationMs, targetId)
    }
  }

  function presentObject(objectId, objectRender, durationMs, parameters) {
    if (!objectId || !objectRender) return
    const scene = getScene()
    if (!scene) return
    const previous = objectPresentations.get(objectId)
    if (previous) {
      clearTimeout(previous.timer)
      scene.remove(previous.object)
    }
    const root = new THREE.Group()
    const position = resolveObjectPosition?.(objectId, objectRender)
    if (position) root.position.copy(position)
    const imageFormats = ['svg', 'png', 'jpg', 'jpeg', 'webp']
    const iconPath = objectRender.icon || (
      imageFormats.includes(String(objectRender.format || '').toLowerCase())
        ? objectRender.asset : ''
    )
    if (iconPath) {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: new THREE.TextureLoader().load(resolveAsset?.(iconPath) || iconPath),
        transparent: true,
        depthWrite: false,
      }))
      sprite.scale.set(1.1, 1.1, 1)
      sprite.position.y = 1.4
      sprite.userData.cameraIgnore = true
      root.add(sprite)
    }
    if (objectRender.display_mode === 'ui_card' || objectRender.ui?.show_card) {
      const element = document.createElement('div')
      element.className = 'world-object-card'
      const label = objectRender.ui?.label || objectRender.ui?.display_name || objectId
      const values = parameters.values || {}
      const detail = Object.entries(values).slice(0, 2)
        .map(([key, value]) => `${key} ${value}`).join(' · ')
      const strong = document.createElement('strong')
      strong.textContent = String(label)
      element.appendChild(strong)
      if (detail) {
        const span = document.createElement('span')
        span.textContent = detail
        element.appendChild(span)
      }
      const labelObject = new CSS2DObject(element)
      labelObject.position.y = iconPath ? 2.15 : 1.25
      root.add(labelObject)
    }
    scene.add(root)
    const timer = setTimeout(() => {
      scene.remove(root)
      objectPresentations.delete(objectId)
    }, Math.min(8000, Math.max(900, durationMs)))
    objectPresentations.set(objectId, { object: root, timer })
  }

  function applyMovement(payload, render) {
    if (render.animation !== 'walk' && render.animation !== 'run') return
    const entry = getAgentEntry(payload.actor_id)
    const target = resolveLocationPosition(payload.target_object_id, payload.actor_id)
    if (!entry?.group || !target) return
    entry.group.userData.targetPos = target.clone()
    entry.group.userData.moving = true
  }

  // ━━ 通用动画语义映射到 FBX 动作库 ━━
  // FBX 库提供：idle / jog / celebrate / shoved
  // 场景包声明通用动画语义；执行器不识别任何业务 action_id。
  const ANIM_NAME_ALIASES = {
    walk: 'walking', run: 'walking', move: 'walking',
    speak: 'sitting_talking', talk: 'sitting_talking', present: 'celebrate',
    success: 'celebrate', celebrate: 'celebrate',
    inspect: 'sad_idle', observe: 'sad_idle', think: 'sad_idle',
    backlash: 'shoved', invalid: 'shoved', fail: 'shoved',
    confront: 'angry', attack: 'angry', angry: 'angry', use_tool: 'angry',
    collaborate: 'sitting_talking', covert: 'sad_idle',
    idle: 'sad_idle',
  }

  function playAnimation(actorId, animationName, durationMs) {
    if (!actorId || !animationName) return
    const entry = getAgentEntry(actorId)
    const group = entry?.group
    if (!group) return

    const mixer = group.userData.mixer
    const clips = group.userData.gltfAnimations || []
    if (mixer) {
      const rawName = String(animationName).toLowerCase()
      const normalized = ANIM_NAME_ALIASES[rawName] || rawName
      let clip = clips.find(item => item.name.toLowerCase() === normalized)
        || clips.find(item => item.name.toLowerCase().includes(normalized))

      // ★ 动态注入：角色没有这个 clip → 从 fbxBundle 取并注入
      if (!clip) {
        const fbxClips = getFBXClips?.()
        if (fbxClips) {
          clip = fbxClips[normalized]
            || Object.values(fbxClips).find(c => c.name === normalized)
          if (clip) {
            clips.push(clip)
            group.userData.gltfAnimations = clips  // 下次直接命中
          }
        }
      }

      if (clip) {
        const next = mixer.clipAction(clip)
        const previous = group.userData.currentAction
        next.reset().fadeIn(0.18).play()
        previous?.fadeOut(0.18)
        group.userData.currentAction = next
        window.setTimeout(() => playIdle(group), durationMs)
        return
      }
    }

    // 无动画资源时仍提供明确反馈
    group.userData.presentationAnimation = {
      name: animationName,
      startedAt: performance.now(),
      durationMs,
    }
  }

  function playIdle(group) {
    const mixer = group.userData.mixer
    const clips = group.userData.gltfAnimations || []
    if (!mixer || !clips.length) return
    const clip = clips.find(item => item.name.toLowerCase() === 'idle') || clips[0]
    const next = mixer.clipAction(clip)
    const previous = group.userData.currentAction
    if (next !== previous) {
      next.reset().fadeIn(0.2).play()
      previous?.fadeOut(0.2)
      group.userData.currentAction = next
    }
  }

  function update(now) {
    // ────────────────────────────────────────────────────────────────────
    // P0-h：所有角色在"非动作"间隙的环境性微动作（呼吸 + 扫视 + 微转向）
    // ────────────────────────────────────────────────────────────────────
    const ambientT = now / 1000
    const allEntries = Object.values(getAllAgentEntries())
    for (let i = 0; i < allEntries.length; i++) {
      const e = allEntries[i]
      if (!e?.group) continue
      if (e.group.userData.presentationAnimation) continue   // 主动作期间不叠加
      if (e.group.userData.moving) continue                  // 走动期间不叠加
      const grp = e.group
      // 每个 agent 给个偏相位避免三人同步呼吸像跳广播体操
      const phase = i * 1.7
      // 呼吸：上半身轻微缩放（用 scale.y 模拟）
      const breath = Math.sin(ambientT * 1.1 + phase) * 0.012
      grp.scale.y = 1 + breath
      // 头部缓慢左右扫视（绕 Y 转 ±0.06rad ≈ ±3.5°），低频
      const scan = Math.sin(ambientT * 0.35 + phase * 1.3) * 0.06
      // 注意：如果角色当前有 fixed yaw（移动到目标后朝向），叠加增量而非覆盖
      const baseYaw = grp.userData.baseYaw ?? grp.rotation.y
      if (grp.userData.baseYaw === undefined) grp.userData.baseYaw = baseYaw
      grp.rotation.y = baseYaw + scan
      // 偶尔（每 ~7-10 秒）做一次小幅"侧身换重心"
      const fidget = Math.sin(ambientT * 0.18 + phase * 0.9)
      grp.rotation.z = fidget * 0.015
    }

    // ────────────────────────────────────────────────────────────────────
    // 程序化身体语言：在没有真 GLB 动画 clip 的情况下，用刚体变换模拟 8+ 种动作
    // 角色朝向和动作表现由场景绑定提供的通用动画语义决定。
    // ────────────────────────────────────────────────────────────────────
    for (const entry of Object.values(getAllAgentEntries())) {
      const animation = entry?.group?.userData?.presentationAnimation
      if (!animation) continue
      const grp = entry.group
      const progress = Math.min(1, (now - animation.startedAt) / animation.durationMs)
      const wave = Math.sin(progress * Math.PI * 4)         // 高频抖动 [-1,1]
      const arc = Math.sin(progress * Math.PI)              // 单驼峰 [0..1..0]
      const name = String(animation.name || '').toLowerCase()

      // 默认归零（避免上一帧残留）
      grp.rotation.x = 0
      grp.rotation.y = 0
      grp.rotation.z = 0
      grp.position.y = 0
      grp.scale.setScalar(1)
      if (grp.userData.ring?.material) grp.userData.ring.material.opacity = 0.7

      if (name === 'talk' || name === 'speak' || name === 'present') {
        // 陈述：大幅左右转 + 头微仰 + 整体微涨。
        grp.rotation.y = wave * 0.18
        grp.rotation.x = -arc * 0.08
        grp.scale.setScalar(1 + arc * 0.04)
      } else if (name === 'collaborate') {
        // 协作：身体微前倾 + 低幅左右晃。
        grp.rotation.x = arc * 0.10
        grp.rotation.y = wave * 0.05
      } else if (name === 'think') {
        // 思考：头微低 + 极缓微倾
        grp.rotation.x = arc * 0.12
        grp.rotation.z = wave * 0.02
      } else if (name === 'use_tool') {
        // 用工具：身体前倾 + 小幅垂直晃（埋头干活）
        grp.rotation.x = 0.18 + arc * 0.06
        grp.position.y = -arc * 0.05
      } else if (name === 'observe') {
        // 观察：抬头远眺 + 缓慢转身扫视
        grp.rotation.x = -0.12
        grp.rotation.y = progress * Math.PI * 0.5 - Math.PI * 0.25
      } else if (name === 'inspect') {
        // 检查：弯腰俯身 + 慢慢凑近
        grp.rotation.x = 0.32 * arc
        grp.position.y = -0.12 * arc
      } else if (name === 'share') {
        // 分享：整体前倾并略微放大。
        grp.rotation.x = 0.22 * arc
        grp.scale.setScalar(1 + arc * 0.06)
        if (grp.userData.ring?.material) grp.userData.ring.material.opacity = 0.7 + arc * 0.3
      } else if (name === 'confront' || name === 'attack' || name === 'angry') {
        // 对抗：突然前冲并放大。
        grp.rotation.x = 0.25 * (progress < 0.4 ? progress / 0.4 : 1)
        grp.rotation.y = wave * 0.10
        grp.scale.setScalar(1 + arc * 0.08)
      } else if (name === 'covert') {
        // 隐蔽行动：背身、缩低并降低光环亮度。
        grp.rotation.y = Math.PI - wave * 0.04          // 背对观众
        grp.position.y = -0.15 * arc                    // 蹲下
        grp.scale.y = 1 - arc * 0.12                    // 缩矮
        // 让环变暗（"消失"感）
        if (grp.userData.ring?.material) grp.userData.ring.material.opacity = 0.7 - arc * 0.5
      } else if (name === 'recover') {
        // 恢复：缓慢上扬并放大。
        grp.rotation.x = -arc * 0.06
        grp.position.y = arc * 0.08
        grp.scale.setScalar(1 + arc * 0.05)
      } else if (name === 'propose') {
        // 提议：前倾并放大。
        grp.rotation.x = -0.08
        grp.scale.setScalar(1 + arc * 0.06)
      } else if (name !== 'walk' && name !== 'run') {
        // 兜底：轻微呼吸
        grp.scale.setScalar(1 + Math.max(0, wave) * 0.03)
      }

      if (progress >= 1) {
        grp.rotation.x = 0
        grp.rotation.y = 0
        grp.rotation.z = 0
        grp.position.y = 0
        grp.scale.setScalar(1)
        if (grp.userData.ring?.material) grp.userData.ring.material.opacity = 0.7
        delete grp.userData.presentationAnimation
      }
    }
  }

  function getAllAgentEntries() {
    try {
      const all = getAgentEntry('__all__')
      if (all && typeof all === 'object') return all
    } catch (_) { /* ignore */ }
    const render = getRenderConfig?.() || {}
    const ids = new Set([
      ...Object.keys(render.characters || {}),
      ...Object.keys(render.agent_bindings || {}),
    ])
    const out = {}
    for (const id of ids) {
      try {
        const entry = getAgentEntry(id)
        if (entry) out[id] = entry
      } catch (_) { /* ignore */ }
    }
    return out
  }

  function showDialogue(actorId, text, durationMs) {
    const entry = getAgentEntry(actorId)
    if (!entry?.group) return
    // 舞台同一时间只突出一名发言者，避免多块长文本互相遮挡。
    clearDialogues()

    const element = document.createElement('div')
    element.className = 'agent-dialogue'
    element.textContent = summarizeDialogue(text)
    element.setAttribute('role', 'status')
    const label = new CSS2DObject(element)
    label.position.set(0, 3.05, 0)
    entry.group.add(label)
    entry.group.userData.dialogueObject = label
    dialogueObjects.set(actorId, { entry, label })

    dialogueTimers.set(actorId, window.setTimeout(() => {
      removeDialogue(actorId)
    }, Math.min(5200, Math.max(2200, durationMs))))
  }

  function summarizeDialogue(value) {
    const text = String(value || '')
      .replace(/\s+/g, ' ')
      .replace(/^[；;，,\s]+|[；;，,\s]+$/g, '')
      .trim()
    if (text.length <= 72) return text
    const clauses = text.split(/[。！？；;]/).map(item => item.trim()).filter(Boolean)
    const summary = clauses.slice(0, 2).join('；')
    const result = summary.length >= 24 ? summary : text
    return `${result.slice(0, 72).replace(/[，,；;\s]+$/g, '')}…`
  }

  function removeDialogue(actorId) {
    const active = dialogueObjects.get(actorId)
    if (active) {
      active.entry.group.remove(active.label)
      if (active.entry.group.userData.dialogueObject === active.label) {
        delete active.entry.group.userData.dialogueObject
      }
      dialogueObjects.delete(actorId)
    }
    if (dialogueTimers.has(actorId)) {
      window.clearTimeout(dialogueTimers.get(actorId))
      dialogueTimers.delete(actorId)
    }
  }

  function clearDialogues() {
    for (const actorId of [...dialogueObjects.keys()]) removeDialogue(actorId)
  }

  function applyCamera(cameraId, actorId, durationMs) {
    // P0-h+：重启 LLM 驱动的运镜，但加慢/防抖避免历史"晕头转向"问题：
    //   - tween 1.8-2.5s（电影感，不是急切）
    //   - 任意两次镜头切换之间至少间隔 2.5s（防止 1 秒切 3 次）
    //   - 同镜头+同 actor 6s 内不重复
    if (!cameraId || cameraId === 'none') return
    const cameraKey = `${cameraId}:${actorId || ''}`
    const now = performance.now()
    if (cameraKey === lastCameraKey && now - lastCameraAt < 6000) return
    // 不同镜头之间也要冷却，避免连续硬切
    if (now - lastCameraAt < 2500) return
    lastCameraKey = cameraKey
    lastCameraAt = now
    const cameras = getRenderConfig()?.cameras || {}
    const aliases = {
      focus_object: 'object_focus',
      focus_actor: 'actor_closeup',
      close: 'camera_close',
      follow: 'camera_follow',
      wide: 'camera_main',
      overview: 'final_overview',
      static: 'camera_main',
    }
    const resolvedId = aliases[cameraId] || cameraId
    const config = cameras[resolvedId]
      || cameras[`camera_${resolvedId}`]
    if (!config) return
    const camera = getCamera()
    const controls = getControls()
    if (!camera || !controls) return

    const actor = getAgentEntry(actorId)?.group
    const target = actor?.position?.clone() || vectorFrom(config.look_at) || controls.target.clone()
    target.y = Math.max(0.8, target.y + Number(config.height || 0) * 0.35)

    let destination = vectorFrom(config.position)
    if (!destination && actor) {
      const distance = Number(config.distance || 5)
      const height = Number(config.height || 2.5)
      // 方向以场景主镜头为基准，不继承上一次可能已经穿模的镜头方向。
      const mainPosition = vectorFrom(cameras.camera_main?.position)
      const direction = (mainPosition || camera.position).clone().sub(target).setY(0)
      if (direction.lengthSq() < 0.01) direction.set(0, 0, 1)
      destination = actor.position.clone()
        .add(direction.normalize().multiplyScalar(distance))
        .add(new THREE.Vector3(0, height, 0))
    }
    if (!destination) return
    destination = findSafeCameraPosition(destination, target, actor)
    // P0-h+：慢速电影感 tween。范围 1.8-2.6s，让运镜有"推/拉/摇"的呼吸感
    const tweenMs = Math.min(2600, Math.max(1800, durationMs * 0.7))
    tweenCamera(camera, controls, destination, target, tweenMs)
  }

  function findSafeCameraPosition(preferred, target, actor) {
    const scene = getScene()
    const safe = preferred.clone()
    safe.y = Math.max(1.4, safe.y, target.y + 0.45)
    if (!scene || hasClearSight(target, safe, actor)) return safe

    const horizontal = safe.clone().sub(target).setY(0)
    const distance = Math.max(3.2, horizontal.length())
    const baseAngle = Math.atan2(horizontal.z, horizontal.x)
    const heights = [Math.max(safe.y, target.y + 1.5), target.y + 3, target.y + 5]
    for (const height of heights) {
      for (const offset of [Math.PI / 4, -Math.PI / 4, Math.PI / 2, -Math.PI / 2, Math.PI]) {
        const angle = baseAngle + offset
        const candidate = new THREE.Vector3(
          target.x + Math.cos(angle) * distance,
          Math.max(1.4, height),
          target.z + Math.sin(angle) * distance,
        )
        if (hasClearSight(target, candidate, actor)) return candidate
      }
    }
    // 最终兜底：目标头顶上方 10m 俯拍，绝不穿模
    return target.clone().add(new THREE.Vector3(0, 10, 3))
  }

  function hasClearSight(target, destination, actor) {
    const scene = getScene()
    const origin = target.clone()
    const direction = destination.clone().sub(origin)
    const distance = direction.length()
    if (!scene || distance < 0.1) return true
    const raycaster = new THREE.Raycaster(origin, direction.normalize(), 0.35, distance - 0.35)
    const hits = raycaster.intersectObjects(scene.children, true)
    return !hits.some(hit => {
      if (!hit.object?.isMesh || !hit.object.visible) return false
      if (actor && isDescendantOf(hit.object, actor)) return false
      if (hit.object.userData?.cameraIgnore) return false
      return true
    })
  }

  function isDescendantOf(object, parent) {
    let current = object
    while (current) {
      if (current === parent) return true
      current = current.parent
    }
    return false
  }

  function tweenCamera(camera, controls, destination, target, durationMs) {
    const token = ++cameraTweenToken
    const fromPosition = camera.position.clone()
    const fromTarget = controls.target.clone()
    const startedAt = performance.now()
    const animateCamera = now => {
      if (token !== cameraTweenToken) return
      const raw = Math.min(1, (now - startedAt) / Math.max(1, durationMs))
      const eased = 1 - Math.pow(1 - raw, 3)
      camera.position.lerpVectors(fromPosition, destination, eased)
      controls.target.lerpVectors(fromTarget, target, eased)
      if (raw < 1) requestAnimationFrame(animateCamera)
    }
    requestAnimationFrame(animateCamera)
  }

  // ────────────────────────────────────────────────────────────────────
  // 9 种 effect 的真实现：每种语义对应独立视觉
  // glow / warning_flash / scan_pulse / dialogue_highlight / risk_wave
  // evidence_reveal / relation_line / final_flash / neutral_pulse
  // ────────────────────────────────────────────────────────────────────
  function applyEffect(effectId, actorId, durationMs, targetActorId) {
    if (!effectId || effectId === 'none') return
    const scene = getScene()
    const actor = getAgentEntry(actorId)?.group
    if (!scene || !actor) return
    const dur = Math.max(600, durationMs * 0.85)

    switch (String(effectId)) {
      case 'glow':              return effectGlow(scene, actor, dur)
      case 'warning_flash':     return effectWarningFlash(scene, actor, dur)
      case 'scan_pulse':        return effectScanPulse(scene, actor, dur)
      case 'dialogue_highlight':return effectDialoguePopup(scene, actor, dur)
      case 'risk_wave':         return effectRiskWave(scene, actor, dur)
      case 'evidence_reveal':   return effectEvidenceReveal(scene, actor, dur)
      case 'relation_line':     return effectRelationLine(scene, actor, getAgentEntry(targetActorId)?.group, dur)
      case 'final_flash':       return effectFinalFlash(scene, dur)
      case 'neutral_pulse':     return effectNeutralPulse(scene, actor, dur)
      // 兼容旧 alias
      case 'success':           return effectGlow(scene, actor, dur, '#55e69a')
      case 'fail':              return effectWarningFlash(scene, actor, dur)
      default:                  return effectNeutralPulse(scene, actor, dur)
    }
  }

  function tweenAndRemove(scene, mesh, durationMs, onFrame) {
    const start = performance.now()
    const step = now => {
      const p = Math.min(1, (now - start) / durationMs)
      onFrame(p, mesh)
      if (p < 1) requestAnimationFrame(step)
      else {
        scene.remove(mesh)
        mesh.geometry?.dispose?.()
        mesh.material?.dispose?.()
      }
    }
    requestAnimationFrame(step)
  }

  // ① glow —— 金色光晕呼吸（成功的关键动作）
  function effectGlow(scene, actor, durationMs, color = '#ffd24a') {
    const halo = new THREE.Mesh(
      new THREE.SphereGeometry(0.55, 24, 16),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55, depthWrite: false }),
    )
    halo.position.copy(actor.position); halo.position.y = 1.4
    scene.add(halo)
    tweenAndRemove(scene, halo, durationMs, (p, m) => {
      const breath = 0.55 * (1 - p) * (0.7 + Math.sin(p * Math.PI * 3) * 0.3)
      m.material.opacity = Math.max(0, breath)
      m.scale.setScalar(1 + p * 1.2)
    })
  }

  // ② warning_flash —— 风险事件的红色快闪
  function effectWarningFlash(scene, actor, durationMs) {
    const disc = new THREE.Mesh(
      new THREE.RingGeometry(0.85, 1.15, 40),
      new THREE.MeshBasicMaterial({ color: '#ff3a3a', transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }),
    )
    disc.rotation.x = -Math.PI / 2
    disc.position.copy(actor.position); disc.position.y = 0.08
    scene.add(disc)
    tweenAndRemove(scene, disc, durationMs, (p, m) => {
      const flash = Math.abs(Math.sin(p * Math.PI * 3))    // 3 次脉冲
      m.material.opacity = 0.9 * flash * (1 - p * 0.7)
      m.scale.setScalar(1 + p * 0.4)
    })
  }

  // ③ scan_pulse —— 蓝色波纹向外扩（调查类）
  function effectScanPulse(scene, actor, durationMs) {
    for (let i = 0; i < 3; i++) {
      setTimeout(() => {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(0.6, 0.75, 40),
          new THREE.MeshBasicMaterial({ color: '#00d4ff', transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false }),
        )
        ring.rotation.x = -Math.PI / 2
        ring.position.copy(actor.position); ring.position.y = 0.06
        scene.add(ring)
        tweenAndRemove(scene, ring, durationMs * 0.7, (p, m) => {
          m.scale.setScalar(1 + p * 3.5)
          m.material.opacity = 0.85 * (1 - p)
        })
      }, i * 220)
    }
  }

  // ④ dialogue_highlight —— 角色头顶弹"!"对话泡泡（公开陈述）
  function effectDialoguePopup(scene, actor, durationMs) {
    const sprite = createBillboardText('！', '#ffd060', 1.6)
    sprite.position.set(0, 3.2, 0)
    actor.add(sprite)
    const start = performance.now()
    const step = now => {
      const p = Math.min(1, (now - start) / durationMs)
      const bounce = p < 0.3 ? p / 0.3 : 1
      sprite.position.y = 3.2 + bounce * 0.4
      sprite.material.opacity = p < 0.7 ? 1 : (1 - (p - 0.7) / 0.3)
      sprite.scale.setScalar(1.6 * (1 + bounce * 0.3))
      if (p < 1) requestAnimationFrame(step)
      else { actor.remove(sprite); sprite.material.map?.dispose(); sprite.material.dispose() }
    }
    requestAnimationFrame(step)
  }

  // ⑤ risk_wave —— 红色波纹从地面扩散 + 阴影脉冲
  function effectRiskWave(scene, actor, durationMs) {
    // 暗红地面阴影
    const shadow = new THREE.Mesh(
      new THREE.CircleGeometry(2.5, 40),
      new THREE.MeshBasicMaterial({ color: '#5a0000', transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }),
    )
    shadow.rotation.x = -Math.PI / 2
    shadow.position.copy(actor.position); shadow.position.y = 0.04
    scene.add(shadow)
    // 2 圈红波连发
    for (let i = 0; i < 2; i++) {
      setTimeout(() => {
        const wave = new THREE.Mesh(
          new THREE.RingGeometry(0.4, 0.55, 40),
          new THREE.MeshBasicMaterial({ color: '#ff0033', transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }),
        )
        wave.rotation.x = -Math.PI / 2
        wave.position.copy(actor.position); wave.position.y = 0.07
        scene.add(wave)
        tweenAndRemove(scene, wave, durationMs * 0.8, (p, m) => {
          m.scale.setScalar(1 + p * 4)
          m.material.opacity = 0.9 * (1 - p)
        })
      }, i * 350)
    }
    tweenAndRemove(scene, shadow, durationMs, (p, m) => {
      m.material.opacity = 0.5 * Math.sin(p * Math.PI)
    })
  }

  // ⑥ evidence_reveal —— 半透明文档从地下浮出（share_evidence / 证据生成）
  function effectEvidenceReveal(scene, actor, durationMs) {
    const doc = new THREE.Mesh(
      new THREE.PlaneGeometry(0.6, 0.8),
      new THREE.MeshBasicMaterial({ color: '#f5e9c8', transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }),
    )
    doc.position.copy(actor.position)
    doc.position.y = 0.5
    doc.position.x += 0.8
    scene.add(doc)
    tweenAndRemove(scene, doc, durationMs, (p, m) => {
      m.position.y = 0.5 + p * 1.4         // 上升
      m.material.opacity = p < 0.7 ? p / 0.7 : (1 - (p - 0.7) / 0.3)
      m.rotation.y = p * Math.PI * 0.3     // 微旋
    })
  }

  // ⑦ relation_line —— 两角色间连线，由场景效果声明触发。
  function effectRelationLine(scene, actor, targetGroup, durationMs) {
    if (!actor || !targetGroup) return effectGlow(scene, actor, durationMs)  // 没目标时退回 glow
    const pts = [
      new THREE.Vector3(actor.position.x, 1.3, actor.position.z),
      new THREE.Vector3(targetGroup.position.x, 1.3, targetGroup.position.z),
    ]
    const geo = new THREE.BufferGeometry().setFromPoints(pts)
    const mat = new THREE.LineBasicMaterial({ color: '#ffd24a', transparent: true, opacity: 0.95 })
    const line = new THREE.Line(geo, mat)
    scene.add(line)
    tweenAndRemove(scene, line, durationMs, (p, m) => {
      m.material.opacity = Math.sin(p * Math.PI) * 0.95   // 出现→淡出
    })
  }

  // ⑧ final_flash —— 全屏白闪 + 慢速缩放（场景终局仪式）
  function effectFinalFlash(scene, durationMs) {
    // 用相机面前的大平面贴片模拟全屏闪
    const camera = getCamera()
    if (!camera) return
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(80, 50),
      new THREE.MeshBasicMaterial({ color: '#fff8e0', transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, depthTest: false }),
    )
    plane.userData.cameraIgnore = true
    camera.add(plane)
    plane.position.set(0, 0, -5)
    scene.add(camera)
    const start = performance.now()
    const step = now => {
      const p = Math.min(1, (now - start) / durationMs)
      plane.material.opacity = p < 0.3 ? p / 0.3 * 0.9 : 0.9 * (1 - (p - 0.3) / 0.7)
      if (p < 1) requestAnimationFrame(step)
      else { camera.remove(plane); plane.geometry.dispose(); plane.material.dispose() }
    }
    requestAnimationFrame(step)
  }

  // ⑨ neutral_pulse —— 灰色脉冲一次（中性 / 无效果）
  function effectNeutralPulse(scene, actor, durationMs) {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.7, 0.85, 40),
      new THREE.MeshBasicMaterial({ color: '#888', transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false }),
    )
    ring.rotation.x = -Math.PI / 2
    ring.position.copy(actor.position); ring.position.y = 0.06
    scene.add(ring)
    tweenAndRemove(scene, ring, durationMs * 0.6, (p, m) => {
      m.scale.setScalar(1 + p * 1.5)
      m.material.opacity = 0.6 * (1 - p)
    })
  }

  // 工具：在世界中创建一个带文字的 sprite（用 canvas 贴图）
  function createBillboardText(text, color = '#fff', size = 1) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 128
    const ctx = c.getContext('2d')
    ctx.fillStyle = color
    ctx.font = 'bold 96px sans-serif'
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(text, 64, 70)
    const tex = new THREE.CanvasTexture(c)
    tex.colorSpace = THREE.SRGBColorSpace
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 1, depthWrite: false })
    const sp = new THREE.Sprite(mat)
    sp.scale.setScalar(size)
    return sp
  }

  function vectorFrom(value) {
    if (!value) return null
    if (Array.isArray(value)) return new THREE.Vector3(value[0] || 0, value[1] || 0, value[2] || 0)
    return new THREE.Vector3(value.x || 0, value.y || 0, value.z || 0)
  }

  function dispose() {
    cameraTweenToken += 1
    clearDialogues()
    for (const item of objectPresentations.values()) {
      clearTimeout(item.timer)
      getScene()?.remove(item.object)
    }
    objectPresentations.clear()
  }

  function resetCamera() {
    lastCameraKey = ''
    applyCamera('camera_main', null, 900)
  }

  return {
    executeSegment,
    executeRenderCommand,
    update,
    resetCamera,
    dispose,
  }
}
