import { Application, Assets, Container, Graphics, Sprite } from 'pixi.js'

const MOUTH_KEYS = ['sil', 'a', 'e', 'i', 'o', 'u', 'fv', 'mbp']

const expressionTint = {
  neutral: 0xFFFFFF,
  warm: 0xFFF5EE,
  attentive: 0xF5FAFF,
}

/**
 * The renderer owns pixels only.  It never creates a playback timer: callers
 * set a frame derived from HTMLAudioElement time, which keeps PixiJS from
 * becoming a competing clock.
 */
export class Sprite2DRenderer {
  constructor({ container, quality = 'auto', onMetrics = () => {} }) {
    this.container = container
    this.quality = quality
    this.onMetrics = onMetrics
    this.app = null
    this.root = null
    this.eyes = null
    this.head = null
    this.portraitBody = null
    this.leftArm = null
    this.rightArm = null
    this.mouths = new Map()
    this.currentMouth = null
    this.manifest = null
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
    const textures = await Promise.all(entries.map(async ([key, url]) => [key, await Assets.load(url)]))
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
      this.portraitBody = this.#sprite(textures.get('body'), layout)
      this.eyes = this.#sprite(textures.get('eyes'), layout.eyes)
      this.eyes.visible = false
      root.addChild(this.portraitBody, this.eyes)

      for (const key of MOUTH_KEYS) {
        const mouth = this.#sprite(textures.get(`mouth:${key}`), layout.mouth)
        mouth.visible = key === 'sil'
        root.addChild(mouth)
        this.mouths.set(key, mouth)
      }
      this.currentMouth = this.mouths.get('sil')
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
      root.addChild(mouth)
      this.mouths.set(key, mouth)
    }
    this.currentMouth = this.mouths.get('sil')
  }

  #layout() {
    if (!this.app || !this.root || !this.manifest) return
    const stage = this.manifest.stage
    const scale = Math.max(0.1, Math.min(this.app.renderer.width / stage.width, this.app.renderer.height / stage.height))
    this.root.scale.set(scale)
    this.root.position.set(
      (this.app.renderer.width - stage.width * scale) / 2,
      Math.max(0, (this.app.renderer.height - stage.height * scale) / 2),
    )
  }

  setFrame({ viseme = 'sil', speaking = false, precision = 'none', timeMs = 0 }) {
    if (!this.app) return
    this.#layout()
    const safeViseme = MOUTH_KEYS.includes(viseme) ? viseme : (speaking ? 'a' : 'sil')
    if (this.currentMouth !== this.mouths.get(safeViseme)) {
      this.currentMouth.visible = false
      this.currentMouth = this.mouths.get(safeViseme)
      this.currentMouth.visible = true
    }

    // Decorative motion is a deterministic function of audio time, not wall time.
    const seconds = Math.max(0, Number(timeMs) || 0) / 1000
    const blinkCycle = seconds % 4.6
    const blink = blinkCycle > 4.25 && blinkCycle < 4.42
    if (this.manifest.renderMode === 'portrait_patch_v1') {
      // The closed-eye patch is part of the same fictional portrait package;
      // it is selected from audio time rather than from a wall-clock timer.
      this.eyes.visible = blink
      return
    }

    this.eyes.scale.y = blink ? 0.12 : 1
    const expression = speaking ? (precision === 'phoneme' ? 'attentive' : 'warm') : 'neutral'
    this.head.tint = expressionTint[expression]
    this.eyes.tint = expressionTint[expression]
    const gesture = speaking && Math.floor(seconds / 2.4) % 2 === 1 ? 'emphasis' : 'rest'
    const sway = gesture === 'emphasis' ? Math.sin(seconds * 8) * 0.22 : 0
    this.leftArm.rotation = -0.2 + sway
    this.rightArm.rotation = 0.2 - sway
  }

  destroy() {
    if (!this.app) return
    this.app.destroy({ removeView: true }, { children: true })
    this.app = null
    this.root = null
    this.portraitBody = null
    this.mouths.clear()
    this.currentMouth = null
    this.container?.replaceChildren()
  }
}
