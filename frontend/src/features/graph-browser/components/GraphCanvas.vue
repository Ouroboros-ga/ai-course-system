<template>
  <div ref="wrap" class="gb-canvas-wrap" @wheel.prevent="onWheel">
    <canvas
      ref="canvas"
      class="gb-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseUp"
      @click="onClick"
    />
    <div class="gb-canvas-legend">
      <span class="lg lg-course"><i />课程</span>
      <span class="lg lg-kp"><i />知识点</span>
      <span class="lg lg-ev"><i />证据</span>
      <span class="lg-hint">滚轮缩放 · 拖拽平移 · 点节点查看</span>
    </div>
  </div>
</template>

<script setup>
/**
 * Force-directed graph canvas (zero-dependency, canvas 2D).
 *
 * Renders ONLY the nodes/edges handed in via props (already contract-validated
 * and assembled from real endpoints by useGraphBrowser). No retrieval/graph
 * stages are fabricated here — this component is a pure renderer.
 */
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },   // [{id,kind,label,...}]
  edges: { type: Array, default: () => [] },   // [{source,target,kind}]
  selectedId: { type: String, default: null },
})
const emit = defineEmits(['select'])

const wrap = ref(null)
const canvas = ref(null)

// ---- layout / simulation state (plain, non-reactive for perf) ----
let sim = { nodes: [], edges: [] }
let running = false
let rafId = 0
let view = { x: 0, y: 0, k: 1 }
let drag = null       // {type:'pan'|'node', node?, startX,startY}
let hovered = null
let dpr = 1

const KIND_COLOR = {
  course: '#1769aa',
  chapter: '#4f46e5',
  knowledge_point: '#0d9488',
  ppt_slide: '#ea580c',
  script_node: '#64748b',
  evidence: '#a16207',
}
const KIND_R = { course: 22, chapter: 16, knowledge_point: 13, ppt_slide: 10, script_node: 8, evidence: 7 }

function nodeColor(n) { return KIND_COLOR[n.kind] || '#64748b' }
function nodeR(n) { return KIND_R[n.kind] || 9 }

function buildSim() {
  const byId = new Map()
  const simNodes = props.nodes.map((n) => {
    const prev = sim.nodes.find((p) => p.id === n.id)
    const s = {
      ref: n, id: n.id, kind: n.kind, label: n.label,
      x: prev ? prev.x : (Math.random() - 0.5) * 400,
      y: prev ? prev.y : (Math.random() - 0.5) * 300,
      vx: 0, vy: 0, fx: null, fy: null,
    }
    byId.set(n.id, s)
    return s
  })
  const simEdges = props.edges
    .map((e) => ({ source: byId.get(e.source), target: byId.get(e.target), kind: e.kind }))
    .filter((e) => e.source && e.target)
  sim = { nodes: simNodes, edges: simEdges }
  // warm up
  for (let i = 0; i < 120; i++) tick(0.5)
  fit()
  startLoop()
}

// physics parameters
const REPULSION = 2600
const SPRING_LEN = { contains: 90, has_evidence: 60 }
const SPRING_K = 0.02
const CENTER_K = 0.008
const DAMPING = 0.86

function tick(alpha = 1) {
  const ns = sim.nodes
  // repulsion (O(n^2); n is small for one course)
  for (let i = 0; i < ns.length; i++) {
    for (let j = i + 1; j < ns.length; j++) {
      const a = ns[i], b = ns[j]
      let dx = a.x - b.x, dy = a.y - b.y
      let d2 = dx * dx + dy * dy
      if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1 }
      const f = (REPULSION / d2) * alpha
      const dist = Math.sqrt(d2)
      const fx = (dx / dist) * f, fy = (dy / dist) * f
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy
    }
  }
  // springs
  for (const e of sim.edges) {
    const a = e.source, b = e.target
    const dx = b.x - a.x, dy = b.y - a.y
    const dist = Math.max(1, Math.hypot(dx, dy))
    const target = SPRING_LEN[e.kind] || 80
    const f = (dist - target) * SPRING_K * alpha
    const fx = (dx / dist) * f, fy = (dy / dist) * f
    a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy
  }
  // centering
  for (const n of ns) { n.vx -= n.x * CENTER_K * alpha; n.vy -= n.y * CENTER_K * alpha }
  // integrate
  for (const n of ns) {
    if (n.fx != null) { n.x = n.fx; n.vx = 0 }
    else { n.vx *= DAMPING; n.x += n.vx }
    if (n.fy != null) { n.y = n.fy; n.vy = 0 }
    else { n.vy *= DAMPING; n.y += n.vy }
  }
}

