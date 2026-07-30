<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  relations: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const host = ref(null)
const canvas = ref(null)
const clusterMode = ref(false)
const expandedClusterLabel = ref('')
const relationColors = {
  PREREQUISITE_OF: '#d97706',
  PART_OF: '#7c3aed',
  EXPLAINS: '#2563eb',
  CAUSES: '#dc2626',
  CONTRASTS_WITH: '#db2777',
  APPLIES_TO: '#059669',
  EXAMPLE_OF: '#0891b2',
  RELATED_TO: '#64748b',
}

let graph = { nodes: [], relations: [] }
let view = { x: 0, y: 0, scale: 1 }
let pointer = null
let hoverId = ''
let frame = 0
let resizeObserver = null
let dpr = 1
let expandedCluster = ''
const reducedMotion = typeof window !== 'undefined'
  ? (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  : true

function hash(value) {
  let result = 2166136261
  for (const char of String(value)) {
    result ^= char.charCodeAt(0)
    result = Math.imul(result, 16777619)
  }
  return result >>> 0
}

function visibleGraphSources() {
  if (props.nodes.length <= 200) {
    clusterMode.value = false
    return {
      sources: props.nodes,
      endpoint: new Map(props.nodes.map((node) => [String(node.id), String(node.id)])),
    }
  }
  clusterMode.value = true
  const groups = new Map()
  for (const source of props.nodes) {
    const type = String(source.type || source.kind || 'concept')
    if (!groups.has(type)) groups.set(type, [])
    groups.get(type).push(source)
  }
  const sources = []
  const endpoint = new Map()
  for (const [type, members] of groups) {
    if (expandedCluster === type) {
      sources.push(...members)
      for (const member of members) endpoint.set(String(member.id), String(member.id))
    } else {
      const clusterId = `cluster:${type}`
      sources.push({
        id: clusterId,
        title: `${type} (${members.length})`,
        type,
        _clusterType: type,
      })
      for (const member of members) endpoint.set(String(member.id), clusterId)
    }
  }
  return { sources, endpoint }
}

function rebuild() {
  const previous = new Map(graph.nodes.map((node) => [node.id, node]))
  const { sources, endpoint } = visibleGraphSources()
  const byId = new Map()
  const nodes = sources.map((source) => {
    const id = String(source.id)
    const old = previous.get(id)
    const angle = ((hash(id) % 360) / 180) * Math.PI
    const radius = 80 + (hash(`${id}:radius`) % 220)
    const item = {
      id,
      source,
      label: source.title || source.label || id,
      x: old?.x ?? Math.cos(angle) * radius,
      y: old?.y ?? Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      fixed: false,
    }
    byId.set(id, item)
    return item
  })
  const relations = props.relations
    .map((payload) => ({
      source: byId.get(endpoint.get(String(payload.source))),
      target: byId.get(endpoint.get(String(payload.target))),
      type: String(payload.type || payload.relation_type || 'RELATED_TO').toUpperCase(),
      payload,
    }))
    .filter((edge) => edge.source && edge.target && edge.source.id !== edge.target.id)
  graph = { nodes, relations }
  for (let tick = 0; tick < (reducedMotion ? 35 : 100); tick += 1) {
    simulate(0.55)
  }
  fit()
  animate()
}

function simulate(alpha) {
  for (let left = 0; left < graph.nodes.length; left += 1) {
    const limit = graph.nodes.length > 200
      ? Math.min(graph.nodes.length, left + 50)
      : graph.nodes.length
    for (let right = left + 1; right < limit; right += 1) {
      const a = graph.nodes[left]
      const b = graph.nodes[right]
      let dx = a.x - b.x
      let dy = a.y - b.y
      let squared = dx * dx + dy * dy
      if (squared < 1) {
        dx = .5
        dy = .5
        squared = 1
      }
      const distance = Math.sqrt(squared)
      const force = (3000 / squared) * alpha
      a.vx += (dx / distance) * force
      a.vy += (dy / distance) * force
      b.vx -= (dx / distance) * force
      b.vy -= (dy / distance) * force
    }
  }
  for (const edge of graph.relations) {
    const dx = edge.target.x - edge.source.x
    const dy = edge.target.y - edge.source.y
    const distance = Math.max(1, Math.hypot(dx, dy))
    const desired = edge.type === 'PREREQUISITE_OF' ? 125 : 100
    const force = (distance - desired) * .018 * alpha
    edge.source.vx += (dx / distance) * force
    edge.source.vy += (dy / distance) * force
    edge.target.vx -= (dx / distance) * force
    edge.target.vy -= (dy / distance) * force
  }
  for (const node of graph.nodes) {
    if (node.fixed) continue
    node.vx = (node.vx - node.x * .006 * alpha) * .84
    node.vy = (node.vy - node.y * .006 * alpha) * .84
    node.x += node.vx
    node.y += node.vy
  }
}

function animate() {
  cancelAnimationFrame(frame)
  if (reducedMotion) {
    draw()
    return
  }
  let tick = 0
  const step = () => {
    simulate(Math.max(.08, 1 - tick / 220))
    draw()
    tick += 1
    if (tick < 220) frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
}

function resize() {
  if (!host.value || !canvas.value) return
  dpr = window.devicePixelRatio || 1
  const width = host.value.clientWidth
  const height = host.value.clientHeight
  canvas.value.width = width * dpr
  canvas.value.height = height * dpr
  canvas.value.style.width = `${width}px`
  canvas.value.style.height = `${height}px`
  draw()
}

function worldToScreen(x, y) {
  const width = (canvas.value?.width || 0) / dpr
  const height = (canvas.value?.height || 0) / dpr
  return [
    width / 2 + (x + view.x) * view.scale,
    height / 2 + (y + view.y) * view.scale,
  ]
}

function screenToWorld(x, y) {
  const width = (canvas.value?.width || 0) / dpr
  const height = (canvas.value?.height || 0) / dpr
  return [
    (x - width / 2) / view.scale - view.x,
    (y - height / 2) / view.scale - view.y,
  ]
}

function fit() {
  if (!graph.nodes.length || !host.value) return
  const xs = graph.nodes.map((node) => node.x)
  const ys = graph.nodes.map((node) => node.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  view.scale = Math.max(.28, Math.min(1.5, Math.min(
    host.value.clientWidth / Math.max(240, maxX - minX + 180),
    host.value.clientHeight / Math.max(180, maxY - minY + 180),
  )))
  view.x = -(minX + maxX) / 2
  view.y = -(minY + maxY) / 2
  draw()
}

function drawArrow(context, edge, highlighted) {
  const [startX, startY] = worldToScreen(edge.source.x, edge.source.y)
  const [endX, endY] = worldToScreen(edge.target.x, edge.target.y)
  const angle = Math.atan2(endY - startY, endX - startX)
  const x = endX - Math.cos(angle) * (17 * view.scale + 4)
  const y = endY - Math.sin(angle) * (17 * view.scale + 4)
  context.beginPath()
  context.moveTo(startX, startY)
  context.lineTo(x, y)
  context.strokeStyle = relationColors[edge.type] || relationColors.RELATED_TO
  context.globalAlpha = highlighted ? .95 : .25
  context.lineWidth = highlighted ? 2.2 : 1.1
  context.stroke()
  context.beginPath()
  context.moveTo(x, y)
  context.lineTo(x - Math.cos(angle - .48) * 8, y - Math.sin(angle - .48) * 8)
  context.lineTo(x - Math.cos(angle + .48) * 8, y - Math.sin(angle + .48) * 8)
  context.closePath()
  context.fillStyle = context.strokeStyle
  context.fill()
  context.globalAlpha = 1
}

function draw() {
  if (!canvas.value) return
  const context = canvas.value.getContext('2d')
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, canvas.value.width / dpr, canvas.value.height / dpr)
  const selected = String(props.selectedId || '')
  const connected = new Set([selected])
  for (const edge of graph.relations) {
    if (edge.source.id === selected) connected.add(edge.target.id)
    if (edge.target.id === selected) connected.add(edge.source.id)
    drawArrow(
      context,
      edge,
      !selected || edge.source.id === selected || edge.target.id === selected,
    )
  }
  for (const node of graph.nodes) {
    const [x, y] = worldToScreen(node.x, node.y)
    const active = node.id === selected
    const cluster = Boolean(node.source?._clusterType)
    const radius = (cluster ? 19 : active ? 15 : 12) * Math.max(.72, Math.min(1.2, view.scale))
    context.globalAlpha = selected && !connected.has(node.id) ? .28 : 1
    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    context.fillStyle = cluster ? '#7c3aed' : active ? '#0f766e' : '#0d9488'
    context.fill()
    if (active || node.id === hoverId) {
      context.strokeStyle = '#ccfbf1'
      context.lineWidth = 5
      context.stroke()
    }
    context.fillStyle = '#0f172a'
    context.font = `${active ? 600 : 500} 12px system-ui, sans-serif`
    context.textAlign = 'center'
    const label = node.label.length > 16 ? `${node.label.slice(0, 15)}…` : node.label
    context.fillText(label, x, y + radius + 16)
    context.globalAlpha = 1
  }
}

function eventPoint(event) {
  const rect = canvas.value.getBoundingClientRect()
  return [event.clientX - rect.left, event.clientY - rect.top]
}

function pick(x, y) {
  const [worldX, worldY] = screenToWorld(x, y)
  return graph.nodes.find(
    (node) => Math.hypot(node.x - worldX, node.y - worldY) < 22 / view.scale,
  ) || null
}

function onPointerDown(event) {
  canvas.value.setPointerCapture(event.pointerId)
  const [x, y] = eventPoint(event)
  const node = pick(x, y)
  pointer = node
    ? { kind: 'node', node, moved: false }
    : { kind: 'pan', x, y, viewX: view.x, viewY: view.y, moved: false }
  if (node) node.fixed = true
}

function onPointerMove(event) {
  const [x, y] = eventPoint(event)
  if (!pointer) {
    hoverId = pick(x, y)?.id || ''
    canvas.value.style.cursor = hoverId ? 'pointer' : 'grab'
    draw()
    return
  }
  pointer.moved = true
  if (pointer.kind === 'node') {
    ;[pointer.node.x, pointer.node.y] = screenToWorld(x, y)
  } else {
    view.x = pointer.viewX + (x - pointer.x) / view.scale
    view.y = pointer.viewY + (y - pointer.y) / view.scale
  }
  draw()
}

function onPointerUp() {
  if (!pointer) return
  if (pointer.kind === 'node') {
    pointer.node.fixed = false
    if (!pointer.moved) {
      if (pointer.node.source?._clusterType) {
        expandedCluster = pointer.node.source._clusterType
        expandedClusterLabel.value = expandedCluster
        rebuild()
      } else {
        emit('select', pointer.node.source)
      }
    }
  }
  pointer = null
}

function onWheel(event) {
  event.preventDefault()
  const [x, y] = eventPoint(event)
  const [worldX, worldY] = screenToWorld(x, y)
  view.scale = Math.max(.2, Math.min(4, view.scale * (event.deltaY < 0 ? 1.12 : .89)))
  const [newX, newY] = worldToScreen(worldX, worldY)
  view.x += (x - newX) / view.scale
  view.y += (y - newY) / view.scale
  draw()
}

function collapseClusters() {
  expandedCluster = ''
  expandedClusterLabel.value = ''
  rebuild()
}

onMounted(() => {
  resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(host.value)
  rebuild()
  resize()
})
onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  resizeObserver?.disconnect()
})
watch(() => [props.nodes, props.relations], rebuild, { deep: true })
watch(() => props.selectedId, (selectedId) => {
  if (props.nodes.length > 200 && selectedId) {
    const selected = props.nodes.find((node) => String(node.id) === String(selectedId))
    const type = selected ? String(selected.type || selected.kind || 'concept') : ''
    if (type && type !== expandedCluster) {
      expandedCluster = type
      expandedClusterLabel.value = type
      rebuild()
      return
    }
  }
  draw()
})
</script>

