import { computed, ref, watch } from 'vue'

function sameId(left, right) {
  return left != null && right != null && String(left) === String(right)
}

/**
 * Select the source clock without treating a shared course audio file as a
 * per-node clip. Only an item-owned URL can use that item's local offset.
 */
export function resolveActiveAudioClock(items, activeIndex, fallbackAudioUrl = '') {
  const item = Array.isArray(items) ? items[activeIndex] ?? null : null
  const itemAudioUrl = String(item?.audioUrl || '')
  const audioUrl = itemAudioUrl || String(fallbackAudioUrl || '')
  const segmented = Boolean(itemAudioUrl)
  return {
    audioUrl,
    offsetSeconds: segmented ? Math.max(0, Number(item?.offsetMs) || 0) / 1000 : 0,
    segmented,
    // A shared source must keep the same element across rail selection, while
    // adjacent segmented items need unique generations even if their URLs match.
    generation: segmented ? `item:${activeIndex}:${audioUrl}` : `shared:${audioUrl}`,
  }
}

/** Return whether an event was emitted by the currently rendered media clock. */
export function isActiveAudioClockEvent(eventGeneration, activeGeneration) {
  return String(eventGeneration || '') === String(activeGeneration || '')
}

/** Ignore clock drift from media timeupdates, but always honor a learner seek. */
export function shouldSeekMediaClock(currentSeconds, targetSeconds, force = false) {
  if (force) return true
  return Math.abs((Number(currentSeconds) || 0) - (Number(targetSeconds) || 0)) > 1.25
}

/** Match a course node to its immutable playlist item. Node ids are preferred. */
export function findPlaylistItemIndex(items, node) {
  if (!Array.isArray(items) || !node) return -1
  const nodeIndex = items.findIndex(item => sameId(item?.nodeId, node.id))
  if (nodeIndex >= 0) return nodeIndex
  return items.findIndex(item => sameId(item?.outlineNodeId, node.outlineNodeId))
}

const KNOWLEDGE_NODE_TYPES = new Set(['knowledge_point', 'KNOWLEDGE_POINT'])

function isKnowledgePointNode(node) {
  return KNOWLEDGE_NODE_TYPES.has(String(node?.type ?? node?.nodeType ?? ''))
}

function outlineIdOf(node) {
  return node?.outlineNodeId ?? node?.id ?? null
}

function isDescendantOf(nodes, indexById, childIndex, ancestorIndex, maxDepth = 24) {
  const ancestorId = outlineIdOf(nodes[ancestorIndex])
  if (ancestorId == null) return false
  let parent = nodes[childIndex]?.chapterId ?? null
  let depth = 0
  while (parent != null && depth < maxDepth) {
    if (String(parent) === String(ancestorId)) return true
    parent = nodes[indexById.get(String(parent))]?.chapterId ?? null
    depth += 1
  }
  return false
}

function normalizeMatchKey(value) {
  return String(value ?? '').trim().toLowerCase()
}

function knowledgeGraphKeyOf(entry) {
  return normalizeMatchKey(entry?.knowledgeGraphNodeId ?? entry?.knowledge_graph_node_id)
}

function titleKeyOf(entry) {
  return normalizeMatchKey(entry?.title)
}

/**
 * Stable-key bridge for teacher draft preview.
 *
 * A draft outline and the frozen media release own different
 * ``outline_node_id`` values, so every id-based matcher fails and the rail,
 * the playlist clock and review jumps silently desynchronize.  The two sides
 * also do NOT share a knowledge-point order (drafts reorder nodes freely),
 * so positional mapping is unreliable.  Instead, match each draft knowledge
 * point to a playlist item by the stable knowledge-graph concept id first,
 * then by normalized title, and only fall back to positional pairing for
 * unmatched leftovers.  Non-knowledge nodes (chapter/section) fall back to
 * their first descendant knowledge point so authoring clicks still land on
 * media.
 */
