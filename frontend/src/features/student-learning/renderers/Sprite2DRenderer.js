import { Application, Assets, Container, Graphics, Sprite } from 'pixi.js'

const MOUTH_KEYS = ['sil', 'a', 'e', 'i', 'o', 'u', 'fv', 'mbp']

const expressionTint = {
  neutral: 0xFFFFFF,
  warm: 0xFFF5EE,
  attentive: 0xF5FAFF,
}

const MOUTH_OPENNESS = {
  sil: 0.0,
  fv: 0.05,
  mbp: 0.02,
  e: 0.35,
  i: 0.25,
  u: 0.2,
  o: 0.5,
  a: 1.0,
}

// 自然口型不对称：张口（起音）更快、合口（收尾）更慢，避免机械抖动
const MOUTH_ATTACK_MS = 32
const MOUTH_RELEASE_MS = 68
const RAPID_TRANSITION_MS = 22
const MIN_VISEME_HOLD_MS = 40

export const spriteTextureAsset = url => ({ src: url, parser: 'loadTextures' })

export class Sprite2DRenderer {
  constructor({ container, quality = 'auto', onMetrics = () => {} }) {
    this.container = container
    this.quality = quality
    this.onMetrics = onMetrics
    this.app = null
    this.root = null
    this.head = null
    this.portraitBody = null
    this.mouths = new Map()
    this.currentViseme = 'sil'
    this.targetViseme = 'sil'
    this.transitionStartMs = 0
    this.transitionDurationMs = MOUTH_ATTACK_MS
    this.lastSetFrameMs = 0
    this.manifest = null
    this._lastViewport = { width: 0, height: 0 }
    this._ready = false
  }

  async init(manifest) {
    if (!this.container) throw new Error('SPRITE2D_CONTAINER_MISSING')
    const startedAt = performance.now()
    this.manifest = manifest
    const app = new Application()
    await app.init({
      resizeTo: this.container,
      backgroundAlpha: 0,
      antialias: this.quality !== 'low_resource',
      autoDensity: true,
      resolution: this.quality === 'low_resource' ? 1 : Math.min(window.devicePixelRatio || 1, 2),
      preference: 'webgl',
      powerPreference: this.quality === 'low_resource' ? 'low-power' : 'high-performance',
    })
    app.canvas.className = 'sprite2d-canvas'
    app.canvas.setAttribute('aria-hidden', 'true')
    this.container.replaceChildren(app.canvas)
    this.app = app

    const textures = await this.#loadTextures(manifest)
    this.#createStage(textures)
    // 舞台构建完成前 setFrame 一律 no-op：init 期间（app 已创建、贴图仍在加载）
    // currentTime 变化会触发 updateFrame，此时 eyes/mouths 尚未创建，直接访问会抛
    // "Cannot set properties of undefined"。
    this._ready = true
    this.#layout()
    this.setFrame({ viseme: 'sil', speaking: false, precision: 'none', timeMs: 0 })
    this.onMetrics({ initMs: Math.round(performance.now() - startedAt), quality: this.quality })
  }

