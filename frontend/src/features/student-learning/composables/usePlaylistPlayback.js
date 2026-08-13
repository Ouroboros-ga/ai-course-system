import { computed, ref, watch } from 'vue'

function sameId(left, right) {
  return left != null && right != null && String(left) === String(right)
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

/** Resolve an immutable media release item id without inferring from mutable titles. */
export function findPlaylistItemIndexById(items, itemId) {
  if (!Array.isArray(items) || itemId == null || itemId === '') return -1
  return items.findIndex(item => sameId(item?.itemId, itemId))
}

/** Resolve a directory click to the playlist clock, with legacy node fallback. */
export function resolvePlaylistSelection(items, node) {
  const playlistIndex = findPlaylistItemIndex(items, node)
  const targetTime = playlistIndex >= 0
    ? Math.max(0, Number(items[playlistIndex]?.offsetMs) || 0) / 1000
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