function startLoop() {
  if (running) return
  running = true
  let frames = 0
  const step = () => {
    tick(1)
    draw()
    frames++
    // settle: stop the loop after a while to save CPU; re-draws happen on interaction
    if (frames < 240 && running) rafId = requestAnimationFrame(step)
    else running = false
  }
  rafId = requestAnimationFrame(step)
}

function resize() {
  const el = wrap.value, cv = canvas.value
  if (!el || !cv) return
  dpr = window.devicePixelRatio || 1
  const w = el.clientWidth, h = el.clientHeight
  cv.width = w * dpr; cv.height = h * dpr
  cv.style.width = w + 'px'; cv.style.height = h + 'px'
  draw()
}

function toScreen(x, y) {
  const cv = canvas.value
  const w = cv ? cv.width / dpr : 0, h = cv ? cv.height / dpr : 0
  return [w / 2 + (x + view.x) * view.k, h / 2 + (y + view.y) * view.k]
}
function toWorld(sx, sy) {
  const cv = canvas.value
  const w = cv ? cv.width / dpr : 0, h = cv ? cv.height / dpr : 0
  return [(sx - w / 2) / view.k - view.x, (sy - h / 2) / view.k - view.y]
}

function fit() {
  if (!sim.nodes.length) return
  const xs = sim.nodes.map((n) => n.x), ys = sim.nodes.map((n) => n.y)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const el = wrap.value
  const w = el ? el.clientWidth : 600, h = el ? el.clientHeight : 400
  const gw = Math.max(1, maxX - minX), gh = Math.max(1, maxY - minY)
  view.k = Math.max(0.2, Math.min(2, Math.min(w / (gw + 160), h / (gh + 160))))
  view.x = -(minX + maxX) / 2
  view.y = -(minY + maxY) / 2
}

function draw() {
  const cv = canvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.save()
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, cv.width / dpr, cv.height / dpr)
  // edges
  for (const e of sim.edges) {
    const [x1, y1] = toScreen(e.source.x, e.source.y)
    const [x2, y2] = toScreen(e.target.x, e.target.y)
    ctx.beginPath()
    ctx.moveTo(x1, y1); ctx.lineTo(x2, y2)
    ctx.strokeStyle = e.kind === 'has_evidence' ? 'rgba(161,98,7,0.45)' : 'rgba(23,105,170,0.35)'
    ctx.lineWidth = e.kind === 'has_evidence' ? 1 : 1.4
    ctx.stroke()
  }
  // nodes
  for (const n of sim.nodes) {
    const [sx, sy] = toScreen(n.x, n.y)
    const r = nodeR(n) * Math.sqrt(view.k) + 2
    const isSel = props.selectedId === n.id
    const isHover = hovered === n.id
    ctx.beginPath()
    ctx.arc(sx, sy, r, 0, Math.PI * 2)
    ctx.fillStyle = nodeColor(n)
    ctx.globalAlpha = isSel || isHover ? 1 : 0.92
    ctx.fill()
    ctx.globalAlpha = 1
    if (isSel) {
      ctx.beginPath(); ctx.arc(sx, sy, r + 4, 0, Math.PI * 2)
      ctx.strokeStyle = '#1769aa'; ctx.lineWidth = 2; ctx.stroke()
    }
    // label for course + kp (skip evidence labels to reduce clutter)
    if (n.kind !== 'evidence') {
      ctx.font = `${Math.max(10, 11 * view.k)}px system-ui, sans-serif`
      ctx.fillStyle = '#1e293b'
      ctx.textAlign = 'center'
      const label = n.label.length > 14 ? n.label.slice(0, 13) + '…' : n.label
      ctx.fillText(label, sx, sy + r + 13)
    }
  }
  ctx.restore()
}

