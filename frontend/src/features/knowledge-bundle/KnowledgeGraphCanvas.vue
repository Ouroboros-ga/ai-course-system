<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  relations: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
  rightInset: { type: Number, default: 0 },
})
const emit = defineEmits(['select'])

const host = ref(null)
const canvas = ref(null)
const clusterMode = ref(false)
const expandedClusterLabel = ref('')
// 力导向"余温"模型：alpha>0 时 rAF 循环持续模拟，交互可 reheat 重新加热，
// 松手后整图带阻尼回弹，而不是一次性动画结束后僵硬静止。
let simulationAlpha = 0
let simulationFrame = 0
// 绘制合并：指针事件频率可能高于帧率，直接 draw 会造成一帧多次重绘卡顿，
// 统一调度到每帧最多一次。
let drawFrame = 0
const CLUSTER_THRESHOLD = 120        // design.md §5 大图阈值：超过120节点即聚类
const SUBCLUSTER_LIMIT = 60          // 单聚类展开后内部仍超过60则二次分桶
// design.md §1.1 Academic Ink 体系；不再使用 teal/紫色装饰色
const relationColors = {
  PREREQUISITE_OF: '#E58A00',
  PART_OF:         '#3157D5',
  EXPLAINS:        '#009DB5',
  CAUSES:          '#D64545',
  CONTRASTS_WITH:  '#C34D8C',
  APPLIES_TO:      '#168C5E',
  EXAMPLE_OF:      '#659E3E',
  RELATED_TO:      '#73839B',
}
// 节点类型中文化（解决"部分标题仍为英文或语义较弱"遗留问题）
const TYPE_LABELS = {
  concept: '概念',
  knowledge_point: '知识点',
  skill: '技能',
  topic: '主题',
  chapter: '章节',
  section: '小节',
  method: '方法',
  principle: '原理',
  formula: '公式',
  example: '示例',
  definition: '定义',
  theorem: '定理',
  algorithm: '算法',
  procedure: '流程',
  assessment: '考核',
  default: '节点',
}
function typeLabel(type) {
  return TYPE_LABELS[String(type || '').toLowerCase()] || TYPE_LABELS.default
}
// 关系类型中文化（解决"部分标题仍为英文或语义较弱"遗留问题）
const RELATION_LABELS = {
  PREREQUISITE_OF: '先修',
  PART_OF: '组成',
  EXPLAINS: '解释',
  CAUSES: '因果',
  CONTRASTS_WITH: '对比',
  APPLIES_TO: '应用',
  EXAMPLE_OF: '举例',
  RELATED_TO: '关联',
}

const selectedLabel = computed(() => {
  const selected = props.nodes.find((node) => String(node.id) === String(props.selectedId))
  return selected?.title || selected?.label || ''
})

