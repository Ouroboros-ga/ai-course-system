import { computed, ref, watch } from 'vue'

/** Maps the frozen course playlist to one active HTMLAudioElement source. */
export function usePlaylistPlayback(playlist) {
  const activeIndex = ref(0)
  const activeItem = computed(() => playlist.value?.items?.[activeIndex.value] ?? null)
  const activeAudioUrl = computed(() => activeItem.value?.audioUrl ?? '')
  const globalOffsetSeconds = computed(() => (activeItem.value?.offsetMs ?? 0) / 1000)

  function selectByNode(nodeId) {
    const index = playlist.value?.items?.findIndex(item => (
      String(item.nodeId) === String(nodeId)
      || String(item.outlineNodeId) === String(nodeId)
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
    const ms = Math.max(0, Number(seconds) || 0) * 1000
    const index = playlist.value?.items?.findIndex(item => ms >= item.offsetMs && ms < item.offsetMs + item.durationMs) ?? -1
    if (index < 0) return { changed: false, localSeconds: 0 }
    activeIndex.value = index
    return { changed: true, localSeconds: Math.max(0, (ms - playlist.value.items[index].offsetMs) / 1000) }
  }

  watch(playlist, () => { activeIndex.value = 0 }, { deep: false })
  return { activeIndex, activeItem, activeAudioUrl, globalOffsetSeconds, selectByNode, next, previous, seekGlobal }
}
