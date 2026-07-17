/**
 * 特效引擎 (P2 方案 B · B2)
 *
 * 提供：
 *   - 通用粒子与屏幕效果，由场景包把事件映射到效果键
 *   - 屏幕效果：camera shake、屏幕染色 tint、闪光
 *
 * 设计原则：
 *   - 全部用 Three.js 原生 Points/Sprite/PlaneGeometry 实现，**无需任何贴图资源**
 *   - 自带粒子池，限制同时存在粒子数防止 GC 抖动
 *   - 一次性效果跑完自动清理；持续效果按 duration 控制
 *
 * 使用：
 *   const fx = createEffectEngine({ getScene, getCamera, getAgentEntry })
 *   fx.trigger('success_chime', { actorId })
 *   fx.update(dt)                                  // 每帧调用
 */

import * as THREE from 'three'

const MAX_PARTICLE_SYSTEMS = 8

export function createEffectEngine({ getScene, getCamera, getAgentEntry, eventEffectsMap = {} }) {
  /** @type {Array<{update:(dt:number)=>boolean, dispose:()=>void}>} */
  const active = []
  // 屏幕震动状态
  let shakeAmp = 0          // 当前振幅 (uniform 单位)
  let shakeDecay = 0        // 每秒衰减比例
  // 屏幕染色 overlay（懒创建）
  let tintPlane = null
  let tintMaterial = null
  let tintTimer = 0
  let tintDuration = 0

  // ────────────────────────────────────────────────────────────────────
  // 粒子工厂
  // ────────────────────────────────────────────────────────────────────

  function makeGoldenRain({ duration = 2500 } = {}) {
    const scene = getScene()
    const count = 220
    const geometry = new THREE.BufferGeometry()
    const positions = new Float32Array(count * 3)
    const velocities = new Float32Array(count * 3)
    const spreadX = 30, spreadZ = 30
    for (let i = 0; i < count; i++) {
      positions[3 * i] = (Math.random() - 0.5) * spreadX
      positions[3 * i + 1] = 12 + Math.random() * 8           // 从天而降
      positions[3 * i + 2] = (Math.random() - 0.5) * spreadZ
      velocities[3 * i] = (Math.random() - 0.5) * 0.4
      velocities[3 * i + 1] = -1.5 - Math.random() * 1.5
      velocities[3 * i + 2] = (Math.random() - 0.5) * 0.4
    }
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    const material = new THREE.PointsMaterial({
      color: 0xffd66b,
      size: 0.22,
      transparent: true,
      opacity: 1,
      sizeAttenuation: true,
      depthWrite: false,
    })
    const points = new THREE.Points(geometry, material)
    scene.add(points)
    let elapsed = 0
    return {
      update(dt) {
        elapsed += dt * 1000
        const arr = geometry.attributes.position.array
        for (let i = 0; i < count; i++) {
          arr[3 * i] += velocities[3 * i] * dt
          arr[3 * i + 1] += velocities[3 * i + 1] * dt
          arr[3 * i + 2] += velocities[3 * i + 2] * dt
          if (arr[3 * i + 1] < -0.5) {
            arr[3 * i + 1] = 12 + Math.random() * 8
          }
        }
        geometry.attributes.position.needsUpdate = true
        // 淡出最后 600ms
        const remain = duration - elapsed
        if (remain < 600) material.opacity = Math.max(0, remain / 600)
        return elapsed < duration
      },
      dispose() {
        scene.remove(points)
        geometry.dispose()
        material.dispose()
      },
    }
  }

  function makeColumnOfLight({ position, color = 0xffe082, duration = 1400, radius = 0.9, height = 6 }) {
    const scene = getScene()
    // 金光柱：圆柱 mesh，材质用 additive blending
    const geometry = new THREE.CylinderGeometry(radius * 0.4, radius, height, 14, 1, true)
    const material = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.7,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.position.copy(position).add(new THREE.Vector3(0, height / 2, 0))
    scene.add(mesh)

    // 上扬的金粒子伴随
    const pcount = 80
    const pgeom = new THREE.BufferGeometry()
    const ppos = new Float32Array(pcount * 3)
    const pvel = new Float32Array(pcount * 3)
    for (let i = 0; i < pcount; i++) {
      const a = Math.random() * Math.PI * 2
      const r = Math.random() * radius
      ppos[3 * i] = position.x + Math.cos(a) * r
      ppos[3 * i + 1] = position.y + Math.random() * 0.5
      ppos[3 * i + 2] = position.z + Math.sin(a) * r
      pvel[3 * i] = 0
      pvel[3 * i + 1] = 3 + Math.random() * 2
      pvel[3 * i + 2] = 0
    }
    pgeom.setAttribute('position', new THREE.BufferAttribute(ppos, 3))
    const pmat = new THREE.PointsMaterial({
      color,
      size: 0.18,
      transparent: true,
      opacity: 1,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const points = new THREE.Points(pgeom, pmat)
    scene.add(points)

    let elapsed = 0
    return {
      update(dt) {
        elapsed += dt * 1000
        // 圆柱缩放扩张 + 淡出
        const k = elapsed / duration
        mesh.scale.set(1 + k * 0.4, 1, 1 + k * 0.4)
        material.opacity = 0.7 * (1 - k)
        // 粒子上飘 + 淡出
        const arr = pgeom.attributes.position.array
        for (let i = 0; i < pcount; i++) {
          arr[3 * i + 1] += pvel[3 * i + 1] * dt
        }
        pgeom.attributes.position.needsUpdate = true
        pmat.opacity = 1 - k
        return elapsed < duration
      },
      dispose() {
        scene.remove(mesh); geometry.dispose(); material.dispose()
        scene.remove(points); pgeom.dispose(); pmat.dispose()
      },
    }
  }

  function makeImpactShock({ position, color = 0xff5252, duration = 700, ringRadius = 3.5 }) {
    const scene = getScene()
    // 水平红色环面快速扩张
    const geometry = new THREE.RingGeometry(0.05, 0.12, 48)
    const material = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.rotation.x = -Math.PI / 2
    mesh.position.copy(position).add(new THREE.Vector3(0, 0.1, 0))
    scene.add(mesh)
    let elapsed = 0
    return {
      update(dt) {
        elapsed += dt * 1000
        const k = Math.min(1, elapsed / duration)
        mesh.scale.setScalar(k * ringRadius * 7) // 快速扩张
        material.opacity = 0.9 * (1 - k)
        return elapsed < duration
      },
      dispose() { scene.remove(mesh); geometry.dispose(); material.dispose() },
    }
  }

  function makeBrushSparkle({ position, color = 0xfff1a6, duration = 600 }) {
    const scene = getScene()
    const count = 40
    const geom = new THREE.BufferGeometry()
    const pos = new Float32Array(count * 3)
    const vel = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const a = Math.random() * Math.PI * 2
      const r = 0.4 + Math.random() * 0.3
      pos[3 * i] = position.x + Math.cos(a) * r
      pos[3 * i + 1] = position.y + 1.2 + Math.random() * 0.6
      pos[3 * i + 2] = position.z + Math.sin(a) * r
      vel[3 * i] = (Math.random() - 0.5) * 0.3
      vel[3 * i + 1] = -0.4 - Math.random() * 0.6
      vel[3 * i + 2] = (Math.random() - 0.5) * 0.3
    }
    geom.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    const mat = new THREE.PointsMaterial({
      color, size: 0.1, transparent: true, opacity: 1, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const points = new THREE.Points(geom, mat)
    scene.add(points)
    let elapsed = 0
    return {
      update(dt) {
        elapsed += dt * 1000
        const arr = geom.attributes.position.array
        for (let i = 0; i < count; i++) {
          arr[3 * i] += vel[3 * i] * dt
          arr[3 * i + 1] += vel[3 * i + 1] * dt
          arr[3 * i + 2] += vel[3 * i + 2] * dt
        }
        geom.attributes.position.needsUpdate = true
        mat.opacity = 1 - elapsed / duration
        return elapsed < duration
      },
      dispose() { scene.remove(points); geom.dispose(); mat.dispose() },
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // 屏幕染色 overlay
  // ────────────────────────────────────────────────────────────────────
  function ensureTintPlane() {
    if (tintPlane) return
    const camera = getCamera()
    if (!camera) return
    tintMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      depthTest: false,
    })
    const geo = new THREE.PlaneGeometry(2, 2)
    tintPlane = new THREE.Mesh(geo, tintMaterial)
    tintPlane.renderOrder = 9999
    // 直接挂到 camera 上，永远占满视野
    camera.add(tintPlane)
    tintPlane.position.set(0, 0, -0.5)
    tintPlane.frustumCulled = false
    // 如果场景里 camera 没被 add 到 scene（很多 demo 不会 add），强行 add 一次
    const scene = getScene()
    if (scene && camera.parent !== scene) scene.add(camera)
  }
  function flashTint(color = 0xffd66b, peakOpacity = 0.25, duration = 600) {
    ensureTintPlane()
    if (!tintMaterial) return
    tintMaterial.color.set(color)
    tintMaterial.opacity = peakOpacity
    tintTimer = duration
    tintDuration = duration
  }
  function updateTint(dt) {
    if (tintTimer > 0) {
      tintTimer -= dt * 1000
      if (tintMaterial) {
        const k = Math.max(0, tintTimer / tintDuration)
        // 前 1/3 保持高峰，后 2/3 平滑淡出
        tintMaterial.opacity = (k < 0.66 ? k / 0.66 : 1) * (tintMaterial.userData?.peak || tintMaterial.opacity)
        if (tintTimer <= 0) tintMaterial.opacity = 0
      }
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // Camera shake
  // ────────────────────────────────────────────────────────────────────
  function startShake(amplitude = 0.18, decayPerSec = 4) {
    shakeAmp = Math.max(shakeAmp, amplitude)
    shakeDecay = decayPerSec
  }
  function updateShake(dt) {
    if (shakeAmp <= 0.0001) { shakeAmp = 0; return }
    const camera = getCamera()
    if (!camera) return
    const a = shakeAmp
    camera.position.x += (Math.random() - 0.5) * a
    camera.position.y += (Math.random() - 0.5) * a
    shakeAmp = Math.max(0, shakeAmp - shakeDecay * dt * shakeAmp)
  }

  // ────────────────────────────────────────────────────────────────────
  // 触发 API
  // ────────────────────────────────────────────────────────────────────
  function push(fx) {
    if (active.length >= MAX_PARTICLE_SYSTEMS) {
      // 太多就丢最早
      const old = active.shift()
      try { old.dispose() } catch (e) {}
    }
    active.push(fx)
  }

  function getActorPosition(actorId) {
    if (!actorId) return null
    const entry = getAgentEntry?.(actorId)
    const group = entry?.group
    if (!group) return null
    return group.position.clone()
  }

  function trigger(effectKey, opts = {}) {
    switch (effectKey) {
      case 'challenge_descent': {
        push(makeGoldenRain({ duration: 2800 }))
        flashTint(0xffd66b, 0.18, 500)
        break
      }
      case 'success_chime': {
        const p = getActorPosition(opts.actorId)
        if (p) push(makeColumnOfLight({ position: p, color: 0xffe082, duration: 1400 }))
        else flashTint(0xa6f59c, 0.2, 500)
        break
      }
      case 'backlash_hit': {
        const p = getActorPosition(opts.actorId)
        if (p) push(makeImpactShock({ position: p, color: 0xff5252, duration: 700 }))
        startShake(0.22, 5)
        flashTint(0xff5252, 0.18, 400)
        break
      }
      case 'brush_sparkle': {
        const p = getActorPosition(opts.actorId)
        if (p) push(makeBrushSparkle({ position: p, color: 0xfff1a6, duration: 600 }))
        break
      }
      default:
        // 未知 effect 静默跳过
        break
    }
  }

  /** 事件派发：映射完全来自当前场景包。 */
  function dispatchEvent(eventType, meta = {}) {
    if (!eventType) return
    const configured = eventEffectsMap[eventType]
    const effectKey = typeof configured === 'string'
      ? configured
      : (meta.passed ? configured?.passed : configured?.failed) || configured?.effect
    if (effectKey) trigger(effectKey, { ...meta, ...(configured?.options || {}) })
  }

  // ────────────────────────────────────────────────────────────────────
  // 每帧 update（由 Renderer.animate() 调用）
  // ────────────────────────────────────────────────────────────────────
  function update(dt) {
    for (let i = active.length - 1; i >= 0; i--) {
      const alive = active[i].update(dt)
      if (!alive) {
        try { active[i].dispose() } catch (e) {}
        active.splice(i, 1)
      }
    }
    updateShake(dt)
    updateTint(dt)
  }

  function dispose() {
    for (const fx of active) { try { fx.dispose() } catch (e) {} }
    active.length = 0
    if (tintPlane) {
      const scene = getScene()
      const camera = getCamera()
      camera?.remove(tintPlane)
      scene?.remove(tintPlane)
      tintPlane.geometry.dispose()
      tintMaterial.dispose()
      tintPlane = null
      tintMaterial = null
    }
  }

  return { trigger, dispatchEvent, update, dispose, startShake, flashTint }
}
