<script setup>
/**
 * 粒子视差背景动画
 *
 * 改编自 particleground（作者 Jonathan Nicol，CodePen "3D Background particles"
 * https://codepen.io/Cluster0ne/pen/VeEXoj）
 *
 * 与原版相比的改动：
 *  - 移除 jQuery 依赖与 requestAnimationFrame polyfill（现代浏览器原生支持）
 *  - 改写为 Vue 3 Composition API + 原生 Canvas，组件卸载时清理监听与 rAF
 *  - 颜色从设计令牌读取：shadow app 用 Academic Ink 的 --ink-500/--ink-700，
 *    legacy 页面回退到 --color-primary；浅底场景用深色粒子（原版是深底白点）
 *  - 支持 devicePixelRatio 高清屏渲染
 *  - 尊重 prefers-reduced-motion：开启时不启动视差与动画，仅静态铺一层
 *  - pointer-events: none，不阻挡上层交互
 *
 * 核心机制（保持原版）：
 *  - 粒子恒定速度漂移，触边反弹（direction: 'center'）
 *  - 邻近粒子（< proximity px）自动连线，形成动态网络
 *  - 鼠标视差：粒子按 layer(1-3) 分层，鼠标移动时不同层位移不同，产生 3D 感
 */
import { onMounted, onUnmounted, ref } from 'vue'

const canvasRef = ref(null)
let canvas = null
let ctx = null
let particles = []
let rafId = null
let resizeObserver = null
let themeObserver = null
let prefersReducedMotion = false

// 画布尺寸（CSS 像素，非 backing store）
let elWidth = 0
let elHeight = 0
let dpr = 1

// 鼠标位置（视差用）
let mouseX = 0
let mouseY = 0
let winW = 0
let winH = 0
let desktop = true
let orientationSupport = false
let tiltX = 0
let tiltY = 0
let pointerX = 0
let pointerY = 0

// ════════════════════════════════════════════════════════════════
// 外观参数：粒子颜色与粗细 —— 需要调整时只改这里
// ════════════════════════════════════════════════════════════════

// 颜色是否跟随主题令牌自动取色：
//   true  → 使用 CSS 变量（TOKEN_*）中的颜色，随亮/暗主题切换
//   false → 使用下方 FIXED_* 固定颜色，不随主题变化
const USE_THEME_TOKENS = true

// 主题取色令牌（仅 USE_THEME_TOKENS = true 时生效）
const TOKEN_DOT = '--ink-500' // 粒子点：优先；找不到时回退 --color-focus → --color-primary
const TOKEN_LINE = '--ink-700' // 连线：优先；找不到时回退 --color-brand → --color-primary

// 固定颜色（仅 USE_THEME_TOKENS = false 时生效）
const FIXED_DOT_RGB = { r: 53, g: 92, b: 125 } // 粒子点 RGB（0~255）
const FIXED_LINE_RGB = { r: 53, g: 92, b: 125 } // 邻近粒子连线 RGB（0~255）

// 透明度（0~1，越大越明显）
const DOT_ALPHA = 0.25 // 粒子点
const LINE_ALPHA = 0.2 // 连线

// 粗细（px）
const PARTICLE_RADIUS = 4 // 粒子点半径；实际绘制圆点半径 = 该值 / 2
const LINE_WIDTH = 1 // 连线的线宽