// 组件实例级状态（避免模块级共享导致跨实例污染/坐标爆炸）
let graph = { nodes: [], relations: [], endpoint: new Map() }
let view = { x: 0, y: 0, scale: 1 }
let pointer = null
let hoverId = ''
let resizeObserver = null
let dpr = 1
let expandedCluster = ''
const reducedMotion = typeof window !== 'undefined'
  ? (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  : true
// 坐标安全边界：超过此值视为坐标爆炸，重置该节点
const COORD_LIMIT = 1e6
const VELOCITY_LIMIT = 1e4

function hash(value) {
  let result = 2166136261
  for (const char of String(value)) {
    result ^= char.charCodeAt(0)
    result = Math.imul(result, 16777619)
  }
  return result >>> 0
}

function normalizeType(source) {
  return String(source.type || source.kind || 'concept').trim().toLowerCase()
}

function visibleGraphSources() {
  if (props.nodes.length <= CLUSTER_THRESHOLD) {
    clusterMode.value = false
    expandedClusterLabel.value = ''
    return {
      sources: props.nodes,
      endpoint: new Map(props.nodes.map((node) => [String(node.id), String(node.id)])),
    }
  }
  clusterMode.value = true
  // 按 type 分组（一级聚类），统一小写避免 'concept' / 'Concept' 分裂成多个聚类
  const groups = new Map()
  for (const source of props.nodes) {
    const type = normalizeType(source)
    if (!groups.has(type)) groups.set(type, [])
    groups.get(type).push(source)
  }
  const sources = []
  const endpoint = new Map()
  for (const [type, members] of groups) {
    if (expandedCluster === type) {
      // 渐进展开：展开后若仍超过 SUBCLUSTER_LIMIT，按 hash 二次分桶
      if (members.length > SUBCLUSTER_LIMIT) {
        const buckets = new Map()
        for (const m of members) {
          const idx = hash(`${type}:${m.id}`) % 4
          if (!buckets.has(idx)) buckets.set(idx, [])
          buckets.get(idx).push(m)
        }
        for (const [idx, bucket] of buckets) {
          const clusterId = `cluster:${type}:${idx}`
          sources.push({
            id: clusterId,
            title: `${typeLabel(type)} · 第${idx + 1}组 (${bucket.length})`,
            type,
            _clusterType: type,
            _clusterSub: idx,
          })
          for (const m of bucket) endpoint.set(String(m.id), clusterId)
        }
      } else {
        sources.push(...members)
        for (const member of members) endpoint.set(String(member.id), String(member.id))
      }
    } else {
      const clusterId = `cluster:${type}`
      sources.push({
        id: clusterId,
        title: `${typeLabel(type)} (${members.length})`,
        type,
        _clusterType: type,
      })
      for (const member of members) endpoint.set(String(member.id), clusterId)
    }
  }
  return { sources, endpoint }
}

function rebuild() {
  cancelAnimationFrame(simulationFrame)
  simulationFrame = 0
  const previous = new Map(graph.nodes.map((node) => [node.id, node]))
  const { sources, endpoint } = visibleGraphSources()
  const sourceGraphIsLarge = props.nodes.length > CLUSTER_THRESHOLD
  const byId = new Map()
  const nodes = sources.map((source) => {
    const id = String(source.id)
    const old = previous.get(id)
    const angle = ((hash(id) % 360) / 180) * Math.PI
    const radius = 110 + (hash(`${id}:radius`) % 280)
    const item = {
      id,
      source,
      label: source.title || source.label || id,
      // 大图重建时使用稳定位置，不能继承旧力导向留下的远距离坐标。
      // 节点拖拽不触发 rebuild，因此正常交互中的手工位置仍会保留。
      x: sourceGraphIsLarge ? Math.cos(angle) * radius : old?.x ?? Math.cos(angle) * radius,
      y: sourceGraphIsLarge ? Math.sin(angle) * radius : old?.y ?? Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      fixed: false,
    }
    // 旧坐标可能来自已爆炸的力导向状态，这里强制校验
    if (!Number.isFinite(item.x) || !Number.isFinite(item.y) || Math.abs(item.x) > COORD_LIMIT || Math.abs(item.y) > COORD_LIMIT) {
      resetExplodedNode(item)
    }
    byId.set(id, item)
    return item
  })
  // 聚类后大量原始关系会落到同一对可见端点。若仍逐条参与绘制和力学计算，
  // 同一对节点会被重复施力并出现平行长线，因此按端点和关系类型合并。
  const relationByKey = new Map()
  for (const payload of props.relations) {
    const source = byId.get(endpoint.get(String(payload.source)))
    const target = byId.get(endpoint.get(String(payload.target)))
    if (!source || !target || source.id === target.id) continue
    const type = String(payload.type || payload.relation_type || 'RELATED_TO').toUpperCase()
    const key = `${source.id}\u0000${target.id}\u0000${type}`
    const existing = relationByKey.get(key)
    if (existing) {
      existing.count += 1
    } else {
      relationByKey.set(key, { source, target, type, payload, count: 1 })
    }
  }
  graph = { nodes, relations: [...relationByKey.values()], endpoint }
  // 大图（已聚类）完全不跑力导向预迭代，并使用稳定 hash 初始位置。
  // 避免 simulate 改变坐标 + fit 重置视图导致的抽搐跳变。
  // 小图保留力导向以呈现自然布局。
  // 大图判定必须基于原始拓扑。课程图谱即使聚类后只显示少量节点，仍然不能
  // 被当成小图重新运行力导向动画，否则选择节点时会把整个布局拉出视口。
  const isLargeGraph = sourceGraphIsLarge || graph.nodes.length > 200
  if (!isLargeGraph) {
    const preIterations = reducedMotion ? 35 : 100
    for (let tick = 0; tick < preIterations; tick += 1) {
      simulate(0.55)
    }
  }
  fit()
  if (isLargeGraph) {
    draw()
  } else {
    startSimulation(true)
  }
}

function resetExplodedNode(node) {
  const angle = ((hash(node.id) % 360) / 180) * Math.PI
  const radius = 110 + (hash(`${node.id}:radius`) % 280)
  node.x = Math.cos(angle) * radius
  node.y = Math.sin(angle) * radius
  node.vx = 0
  node.vy = 0
}

function clampVelocity(v) {
  return Math.max(-VELOCITY_LIMIT, Math.min(VELOCITY_LIMIT, v))
}

function simulate(alpha) {
  for (let left = 0; left < graph.nodes.length; left += 1) {
    const limit = graph.nodes.length > 200
      ? Math.min(graph.nodes.length, left + 50)
      : graph.nodes.length
    for (let right = left + 1; right < limit; right += 1) {
      const a = graph.nodes[left]
      const b = graph.nodes[right]
      // 坐标安全检查：重置爆炸节点，防止后续计算产生 NaN/Inf
      if (!Number.isFinite(a.x) || !Number.isFinite(a.y) || Math.abs(a.x) > COORD_LIMIT || Math.abs(a.y) > COORD_LIMIT) {
        resetExplodedNode(a)
      }
      if (!Number.isFinite(b.x) || !Number.isFinite(b.y) || Math.abs(b.x) > COORD_LIMIT || Math.abs(b.y) > COORD_LIMIT) {
        resetExplodedNode(b)
      }
      let dx = a.x - b.x
      let dy = a.y - b.y
      let squared = dx * dx + dy * dy
      if (squared < 1) {
        dx = .5
        dy = .5
        squared = 1
      }
      const distance = Math.sqrt(squared)
      const force = (5200 / squared) * alpha
      const ax = (dx / distance) * force
      const ay = (dy / distance) * force
      a.vx = clampVelocity(a.vx + ax)
      a.vy = clampVelocity(a.vy + ay)
      b.vx = clampVelocity(b.vx - ax)
      b.vy = clampVelocity(b.vy - ay)
    }
  }
  for (const edge of graph.relations) {
    const dx = edge.target.x - edge.source.x
    const dy = edge.target.y - edge.source.y
    const distance = Math.max(1, Math.hypot(dx, dy))
    const desired = edge.type === 'PREREQUISITE_OF' ? 165 : 135
    const force = (distance - desired) * .018 * alpha
    edge.source.vx = clampVelocity(edge.source.vx + (dx / distance) * force)
    edge.source.vy = clampVelocity(edge.source.vy + (dy / distance) * force)
    edge.target.vx = clampVelocity(edge.target.vx - (dx / distance) * force)
    edge.target.vy = clampVelocity(edge.target.vy - (dy / distance) * force)
  }
  for (const node of graph.nodes) {
    if (node.fixed) continue
    if (!Number.isFinite(node.x) || !Number.isFinite(node.y) || Math.abs(node.x) > COORD_LIMIT || Math.abs(node.y) > COORD_LIMIT) {
      resetExplodedNode(node)
      continue
    }
    // 增强中心引力，避免大图节点过度散开导致部分节点跑出可视区
    const centerForce = .018 * alpha
    const damping = .82
    node.vx = clampVelocity((node.vx - node.x * centerForce) * damping)
    node.vy = clampVelocity((node.vy - node.y * centerForce) * damping)
    node.x += node.vx
    node.y += node.vy
  }
}

function startSimulation(initial) {
  cancelAnimationFrame(simulationFrame)
  simulationFrame = 0
  if (reducedMotion) {
    if (initial) fit()
    draw()
    return
  }
  if (initial) simulationAlpha = 1
  const step = () => {
    simulationAlpha = Math.max(0, simulationAlpha - .005)
    simulate(Math.max(.02, simulationAlpha))
    draw()
    if (simulationAlpha > 0) {
      simulationFrame = requestAnimationFrame(step)
    } else {
      simulationFrame = 0
      // 初次布局收敛后重新适配视图，防止节点在动画中漂出可视区
      if (initial) fit()
    }
  }
  simulationFrame = requestAnimationFrame(step)
}

// 交互中/松手后"加热"力学模拟，让邻居弹性跟随、整图阻尼回弹。
// 大图（>200 可见节点）刻意保持静态布局，避免性能抖动（见 rebuild 注释）。
function reheat(value) {
  if (reducedMotion || graph.nodes.length > 200) return
  simulationAlpha = Math.max(simulationAlpha, value)
  if (!simulationFrame) startSimulation(false)
}

function scheduleDraw() {
  if (drawFrame) return
  drawFrame = requestAnimationFrame(() => {
    drawFrame = 0
    draw()
  })
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

function effectiveRightInset() {
  const width = host.value?.clientWidth || 0
  if (width < 760) return 0
  return Math.min(Math.max(0, props.rightInset), width * .42)
}

function viewportCenterX() {
  const width = (canvas.value?.width || 0) / dpr
  return (width - effectiveRightInset()) / 2
}

function worldToScreen(x, y) {
  const height = (canvas.value?.height || 0) / dpr
  const safeScale = Number.isFinite(view.scale) && view.scale > 0 ? view.scale : 1
  const safeX = Number.isFinite(view.x) ? view.x : 0
  const safeY = Number.isFinite(view.y) ? view.y : 0
  return [
    viewportCenterX() + (x + safeX) * safeScale,
    height / 2 + (y + safeY) * safeScale,
  ]
}

function screenToWorld(x, y) {
  const height = (canvas.value?.height || 0) / dpr
  const safeScale = Number.isFinite(view.scale) && view.scale > 0 ? view.scale : 1
  const safeX = Number.isFinite(view.x) ? view.x : 0
  const safeY = Number.isFinite(view.y) ? view.y : 0
  return [
    (x - viewportCenterX()) / safeScale - safeX,
    (y - height / 2) / safeScale - safeY,
  ]
}

function fit() {
  if (!graph.nodes.length || !host.value) return
  // 再次过滤异常坐标，避免 Math.min/max 产生 Infinity/NaN 导致视图消失
  const xs = graph.nodes.map((node) => node.x).filter(Number.isFinite)
  const ys = graph.nodes.map((node) => node.y).filter(Number.isFinite)
  if (!xs.length || !ys.length) return
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const rangeX = Math.max(240, maxX - minX + 200)
  const rangeY = Math.max(180, maxY - minY + 200)
  const availableWidth = Math.max(320, host.value.clientWidth - effectiveRightInset())
  view.scale = Math.max(.28, Math.min(1.5, Math.min(
    availableWidth / rangeX,
    host.value.clientHeight / rangeY,
  )))
  view.x = -(minX + maxX) / 2
  view.y = -(minY + maxY) / 2
  draw()
}

function drawArrow(context, edge, highlighted) {
  const [centerX, centerY] = worldToScreen(edge.source.x, edge.source.y)
  const [endX, endY] = worldToScreen(edge.target.x, edge.target.y)
  const angle = Math.atan2(endY - centerY, endX - centerX)
  // 连线从源节点边缘出发、止于目标节点边缘，避免穿过节点圆心与文字
  const startX = centerX + Math.cos(angle) * (15 * view.scale + 2)
  const startY = centerY + Math.sin(angle) * (15 * view.scale + 2)
  const x = endX - Math.cos(angle) * (17 * view.scale + 4)
  const y = endY - Math.sin(angle) * (17 * view.scale + 4)
  context.beginPath()
  context.moveTo(startX, startY)
  context.lineTo(x, y)
  context.strokeStyle = relationColors[edge.type] || relationColors.RELATED_TO
  context.globalAlpha = highlighted ? .98 : .2
  const weight = Math.min(1.8, 1 + Math.log2(edge.count || 1) * .12)
  context.lineWidth = (highlighted ? 2.2 : 1.1) * weight
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
  const selectedKey = String(props.selectedId || '')
  // 选中的真实节点处于收起聚类时，高亮其可见聚类节点，不改变聚类展开状态。
  const selected = graph.endpoint.get(selectedKey) || selectedKey
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
    const radius = (cluster ? 24 : active ? 19 : 15) * Math.max(.72, Math.min(1.2, view.scale))
    context.globalAlpha = selected && !connected.has(node.id) ? .2 : 1
    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    // design.md §1.1：节点填充使用 Academic Ink，聚类用 amber-500 标识"AI 当前关注"
    context.fillStyle = cluster ? '#7C4DDB' : active ? '#F26A21' : '#3157B7'
    context.fill()
    if (active || node.id === hoverId) {
      context.strokeStyle = active ? '#FFFFFF' : '#DCE5FF'
      context.lineWidth = active ? 5 : 4
      context.stroke()
    }
    if (active) {
      context.beginPath()
      context.arc(x, y, radius + 9, 0, Math.PI * 2)
      context.strokeStyle = 'rgba(242, 106, 33, .48)'
      context.lineWidth = 4
      context.stroke()
    }
    context.fillStyle = active ? '#9A3412' : '#172033'
    context.font = `${active ? 700 : 550} ${active ? 13 : 12}px Inter, "HarmonyOS Sans SC", "PingFang SC", system-ui, sans-serif`
    context.textAlign = 'center'
    const label = node.label.length > 16 ? `${node.label.slice(0, 15)}…` : node.label
    // 文字白色描边光晕：连线从文字下方穿过时保持可读，不再互相压盖
    context.lineJoin = 'round'
    context.lineWidth = 3
    context.strokeStyle = 'rgba(255, 255, 255, .92)'
    context.strokeText(label, x, y + radius + 17)
    context.fillText(label, x, y + radius + 17)
    context.globalAlpha = 1
  }
}

function eventPoint(event) {
  const rect = canvas.value.getBoundingClientRect()
  return [event.clientX - rect.left, event.clientY - rect.top]
}

function pick(x, y) {
  const [worldX, worldY] = screenToWorld(x, y)
  // 聚类节点半径更大，命中阈值随缩放动态调整，提升点击容错
  const threshold = Math.max(28 / view.scale, 14)
  return graph.nodes.find(
    (node) => Math.hypot(node.x - worldX, node.y - worldY) < threshold,
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
    const id = pick(x, y)?.id || ''
    if (id !== hoverId) {
      hoverId = id
      const cursor = hoverId ? 'pointer' : 'grab'
      // 仅变化时写 style，避免每次 move 触发样式重算
      if (canvas.value.style.cursor !== cursor) canvas.value.style.cursor = cursor
      scheduleDraw()
    }
    return
  }
  pointer.moved = true
  if (pointer.kind === 'node') {
    ;[pointer.node.x, pointer.node.y] = screenToWorld(x, y)
    // 拖拽中保持余温：相连节点弹性跟随，而不是只有被拖节点孤零零移动
    reheat(.12)
    // 力学循环运行时由它负责每帧绘制；未运行（降级/大图）才调度补充绘制
    if (!simulationFrame) scheduleDraw()
  } else {
    view.x = pointer.viewX + (x - pointer.x) / view.scale
    view.y = pointer.viewY + (y - pointer.y) / view.scale
    scheduleDraw()
  }
}

function onPointerUp() {
  if (!pointer) return
  if (pointer.kind === 'node') {
    pointer.node.fixed = false
    // 松手后重新加热：整图按力学关系阻尼回弹到新平衡（小幅度，仅恢复局部平衡）
    reheat(.22)
    if (!pointer.moved) {
      if (pointer.node.source?._clusterType) {
        expandedCluster = pointer.node.source._clusterType
        expandedClusterLabel.value = typeLabel(expandedCluster)
        rebuild()
      } else {
        emit('select', pointer.node.source)
      }
    }
  } else if (pointer.kind === 'pan' && !pointer.moved) {
    // 点击空白处（未拖动平移）：取消选择
    emit('select', null)
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
  cancelAnimationFrame(simulationFrame)
  cancelAnimationFrame(drawFrame)
  resizeObserver?.disconnect()
})
watch(() => [props.nodes, props.relations], rebuild)
watch(() => props.selectedId, draw)
watch(() => props.rightInset, fit)
</script>

<template>
  <div class="canvas-frame">
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
          class="sfx-canvas-btn"
          @click="collapseClusters"
        >
          收起「{{ expandedClusterLabel }}」聚类
        </button>
        <button type="button" class="sfx-canvas-btn" @click="fit">重置视图</button>
      </div>
      <div v-if="clusterMode" class="cluster-hint" aria-live="polite">
        节点超过 {{ CLUSTER_THRESHOLD }} 个，已按类型聚类。点击聚类圆点可展开该类型；展开后若仍超过 {{ SUBCLUSTER_LIMIT }} 个，将自动二次分桶。
      </div>
    </div>

    <footer class="canvas-footer" aria-label="图谱阅读辅助">
      <div class="focus-status">
        <span class="focus-status__mark" aria-hidden="true" />
        <span class="focus-status__label">当前聚焦</span>
        <strong>{{ selectedLabel || '选择知识点查看关联' }}</strong>
      </div>
      <div class="legend" aria-label="关系类型">
        <span v-for="(color, type) in relationColors" :key="type">
          <i :style="{ background: color }" />{{ RELATION_LABELS[type] || type }}
        </span>
      </div>
      <p class="canvas-help">拖拽节点 · 滚轮缩放 · 双击画布复位</p>
    </footer>
  </div>
</template>

<style scoped>
.canvas-frame {
  display: grid;
  grid-template-rows: minmax(560px, 1fr) auto;
  width: 100%;
  height: 100%;
  min-height: 650px;
  overflow: hidden;
  border: 1px solid var(--border-default, #DDE2E8);
  border-radius: var(--radius-lg, 14px);
  background: #FFFFFF;
}
.canvas-host {
  position: relative;
  width: 100%;
  min-height: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 50% 42%, rgba(49, 87, 183, .08), transparent 34%),
    linear-gradient(rgba(49, 87, 183, .045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(49, 87, 183, .045) 1px, transparent 1px),
    #FAFBFE;
  background-size: auto, 28px 28px, 28px 28px, auto;
  touch-action: none;
}
.canvas-host canvas { display: block; cursor: grab; }
.actions {
  position: absolute;
  top: var(--space-3, 12px);
  right: var(--space-3, 12px);
  display: flex;
  gap: var(--space-2, 8px);
}
/* design.md §9.1：所有按钮应用 SfxButton；canvas 内浮动按钮为图标按钮例外，
   但仍需使用令牌色与圆角 */
.sfx-canvas-btn {
  border: 1px solid var(--border-strong, #C9CFD8);
  border-radius: var(--radius-md, 10px);
  padding: 6px var(--space-3, 12px);
  background: rgba(255, 255, 255, 0.92);
  color: var(--ink-700, #203A5F);
  font-size: var(--ui-sm-size, 13px);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--duration-fast, 120ms) var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
}
.sfx-canvas-btn:hover { background: var(--surface-cool, #F7F8FA); }
.cluster-hint {
  position: absolute;
  top: var(--space-3, 12px);
  left: var(--space-3, 12px);
  max-width: 320px;
  padding: var(--space-2, 8px) var(--space-3, 12px);
  background: var(--amber-100, #FBF3DE);
  border: 1px solid var(--amber-300, #E5B95C);
  border-radius: var(--radius-sm, 6px);
  color: var(--amber-700, #9B6618);
  font-size: var(--caption-size, 12px);
  line-height: 1.5;
}
.canvas-footer {
  display: grid;
  grid-template-columns: minmax(190px, auto) minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  min-height: 76px;
  padding: 12px 16px;
  border-top: 1px solid #E4E9F2;
  background: linear-gradient(90deg, #FFFFFF, #F7F9FD);
}
.focus-status {
  display: grid;
  grid-template-columns: 12px auto;
  align-items: center;
  column-gap: 8px;
  min-width: 0;
}
.focus-status__mark {
  grid-row: 1 / span 2;
  width: 12px;
  height: 12px;
  border: 3px solid #FFFFFF;
  border-radius: 999px;
  background: #F26A21;
  box-shadow: 0 0 0 3px rgba(242, 106, 33, .24);
}
.focus-status__label { color: #7A8799; font-size: 11px; }
.focus-status strong {
  max-width: 220px;
  overflow: hidden;
  color: #172033;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.legend {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  color: #536176;
  font-size: 12px;
}
.legend span { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.legend i {
  width: 18px;
  height: 5px;
  border-radius: 999px;
  box-shadow: 0 1px 3px rgba(20, 33, 61, .16);
}
.canvas-help { margin: 0; color: #7A8799; font-size: 11px; white-space: nowrap; }

@container (max-width: 900px) {
  .canvas-frame { grid-template-rows: minmax(520px, 1fr) auto; min-height: 620px; }
  .canvas-footer { grid-template-columns: 1fr; gap: 10px; }
  .legend { justify-content: flex-start; }
  .canvas-help { display: none; }
}
</style>