<template>
  <div ref="host" class="canvas-host">
    <canvas
      ref="canvas"
      aria-label="课程知识图谱，可拖拽节点、平移和缩放"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @wheel="onWheel"
      @dblclick="fit"
    />
    <div class="actions">
      <button
        v-if="clusterMode && expandedClusterLabel"
        type="button"
        @click="collapseClusters"
      >
        收起聚类
      </button>
      <button type="button" @click="fit">重置视图</button>
    </div>
    <div class="legend">
      <span v-for="(color, type) in relationColors" :key="type">
        <i :style="{ background: color }" />{{ type }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.canvas-host { position: relative; width: 100%; min-height: 430px; overflow: hidden; border: 1px solid #dbe3ea; border-radius: 16px; background: radial-gradient(circle at 50% 45%, #fff 0, #f8fafc 68%, #eef6f5 100%); touch-action: none; }
.canvas-host canvas { display: block; cursor: grab; }
.actions { position: absolute; top: 12px; right: 12px; display: flex; gap: 7px; }
.actions button { border: 1px solid #cbd5e1; border-radius: 9px; padding: 7px 11px; background: rgb(255 255 255 / 92%); color: #334155; cursor: pointer; }
.legend { position: absolute; left: 12px; bottom: 12px; display: flex; max-width: calc(100% - 24px); flex-wrap: wrap; gap: 8px 12px; border: 1px solid #e2e8f0; border-radius: 10px; padding: 7px 10px; background: rgb(255 255 255 / 90%); color: #64748b; font-size: 10px; pointer-events: none; }
.legend span { display: inline-flex; align-items: center; gap: 4px; }
.legend i { width: 8px; height: 8px; border-radius: 999px; }
</style>