// ── 配置（参照 particleground 原文件默认值，密度与速度略调低）──
// 原文件：density 10000 / maxSpeed 0.7 / proximity 100 / minSpeed 0.1
const options = {
  minSpeedX: 0.05,
  maxSpeedX: 0.35,
  minSpeedY: 0.05,
  maxSpeedY: 0.35,
  directionX: 'center', // 'center' 触边反弹 | 'left' | 'right'
  directionY: 'center',
  density: 16000, // 每 n 像素生成 1 个粒子（值越大越稀疏；原文件 10000）
  // 颜色与粗细见上方「外观参数」；此处为初始兜底，实际由 refreshColors() 覆盖
  dotColor: `rgba(${FIXED_DOT_RGB.r}, ${FIXED_DOT_RGB.g}, ${FIXED_DOT_RGB.b}, 0.25)`,
  lineColor: `rgba(${FIXED_LINE_RGB.r}, ${FIXED_LINE_RGB.g}, ${FIXED_LINE_RGB.b}, 0.15)`,
  particleRadius: PARTICLE_RADIUS,
  lineWidth: LINE_WIDTH,
  curvedLines: false,
  proximity: 100, // 两点间距小于此值则连线（原文件值）
  parallax: true,
  parallaxMultiplier: 5, // 越小视差越剧烈
}

// ── 主题色读取 ──
function readToken(name) {
  const el = canvas || document.documentElement
  const v = getComputedStyle(el).getPropertyValue(name)
  return (v || '').trim()
}

function hexToRgb(hex) {
  if (!hex) return null
  let h = hex.replace('#', '').trim()
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  if (h.length !== 6) return null
  const num = parseInt(h, 16)
  if (Number.isNaN(num)) return null
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 }
}

function parseColor(raw) {
  if (!raw) return null
  const s = raw.trim()
  const hex = hexToRgb(s)
  if (hex) return hex
  const m = s.match(/rgba?\(([^)]+)\)/i)
  if (m) {
    const parts = m[1].split(',').map((p) => p.trim())
    return {
      r: parseInt(parts[0], 10) || 0,
      g: parseInt(parts[1], 10) || 0,
      b: parseInt(parts[2], 10) || 0,
    }
  }
  return null
}

function refreshColors() {
  // 颜色来源：默认跟随主题令牌（USE_THEME_TOKENS = true，见上方「外观参数」）；
  // 关掉后改用 FIXED_* 固定颜色。浅底用深色粒子 + 半透明，保证可见又不抢眼。
  let dot, line
  if (USE_THEME_TOKENS) {
    // shadow app（.sfx 作用域）优先用 Academic Ink 墨色令牌；
    // legacy 页面回退到 :root 的 --color-primary。
    dot =
      parseColor(readToken(TOKEN_DOT)) ||
      parseColor(readToken('--color-focus')) ||
      parseColor(readToken('--color-primary')) ||
      FIXED_DOT_RGB
    line =
      parseColor(readToken(TOKEN_LINE)) ||
      parseColor(readToken('--color-brand')) ||
      parseColor(readToken('--color-primary')) ||
      dot
  } else {
    dot = FIXED_DOT_RGB
    line = FIXED_LINE_RGB
  }
  options.dotColor = `rgba(${dot.r}, ${dot.g}, ${dot.b}, ${DOT_ALPHA})`
  options.lineColor = `rgba(${line.r}, ${line.g}, ${line.b}, ${LINE_ALPHA})`
  if (ctx) {
    ctx.fillStyle = options.dotColor
    ctx.strokeStyle = options.lineColor
    ctx.lineWidth = options.lineWidth
  }
}

// ── Particle ──
function createParticle() {
  const p = {
    stackPos: 0,
    active: true,
    layer: Math.ceil(Math.random() * 3), // 1/2/3，视差深度
    parallaxOffsetX: 0,
    parallaxOffsetY: 0,
    parallaxTargX: 0,
    parallaxTargY: 0,
    position: {
      x: Math.ceil(Math.random() * elWidth),
      y: Math.ceil(Math.random() * elHeight),
    },
    speed: { x: 0, y: 0 },
  }

  // X 方向速度
  switch (options.directionX) {
    case 'left':
      p.speed.x = +(-options.maxSpeedX + Math.random() * options.maxSpeedX - options.minSpeedX).toFixed(2)
      break
    case 'right':
      p.speed.x = +(Math.random() * options.maxSpeedX + options.minSpeedX).toFixed(2)
      break
    default: // center
      p.speed.x = +(-options.maxSpeedX / 2 + Math.random() * options.maxSpeedX).toFixed(2)
      p.speed.x += p.speed.x > 0 ? options.minSpeedX : -options.minSpeedX
  }
  // Y 方向速度
  switch (options.directionY) {
    case 'up':
      p.speed.y = +(-options.maxSpeedY + Math.random() * options.maxSpeedY - options.minSpeedY).toFixed(2)
      break
    case 'down':
      p.speed.y = +(Math.random() * options.maxSpeedY + options.minSpeedY).toFixed(2)
      break
    default:
      p.speed.y = +(-options.maxSpeedY / 2 + Math.random() * options.maxSpeedY).toFixed(2)
      p.speed.y += p.speed.y > 0 ? options.minSpeedY : -options.minSpeedY
  }
  return p
}

