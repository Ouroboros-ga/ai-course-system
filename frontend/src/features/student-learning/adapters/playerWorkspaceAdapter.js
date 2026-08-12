const numberOr = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

function normalizeNode(raw, index) {
  const start = Math.max(0, numberOr(raw?.timestamp_start ?? raw?.timestampStart))
  const duration = Math.max(0, numberOr(raw?.duration))
  const endCandidate = numberOr(raw?.timestamp_end ?? raw?.timestampEnd, start + duration)
  const end = Math.max(start, endCandidate)
  const pageStart = Math.max(1, numberOr(raw?.page_start ?? raw?.pageStart, 1))
  const pageEnd = Math.max(pageStart, numberOr(raw?.page_end ?? raw?.pageEnd, pageStart))

  return {
    id: raw?.id ?? raw?.node_id ?? index + 1,
    outlineNodeId: raw?.outline_node_id ?? raw?.outlineNodeId ?? null,
    index,
    sourceIndex: numberOr(raw?.node_index ?? raw?.nodeIndex, index + 1),
    type: raw?.node_type ?? raw?.nodeType ?? 'lecture',
    title: String(raw?.title || '知识点 ' + (index + 1)),
    content: String(raw?.content || ''),
    chapterId: raw?.chapter_id ?? raw?.chapterId ?? null,
    timestampStart: start,
    timestampEnd: end,
    duration: duration || Math.max(0, end - start),
    pageStart,
    pageEnd,
    isKeyPoint: Boolean(raw?.is_key_point ?? raw?.isKeyPoint),
    videoUrl: String(raw?.video_url ?? raw?.videoUrl ?? ''),
    mediaStatus: raw?.status ?? (raw?.video_url ? 'ready' : 'unavailable'),
  }
}

function normalizeSlides(rawSlides) {
  if (!Array.isArray(rawSlides)) return []
  return rawSlides
    .map((slide, index) => ({
      page: Math.max(1, numberOr(slide?.page ?? slide?.page_no, index + 1)),
      url: String(slide?.url || ''),
    }))
    .filter(slide => slide.url)
    .sort((a, b) => a.page - b.page)
}

function normalizePptPages(rawPages) {
  if (!Array.isArray(rawPages)) return []
  return rawPages
    .map((page, index) => ({
      page: Math.max(1, numberOr(page?.page_no ?? page?.page, index + 1)),
      title: String(page?.title || ''),
      content: String(page?.text ?? page?.content ?? ''),
    }))
    .sort((a, b) => a.page - b.page)
}

function normalizeCompletionRate(value) {
  const parsed = numberOr(value)
  return clamp(parsed <= 1 ? parsed * 100 : parsed, 0, 100)
}

export function findNodeIndexAtTime(nodes, timestamp, fallbackIndex = 0) {
  if (!Array.isArray(nodes) || nodes.length === 0) return 0
  // Immutable course releases no longer own a legacy media timeline. Their
  // nodes intentionally arrive as 0/0 markers while audio-playlist/v1 owns
  // playback. Do not let binary search turn every positive time into the last
  // node when a caller has to use this legacy fallback.
  if (nodes.every(node => Number(node?.timestampStart) === 0 && Number(node?.timestampEnd) === 0)) {
    return clamp(Number(fallbackIndex) || 0, 0, nodes.length - 1)
  }
  const time = Math.max(0, numberOr(timestamp))
  let left = 0
  let right = nodes.length - 1

  while (left <= right) {
    const middle = Math.floor((left + right) / 2)
    const node = nodes[middle]
    if (time < node.timestampStart) {
      right = middle - 1
    } else if (time > node.timestampEnd) {
      left = middle + 1
    } else {
      return middle
    }
  }

  return clamp(left, 0, nodes.length - 1)
}

export function resolvePageAtTime(node, timestamp) {
  if (!node) return 1
  if (node.pageStart === node.pageEnd || node.timestampEnd <= node.timestampStart) {
    return node.pageStart
  }
  const ratio = clamp(
    (numberOr(timestamp) - node.timestampStart) /
      (node.timestampEnd - node.timestampStart),
    0,
    0.999999
  )
  const pageCount = node.pageEnd - node.pageStart + 1
  return node.pageStart + Math.floor(ratio * pageCount)
}