export function buildPreviewPlaylistBridge(nodes, items) {
  if (!Array.isArray(nodes) || !Array.isArray(items) || !items.length) return null
  const nodeToItem = new Array(nodes.length).fill(-1)
  const itemToNode = new Array(items.length).fill(-1)
  const knowledgeIndexes = []
  nodes.forEach((node, index) => {
    if (isKnowledgePointNode(node)) knowledgeIndexes.push(index)
  })

  const itemIndexesByGraphKey = new Map()
  const itemIndexesByTitleKey = new Map()
  items.forEach((item, position) => {
    const graphKey = knowledgeGraphKeyOf(item)
    if (graphKey) {
      if (!itemIndexesByGraphKey.has(graphKey)) itemIndexesByGraphKey.set(graphKey, [])
      itemIndexesByGraphKey.get(graphKey).push(position)
    }
    const title = titleKeyOf(item)
    if (title) {
      if (!itemIndexesByTitleKey.has(title)) itemIndexesByTitleKey.set(title, [])
      itemIndexesByTitleKey.get(title).push(position)
    }
  })

  const claim = (nodeIndex, position) => {
    if (nodeToItem[nodeIndex] >= 0 || itemToNode[position] >= 0) return false
    nodeToItem[nodeIndex] = position
    itemToNode[position] = nodeIndex
    return true
  }
  const claimFirstFree = (nodeIndex, positions) => {
    if (!positions) return false
    return positions.some(position => claim(nodeIndex, position))
  }

  // Pass 1: stable knowledge-graph concept id.
  knowledgeIndexes.forEach(nodeIndex => {
    claimFirstFree(nodeIndex, itemIndexesByGraphKey.get(knowledgeGraphKeyOf(nodes[nodeIndex])))
  })
  // Pass 2: normalized title for nodes/items without a shared concept id.
  knowledgeIndexes.forEach(nodeIndex => {
    if (nodeToItem[nodeIndex] >= 0) return
    claimFirstFree(nodeIndex, itemIndexesByTitleKey.get(titleKeyOf(nodes[nodeIndex])))
  })
  // Pass 3: positional fallback only for whatever remains unmatched, so a
  // partially keyed outline still degrades gracefully instead of freezing.
  const freeNodes = knowledgeIndexes.filter(nodeIndex => nodeToItem[nodeIndex] < 0)
  const freeItems = items.map((_, position) => position).filter(position => itemToNode[position] < 0)
  const fallbackCount = Math.min(freeNodes.length, freeItems.length)
  for (let position = 0; position < fallbackCount; position += 1) {
    claim(freeNodes[position], freeItems[position])
  }

  const indexById = new Map(nodes.map((node, index) => [String(outlineIdOf(node)), index]))
  nodes.forEach((node, index) => {
    if (nodeToItem[index] >= 0) return
    const descendant = knowledgeIndexes.find(knowledgeIndex => (
      knowledgeIndex > index && isDescendantOf(nodes, indexById, knowledgeIndex, index)
    ))
    if (descendant != null) nodeToItem[index] = nodeToItem[descendant]
  })
  return { nodeToItem, itemToNode }
}

/** Resolve the playlist item whose global offset contains the current time. */
export function findPlaylistItemIndexAtTime(items, seconds) {
  if (!Array.isArray(items) || !items.length) return -1
  const timeMs = Math.max(0, Number(seconds) || 0) * 1000
  return items.findIndex(item => {
    const start = Math.max(0, Number(item?.offsetMs) || 0)
    const end = start + Math.max(0, Number(item?.durationMs) || 0)
    return end > start && timeMs >= start && timeMs < end
  })
}

/** Resolve an immutable media release item id without inferring from mutable titles. */
export function findPlaylistItemIndexById(items, itemId) {
  if (!Array.isArray(items) || itemId == null || itemId === '') return -1
  return items.findIndex(item => sameId(item?.itemId, itemId))
}

/** Resolve one keyed playlist item back to the learner rail. */
export function findLearningNodeIndexForPlaylistItem(nodes, item) {
  if (!Array.isArray(nodes) || !item) return -1
  const nodeIdIndex = nodes.findIndex(node => sameId(node?.id, item.nodeId))
  if (nodeIdIndex >= 0) return nodeIdIndex
  return nodes.findIndex(node => sameId(node?.outlineNodeId, item.outlineNodeId))
}

function findTimelineCueForNode(timeline, node) {
  if (!Array.isArray(timeline) || !node) return null
  return timeline.find(cue => (
    sameId(cue?.outlineNodeId, node.outlineNodeId)
    || sameId(cue?.nodeId, node.id)
  )) ?? null
}

/** Resolve a legacy single-audio clock back to one released outline node. */
export function resolveTimelinePlaybackTarget(timeline, nodes, seconds, currentNodeIndex = -1) {
  const targetMs = Math.max(0, Number(seconds) || 0) * 1000
  let activeCue = null
  for (const cue of Array.isArray(timeline) ? timeline : []) {
    if (Math.max(0, Number(cue?.startMs) || 0) > targetMs) break
    activeCue = cue
  }
  const matchedIndex = findLearningNodeIndexForPlaylistItem(nodes, activeCue)
  const fallbackIndex = Number.isInteger(currentNodeIndex)
    && currentNodeIndex >= 0
    && currentNodeIndex < (nodes?.length || 0)
    ? currentNodeIndex
    : -1
  const nodeIndex = matchedIndex >= 0 ? matchedIndex : fallbackIndex
  return {
    nodeIndex,
    nodeId: activeCue?.nodeId ?? null,
    outlineNodeId: activeCue?.outlineNodeId ?? null,
  }
}

/**
 * Project the active audio clock onto the immutable playlist before touching
 * the legacy learner-node timeline. A keyed audio element remains the source
 * of truth for terminal events where a half-open time range has no match.
 */