function updatePosition(p) {
  if (options.parallax) {
    if (orientationSupport && !desktop) {
      const ratioX = winW / 60
      pointerX = (tiltX + 30) * ratioX
      const ratioY = winH / 60
      pointerY = (tiltY + 30) * ratioY
    } else {
      pointerX = mouseX
      pointerY = mouseY
    }
    p.parallaxTargX = (pointerX - winW / 2) / (options.parallaxMultiplier * p.layer)
    p.parallaxOffsetX += (p.parallaxTargX - p.parallaxOffsetX) / 10
    p.parallaxTargY = (pointerY - winH / 2) / (options.parallaxMultiplier * p.layer)
    p.parallaxOffsetY += (p.parallaxTargY - p.parallaxOffsetY) / 10
  }

  const x = p.position.x + p.speed.x + p.parallaxOffsetX
  const y = p.position.y + p.speed.y + p.parallaxOffsetY

  switch (options.directionX) {
    case 'left':
      if (x < 0) p.position.x = elWidth - p.parallaxOffsetX
      else p.position.x += p.speed.x
      break
    case 'right':
      if (x > elWidth) p.position.x = -p.parallaxOffsetX
      else p.position.x += p.speed.x
      break
    default:
      if (x > elWidth || x < 0) p.speed.x = -p.speed.x
      p.position.x += p.speed.x
  }

  switch (options.directionY) {
    case 'up':
      if (y < 0) p.position.y = elHeight - p.parallaxOffsetY
      else p.position.y += p.speed.y
      break
    case 'down':
      if (y > elHeight) p.position.y = -p.parallaxOffsetY
      else p.position.y += p.speed.y
      break
    default:
      if (y > elHeight || y < 0) p.speed.y = -p.speed.y
      p.position.y += p.speed.y
  }
}

function drawParticle(p) {
  const px = p.position.x + p.parallaxOffsetX
  const py = p.position.y + p.parallaxOffsetY

  // 画点
  ctx.beginPath()
  ctx.arc(px, py, Math.max(0.5, options.particleRadius / 2), 0, Math.PI * 2, true)
  ctx.closePath()
  ctx.fill()

  // 画到栈中更高位置粒子的连线（邻近才连）
  ctx.beginPath()
  for (let i = particles.length - 1; i > p.stackPos; i--) {
    const p2 = particles[i]
    if (!p2) continue
    const a = px - (p2.position.x + p2.parallaxOffsetX)
    const b = py - (p2.position.y + p2.parallaxOffsetY)
    const dist = Math.sqrt(a * a + b * b)
    if (dist < options.proximity) {
      ctx.moveTo(px, py)
      if (options.curvedLines) {
        ctx.quadraticCurveTo(
          Math.max(p2.position.x, p2.position.x),
          Math.min(p2.position.y, p2.position.y),
          p2.position.x + p2.parallaxOffsetX,
          p2.position.y + p2.parallaxOffsetY
        )
      } else {
        ctx.lineTo(p2.position.x + p2.parallaxOffsetX, p2.position.y + p2.parallaxOffsetY)
      }
    }
  }
  ctx.stroke()
  ctx.closePath()
}