export function normalizePlayerData(rawResponse) {
  const raw = rawResponse?.data ?? rawResponse ?? {}
  const nodes = Array.isArray(raw.nodes)
    ? raw.nodes.map(normalizeNode).sort((a, b) => a.sourceIndex - b.sourceIndex)
    : []

  nodes.forEach((node, index) => {
    node.index = index
  })

  const slides = normalizeSlides(raw.slide_images ?? raw.slideImages)
  const pptPages = normalizePptPages(raw.ppt_pages ?? raw.pptPages)
  const saved = raw.saved_progress ?? raw.savedProgress ?? {}
  const savedTime = Math.max(0, numberOr(saved.current_timestamp ?? saved.currentTimestamp))
  const savedIndexCandidate = numberOr(
    saved.current_node_index ?? saved.currentNodeIndex,
    findNodeIndexAtTime(nodes, savedTime)
  )
  const currentNodeIndex = nodes.length
    ? clamp(savedIndexCandidate, 0, nodes.length - 1)
    : 0
  const currentNode = nodes[currentNodeIndex]

  return {
    courseId: numberOr(raw.course_id ?? raw.courseId),
    courseTitle: String(raw.course_title ?? raw.courseTitle ?? '未命名课程'),
    scriptId: numberOr(raw.script_id ?? raw.scriptId),
    contentStatus: String(raw.content_status ?? raw.contentStatus ?? 'ready'),
    contentMessage: String(raw.content_message ?? raw.contentMessage ?? ''),
    totalDuration: Math.max(
      numberOr(raw.total_duration ?? raw.totalDuration),
      nodes.at(-1)?.timestampEnd || 0
    ),
    totalNodes: numberOr(raw.total_nodes ?? raw.totalNodes, nodes.length),
    nodes,
    slides,
    pptPages,
    savedProgress: {
      currentNodeIndex,
      currentNodeId: saved.current_node_id ?? saved.currentNodeId ?? currentNode?.id ?? null,
      currentTime: savedTime,
      currentPage: Math.max(
        1,
        numberOr(
          saved.current_page ?? saved.currentPage,
          resolvePageAtTime(currentNode, savedTime)
        )
      ),
      completionRate: normalizeCompletionRate(
        saved.completion_rate ?? saved.completionRate
      ),
      lastAccessedAt: saved.last_accessed_at ?? saved.lastAccessedAt ?? null,
      completedNodeIds: Array.isArray(saved.completed_node_ids ?? saved.completedNodeIds)
        ? (saved.completed_node_ids ?? saved.completedNodeIds)
        : [],
    },
    releaseId: raw.release_id ?? raw.releaseId ?? null,
  }
}

export function withAccessToken(url, token) {
  if (!url || !token || /([?&])token=/.test(url)) return url
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token)
}

export function buildProgressPayload(state) {
  const payload = {
    course_id: numberOr(state.courseId),
    current_node_id: state.currentNodeId ?? null,
    current_timestamp: Math.max(0, numberOr(state.currentTime)),
    current_page: Math.max(1, numberOr(state.currentPage, 1)),
    completed_nodes: Array.isArray(state.completedNodes)
      ? state.completedNodes.filter(id => id !== null && id !== undefined)
      : [],
    // 听课时长埋点：本次保存周期内新增的听课秒数（仅 playing 时累计）。
    // 后端累加到 NodeProgress.time_spent，供认知引擎 evidence_confidence 佐证。
    // 上限 60 秒，与后端校验一致，避免后台标签页长时间未保存的跳变。
  }
  if (state.timeSpentDelta !== undefined && state.timeSpentDelta !== null) {
    payload.time_spent_delta = clamp(numberOr(state.timeSpentDelta, 0), 0, 60) // time_spent_delta
  }
  return payload
}