export function resolvePlaylistPlaybackTarget(items, nodes, seconds, activeIndex = -1) {
  const timedIndex = findPlaylistItemIndexAtTime(items, seconds)
  const fallbackIndex = Number.isInteger(activeIndex)
    && activeIndex >= 0
    && activeIndex < (items?.length || 0)
    ? activeIndex
    : -1
  const playlistIndex = timedIndex >= 0 ? timedIndex : fallbackIndex
  if (playlistIndex < 0) return { playlistIndex: -1, nodeIndex: -1 }
  return {
    playlistIndex,
    nodeIndex: findLearningNodeIndexForPlaylistItem(nodes, items[playlistIndex]),
  }
}

/**
 * Project the immutable media clock onto every learner-facing surface. A
 * published outline intentionally has no legacy media timestamps, so the
 * playlist and frozen PPT cues are the only valid source for this mapping.
 */
export function resolveMediaPlaybackProjection(items, nodes, timeline, seconds, activeIndex = -1) {
  const playlistTarget = resolvePlaylistPlaybackTarget(items, nodes, seconds, activeIndex)
  const timelineTarget = resolveTimelinePlaybackTarget(
    timeline,
    nodes,
    seconds,
    playlistTarget.nodeIndex,
  )
  const playlistItem = playlistTarget.playlistIndex >= 0
    ? items?.[playlistTarget.playlistIndex] ?? null
    : null
  const targetMs = Math.max(0, Number(seconds) || 0) * 1000
  let activeCue = null
  for (const cue of Array.isArray(timeline) ? timeline : []) {
    if (Math.max(0, Number(cue?.startMs) || 0) > targetMs) break
    activeCue = cue
  }

  return {
    playlistIndex: playlistTarget.playlistIndex,
    nodeIndex: playlistTarget.nodeIndex >= 0
      ? playlistTarget.nodeIndex
      : timelineTarget.nodeIndex,
    nodeId: playlistItem?.nodeId ?? timelineTarget.nodeId,
    outlineNodeId: playlistItem?.outlineNodeId ?? timelineTarget.outlineNodeId,
    page: activeCue?.page ?? null,
    materialVersionId: activeCue?.materialVersionId ?? null,
  }
}

/** Resolve a directory click to the playlist clock, with legacy node fallback. */
export function resolvePlaylistSelection(items, node, timeline = []) {
  const playlistIndex = findPlaylistItemIndex(items, node)
  const timelineCue = playlistIndex < 0 ? findTimelineCueForNode(timeline, node) : null
  const targetTime = playlistIndex >= 0
    ? Math.max(0, Number(items[playlistIndex]?.offsetMs) || 0) / 1000
    : timelineCue
      ? Math.max(0, Number(timelineCue.startMs) || 0) / 1000
    : Math.max(0, Number(node?.timestampStart) || 0)
  return { playlistIndex, targetTime }
}

/** Maps the frozen course playlist to one active HTMLAudioElement source. */
export function usePlaylistPlayback(playlist) {
  const activeIndex = ref(0)
  const activeItem = computed(() => playlist.value?.items?.[activeIndex.value] ?? null)
  const activeAudioUrl = computed(() => activeItem.value?.audioUrl ?? '')
  const globalOffsetSeconds = computed(() => (activeItem.value?.offsetMs ?? 0) / 1000)

  function selectByNode(nodeId) {
    const index = playlist.value?.items?.findIndex(item => (
      sameId(item.nodeId, nodeId)
      || sameId(item.outlineNodeId, nodeId)
    )) ?? -1
    if (index >= 0) activeIndex.value = index
    return index >= 0
  }

  function selectByItemId(itemId) {
    const index = findPlaylistItemIndexById(playlist.value?.items, itemId)
    if (index >= 0) activeIndex.value = index
    return index >= 0
  }

  function next() {
    const items = playlist.value?.items ?? []
    if (activeIndex.value >= items.length - 1) return false
    activeIndex.value += 1
    return true
  }

  function previous() {
    if (activeIndex.value <= 0) return false
    activeIndex.value -= 1
    return true
  }

  function seekGlobal(seconds) {
    const index = findPlaylistItemIndexAtTime(playlist.value?.items, seconds)
    if (index < 0) return { changed: false, localSeconds: 0 }
    activeIndex.value = index
    const ms = Math.max(0, Number(seconds) || 0) * 1000
    return { changed: true, localSeconds: Math.max(0, (ms - playlist.value.items[index].offsetMs) / 1000) }
  }

  watch(playlist, () => { activeIndex.value = 0 }, { deep: false })
  return {
    activeIndex,
    activeItem,
    activeAudioUrl,
    globalOffsetSeconds,
    selectByNode,
    selectByItemId,
    next,
    previous,
    seekGlobal,
  }
}