  async #loadTextures(manifest) {
    const entries = [
      ['body', manifest.sprites.body],
      ['head', manifest.sprites.head],
      ['eyes', manifest.sprites.eyes],
      ...MOUTH_KEYS.map(key => [`mouth:${key}`, manifest.sprites.mouths[key]]),
    ]
    const textures = await Promise.all(entries.map(async ([key, url]) => [
      key,
      await Assets.load(spriteTextureAsset(url)),
    ]))
    return new Map(textures)
  }

  #sprite(texture, { x, y, width, height, anchorX = 0.5, anchorY = 0.5 }) {
    const sprite = Sprite.from(texture)
    sprite.anchor.set(anchorX, anchorY)
    sprite.position.set(x, y)
    sprite.width = width
    sprite.height = height
    return sprite
  }

  #createArm(x, y, mirrored = false) {
    const arm = new Graphics()
      .roundRect(-18, 0, 36, 130, 18)
      .fill({ color: 0x203A5F })
    arm.position.set(x, y)
    arm.pivot.set(0, 12)
    arm.scale.x = mirrored ? -1 : 1
    return arm
  }

  #createStage(textures) {
    const root = new Container()
    this.root = root
    this.app.stage.addChild(root)

    if (this.manifest.renderMode === 'portrait_patch_v1') {
      const layout = this.manifest.layout
      this.portraitBody = this.#sprite(textures.get('body'), layout.body)
      this.eyes = this.#sprite(textures.get('eyes'), layout.eyes)
      this.eyes.visible = false
      root.addChild(this.portraitBody, this.eyes)

      for (const key of MOUTH_KEYS) {
        const mouth = this.#sprite(textures.get(`mouth:${key}`), layout.mouth)
        mouth.visible = key === 'sil'
        mouth.alpha = key === 'sil' ? 1 : 0
        root.addChild(mouth)
        this.mouths.set(key, mouth)
      }
      this.currentViseme = 'sil'
      this.targetViseme = 'sil'
      return
    }

    this.leftArm = this.#createArm(150, 354)
    this.rightArm = this.#createArm(330, 354, true)
    root.addChild(this.leftArm, this.rightArm)

    root.addChild(this.#sprite(textures.get('body'), { x: 240, y: 482, width: 380, height: 316, anchorY: 1 }))
    this.head = this.#sprite(textures.get('head'), { x: 240, y: 210, width: 245, height: 310 })
    this.eyes = this.#sprite(textures.get('eyes'), { x: 240, y: 210, width: 245, height: 310 })
    root.addChild(this.head, this.eyes)

    for (const key of MOUTH_KEYS) {
      const mouth = this.#sprite(textures.get(`mouth:${key}`), { x: 240, y: 286, width: 74, height: 42 })
      mouth.visible = key === 'sil'
      mouth.alpha = key === 'sil' ? 1 : 0
      root.addChild(mouth)
      this.mouths.set(key, mouth)
    }
    this.currentViseme = 'sil'
    this.targetViseme = 'sil'
  }

  #layout() {
    if (!this.app || !this.root || !this.manifest) return
    const width = this.app.renderer.width
    const height = this.app.renderer.height
    if (width === this._lastViewport.width && height === this._lastViewport.height) return
    this._lastViewport = { width, height }
    const stage = this.manifest.stage
    const scale = Math.max(0.1, Math.max(width / stage.width, height / stage.height))
    this.root.scale.set(scale)
    this.root.position.set(
      (width - stage.width * scale) / 2,
      (height - stage.height * scale) / 2,
    )
  }

  setFrame({ viseme = 'sil', speaking = false, precision = 'none', timeMs = 0 }) {
    if (!this.app || !this._ready) return
    this.#layout()

    const nextViseme = MOUTH_KEYS.includes(viseme) ? viseme : (speaking ? 'a' : 'sil')
    const nowMs = timeMs
    if (nextViseme !== this.targetViseme) {
      const sinceLast = nowMs - this.lastSetFrameMs
      // 依据口型开合方向选过渡时长：张口快（起音干脆）、合口慢（收尾自然）
      const opening = (MOUTH_OPENNESS[nextViseme] ?? 0) > (MOUTH_OPENNESS[this.targetViseme] ?? 0)
      const baseDuration = opening ? MOUTH_ATTACK_MS : MOUTH_RELEASE_MS
      const duration = sinceLast > 0 && sinceLast < MIN_VISEME_HOLD_MS
        ? Math.min(RAPID_TRANSITION_MS, baseDuration)
        : baseDuration
      this.currentViseme = this.#snapshotVisemeAt(nowMs)
      this.targetViseme = nextViseme
      this.transitionStartMs = nowMs
      this.transitionDurationMs = duration
    }
    this.lastSetFrameMs = nowMs

    this.#applyMouthBlend(nowMs)
    this.#applyExpression(nowMs, speaking, precision)
  }

  #snapshotVisemeAt(nowMs) {
    const progress = Math.min(1, Math.max(0, (nowMs - this.transitionStartMs) / this.transitionDurationMs))
    const easeProgress = 1 - Math.pow(1 - progress, 3)
    if (easeProgress >= 0.99) return this.targetViseme
    const fromOpen = MOUTH_OPENNESS[this.currentViseme] ?? 0
    const toOpen = MOUTH_OPENNESS[this.targetViseme] ?? 0
    const currentOpen = fromOpen + (toOpen - fromOpen) * easeProgress
    let closest = this.currentViseme
    let closestDist = Infinity
    for (const key of MOUTH_KEYS) {
      const dist = Math.abs((MOUTH_OPENNESS[key] ?? 0) - currentOpen)
      if (dist < closestDist) { closestDist = dist; closest = key }
    }
    return closest
  }

  #applyMouthBlend(nowMs) {
    const progress = Math.min(1, Math.max(0, (nowMs - this.transitionStartMs) / this.transitionDurationMs))
    const easeProgress = progress < 0.5
      ? 2 * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 2) / 2

    const fromSprite = this.mouths.get(this.currentViseme)
    const toSprite = this.mouths.get(this.targetViseme)

    for (const [key, mouth] of this.mouths) {
      if (key === this.currentViseme || key === this.targetViseme) continue
      if (mouth.visible) { mouth.visible = false; mouth.alpha = 0 }
    }

    if (fromSprite && toSprite && fromSprite !== toSprite) {
      fromSprite.visible = true
      toSprite.visible = true
      fromSprite.alpha = 1 - easeProgress
      toSprite.alpha = easeProgress
    } else if (toSprite) {
      toSprite.visible = true
      toSprite.alpha = 1
      if (fromSprite && fromSprite !== toSprite) {
        fromSprite.visible = false
        fromSprite.alpha = 0
      }
    }
  }

  #applyExpression(timeMs, speaking, precision) {
    const seconds = Math.max(0, Number(timeMs) || 0) / 1000

    const blinkCycle = seconds % 4.2
    const blinkPhase = blinkCycle - 3.95
    let eyeScale = 1
    if (blinkPhase >= 0 && blinkPhase < 0.2) {
      const t = blinkPhase / 0.2
      eyeScale = t < 0.5
        ? 1 - Math.sin(t * Math.PI)
        : Math.sin((t - 0.5) * Math.PI)
    }
    if (this.manifest.renderMode === 'portrait_patch_v1') {
      this.eyes.visible = eyeScale < 0.5
    } else {
      this.eyes.scale.y = Math.max(0.05, eyeScale)
    }

    const breathY = Math.sin(seconds * 0.85) * 0.6 + Math.sin(seconds * 1.7 + 0.4) * 0.25
    const sway = Math.sin(seconds * 0.5) * 0.006

    if (this.manifest.renderMode === 'portrait_patch_v1') {
      if (this.portraitBody) {
        this.portraitBody.y = (this.manifest.layout?.body?.y ?? 240) + breathY
      }
      if (this.eyes) {
        this.eyes.y = (this.manifest.layout?.eyes?.y ?? 210) + breathY
      }
      for (const mouth of this.mouths.values()) {
        mouth.y = (this.manifest.layout?.mouth?.y ?? 286) + breathY
      }
      if (this.portraitBody) this.portraitBody.rotation = sway
      if (this.eyes) this.eyes.rotation = sway
      for (const mouth of this.mouths.values()) { mouth.rotation = sway }
      return
    }

    if (this.head) {
      // 呼吸起伏 + 说话时的轻点头（周期 ~1.1s，仅向上脉冲，幅度小）
      const nod = speaking ? Math.max(0, Math.sin(seconds * 1.15 + 0.4)) * 1.4 : 0
      this.head.y = 210 + breathY + nod
      // 视线缓慢巡视：双眼沿椭圆轨迹轻微偏移，不跳帧
      const gazeX = Math.sin(seconds * 0.31 + 0.8) * 4.5
      const gazeY = Math.cos(seconds * 0.23 + 1.2) * 2.5
      if (this.eyes) {
        this.eyes.y = this.head.y + gazeY
        this.eyes.x = 240 + gazeX
      }
    }
    if (this.head) this.head.rotation = sway
    if (this.eyes && this.eyes !== this.head) this.eyes.rotation = sway

    // 表情 tint 逐帧插值：状态切换不再瞬间跳变，过渡更柔和
    const targetExpression = speaking ? (precision === 'phoneme' ? 'attentive' : 'warm') : 'neutral'
    const targetTint = expressionTint[targetExpression]
    this.#lerpTint(this.head, targetTint)
    this.#lerpTint(this.eyes, targetTint)
    const gesture = speaking && Math.floor(seconds / 2.4) % 2 === 1 ? 'emphasis' : 'rest'
    const armSway = gesture === 'emphasis' ? Math.sin(seconds * 8) * 0.22 : 0
    if (this.leftArm) this.leftArm.rotation = -0.2 + armSway
    if (this.rightArm) this.rightArm.rotation = 0.2 - armSway
  }

  #lerpTint(sprite, targetColor, factor = 0.25) {
    if (!sprite) return
    const current = sprite.tint ?? 0xFFFFFF
    const cr = (current >> 16) & 0xFF
    const cg = (current >> 8) & 0xFF
    const cb = current & 0xFF
    const tr = (targetColor >> 16) & 0xFF
    const tg = (targetColor >> 8) & 0xFF
    const tb = targetColor & 0xFF
    const r = Math.round(cr + (tr - cr) * factor)
    const g = Math.round(cg + (tg - cg) * factor)
    const b = Math.round(cb + (tb - cb) * factor)
    sprite.tint = (r << 16) | (g << 8) | b
  }

  destroy() {
    if (!this.app) return
    this.app.destroy({ removeView: true }, { children: true })
    this.app = null
    this._ready = false
    this.root = null
    this.portraitBody = null
    this.head = null
    this.eyes = null
    this.mouths.clear()
    this.currentViseme = 'sil'
    this.targetViseme = 'sil'
    this.container?.replaceChildren()
  }
}