// ── Canvas 尺寸与样式 ──
function styleCanvas() {
  if (!canvas || !canvas.parentElement) return
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  const rect = canvas.parentElement.getBoundingClientRect()
  elWidth = Math.max(1, Math.floor(rect.width))
  elHeight = Math.max(1, Math.floor(rect.height))
  canvas.width = Math.floor(elWidth * dpr)
  canvas.height = Math.floor(elHeight * dpr)
  canvas.style.width = elWidth + 'px'
  canvas.style.height = elHeight + 'px'
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = options.dotColor
  ctx.strokeStyle = options.lineColor
  ctx.lineWidth = options.lineWidth
}

function createParticles() {
  particles = []
  const num = Math.round((elWidth * elHeight) / options.density)
  for (let i = 0; i < num; i++) {
    const p = createParticle()
    p.stackPos = i
    particles.push(p)
  }
}

// ── 主循环 ──
function draw() {
  winW = window.innerWidth
  winH = window.innerHeight
  ctx.clearRect(0, 0, elWidth, elHeight)
  for (const p of particles) updatePosition(p)
  for (const p of particles) drawParticle(p)
  rafId = requestAnimationFrame(draw)
}

// ── 事件 ──
function onMouseMove(e) {
  mouseX = e.pageX
  mouseY = e.pageY
}

function onDeviceOrientation(e) {
  tiltY = Math.min(Math.max(-e.beta, -30), 30)
  tiltX = Math.min(Math.max(-e.gamma, -30), 30)
}

function onResize() {
  styleCanvas()
  const num = Math.round((elWidth * elHeight) / options.density)
  // 移除超出边界的粒子
  for (let i = particles.length - 1; i >= 0; i--) {
    if (particles[i].position.x > elWidth || particles[i].position.y > elHeight) {
      particles.splice(i, 1)
    }
  }
  // 补足或裁剪
  if (num > particles.length) {
    while (num > particles.length) particles.push(createParticle())
  } else if (num < particles.length) {
    particles.splice(num)
  }
  for (let i = particles.length - 1; i >= 0; i--) particles[i].stackPos = i
}

function addListeners() {
  if (!('ontouchstart' in window)) {
    window.addEventListener('mousemove', onMouseMove)
  }
  window.addEventListener('resize', onResize)
  if (orientationSupport && !desktop) {
    window.addEventListener('deviceorientation', onDeviceOrientation, true)
  }
  if (typeof ResizeObserver !== 'undefined' && canvas?.parentElement) {
    resizeObserver = new ResizeObserver(onResize)
    resizeObserver.observe(canvas.parentElement)
  }
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(refreshColors)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
  }
}

function removeListeners() {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('deviceorientation', onDeviceOrientation, true)
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (themeObserver) {
    themeObserver.disconnect()
    themeObserver = null
  }
}

onMounted(() => {
  canvas = canvasRef.value
  if (!canvas) return
  ctx = canvas.getContext('2d')
  desktop = !navigator.userAgent.match(/(iPhone|iPod|iPad|Android|BlackBerry|BB10|mobi|tablet|opera mini|nexus 7)/i)
  orientationSupport = typeof window.DeviceOrientationEvent !== 'undefined'
  prefersReducedMotion =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  refreshColors()
  styleCanvas()
  createParticles()

  if (prefersReducedMotion) {
    // 减少动画偏好：只渲染一帧静态粒子网络，不启动 rAF 与视差
    ctx.clearRect(0, 0, elWidth, elHeight)
    for (const p of particles) drawParticle(p)
    return
  }

  addListeners()
  draw()
})

onUnmounted(() => {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  removeListeners()
  particles = []
})
</script>

<template>
  <canvas ref="canvasRef" class="particle-bg" aria-hidden="true"></canvas>
</template>

<style scoped>
.particle-bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none;
  display: block;
}
</style>
