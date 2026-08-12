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
  return { activeIndex, activeItem, activeAudioUrl, globalOffsetSeconds, selectByNode, next, previous, seekGlobal }
}