// ---- interaction ----
function pickNode(sx, sy) {
  const [wx, wy] = toWorld(sx, sy)
  let best = null, bestD = 1e9
  for (const n of sim.nodes) {
    const d = Math.hypot(n.x - wx, n.y - wy)
    if (d < nodeR(n) + 6 / view.k && d < bestD) { best = n; bestD = d }
  }
  return best
}

function onMouseDown(ev) {
  const rect = canvas.value.getBoundingClientRect()
  const sx = ev.clientX - rect.left, sy = ev.clientY - rect.top
  const n = pickNode(sx, sy)
  if (n) { drag = { type: 'node', node: n }; n.fx = n.x; n.fy = n.y }
  else drag = { type: 'pan', startX: sx, startY: sy, vx: view.x, vy: view.y }
}
function onMouseMove(ev) {
  const rect = canvas.value.getBoundingClientRect()
  const sx = ev.clientX - rect.left, sy = ev.clientY - rect.top
  if (drag && drag.type === 'node') {
    const [wx, wy] = toWorld(sx, sy)
    drag.node.fx = wx; drag.node.fy = wy
    startLoop()
  } else if (drag && drag.type === 'pan') {
    view.x = drag.vx + (sx - drag.startX) / view.k
    view.y = drag.vy + (sy - drag.startY) / view.k
    draw()
  } else {
    const n = pickNode(sx, sy)
    const id = n ? n.id : null
    if (id !== hovered) { hovered = id; canvas.value.style.cursor = n ? 'pointer' : 'grab'; draw() }
  }
}
function onMouseUp() {
  if (drag && drag.type === 'node') { drag.node.fx = null; drag.node.fy = null }
  drag = null
}
function onClick(ev) {
  const rect = canvas.value.getBoundingClientRect()
  const sx = ev.clientX - rect.left, sy = ev.clientY - rect.top
  const n = pickNode(sx, sy)
  emit('select', n ? n.ref : null)
}
function onWheel(ev) {
  const rect = canvas.value.getBoundingClientRect()
  const sx = ev.clientX - rect.left, sy = ev.clientY - rect.top
  const [wx, wy] = toWorld(sx, sy)
  const factor = ev.deltaY < 0 ? 1.1 : 0.9
  view.k = Math.max(0.2, Math.min(4, view.k * factor))
  const [sx2, sy2] = toScreen(wx, wy)
  view.x += (sx - sx2) / view.k
  view.y += (sy - sy2) / view.k
  draw()
}

let ro = null
onMounted(() => {
  buildSim()
  ro = new ResizeObserver(resize)
  if (wrap.value) ro.observe(wrap.value)
  resize()
})
onBeforeUnmount(() => { running = false; cancelAnimationFrame(rafId); if (ro) ro.disconnect() })
watch(() => [props.nodes, props.edges], buildSim, { deep: true })
watch(() => props.selectedId, draw)
</script>

<style scoped>
.gb-canvas-wrap { position: relative; width: 100%; height: 100%; min-height: 0; background: var(--color-bg-secondary, #f8fafc); border-radius: 10px; overflow: hidden; }
.gb-canvas { display: block; cursor: grab; }
.gb-canvas-legend { position: absolute; left: 10px; bottom: 10px; display: flex; align-items: center; gap: 12px; background: rgba(255,255,255,0.9); border: 1px solid var(--color-border, #d9e1ea); border-radius: 8px; padding: 6px 10px; font-size: 12px; color: var(--color-text-secondary, #475569); }
.gb-canvas-legend .lg { display: inline-flex; align-items: center; gap: 5px; }
.gb-canvas-legend .lg i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.lg-course i { background: #1769aa; }
.lg-kp i { background: #0d9488; }
.lg-ev i { background: #a16207; }
.lg-hint { margin-left: auto; color: var(--color-text-tertiary, #94a3b8); }
</style>
