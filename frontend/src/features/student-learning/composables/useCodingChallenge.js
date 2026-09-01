import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  closeCodingChallenge,
  createCodingChallengeRun,
  dismissCodingChallenge,
  getActiveCodingChallenge,
  getCodingChallengeOffer,
  getCodingChallengeRun,
  revealCodingChallengeHint,
  replaceCodingChallenge,
  startCodingChallenge,
} from '@/api/coding_challenges.js'

const TERMINAL_OUTCOMES = new Set([
  'accepted',
  'wrong_answer',
  'time_limit_exceeded',
  'memory_limit_exceeded',
  'runtime_error',
  'compilation_error',
  'internal_error',
  'sandbox_unavailable',
])

function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `coding-challenge-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function wait(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function outcomeOf(view) {
  return view?.result?.outcome || view?.result?.status || ''
}

export function useCodingChallenge(courseId, conversationSessionId, options = {}) {
  const offer = ref(null)
  const session = ref(null)
  const sourceCode = ref('')
  const language = ref('python3')
  const runView = ref(null)
  const busy = ref(false)
  const hintBusy = ref(false)
  const error = ref('')
  let offerPollGeneration = 0
  let runPollGeneration = 0

  const canRun = computed(() => (
    session.value?.status === 'in_progress'
    && sourceCode.value.trim().length > 0
    && !busy.value
  ))

  function draftStorageKey(sessionId) {
    return `sfx:coding-challenge:draft:${courseId}:${sessionId}`
  }

  function restoreDraft(nextSession) {
    if (!nextSession?.session_id) return nextSession?.starter_code || ''
    try {
      return window.sessionStorage.getItem(draftStorageKey(nextSession.session_id))
        ?? nextSession.starter_code
        ?? ''
    } catch {
      return nextSession.starter_code || ''
    }
  }

  function syncOffer(nextOffer) {
    const previousOfferId = offer.value?.offer_id || null
    offer.value = nextOffer || null
    options.onOfferUpdate?.(offer.value, previousOfferId)
  }

  async function pollOffer(expectedOfferId) {
    const generation = ++offerPollGeneration
    while (generation === offerPollGeneration && offer.value?.status === 'preparing') {
      await wait(1500)
      if (generation !== offerPollGeneration) return
      const next = await getCodingChallengeOffer(courseId, expectedOfferId)
      syncOffer(next)
    }
  }

  function adoptOffer(nextOffer) {
    if (!nextOffer?.offer_id) return
    const changed = offer.value?.offer_id !== nextOffer.offer_id
      || offer.value?.status !== nextOffer.status
    if (changed) syncOffer({ ...nextOffer })
    if (changed && nextOffer.status === 'preparing') {
      pollOffer(nextOffer.offer_id).catch(() => {
        error.value = '代码挑战仍在准备中，可以稍后再试。'
      })
    }
  }

  async function restore() {
    try {
      const active = await getActiveCodingChallenge(courseId, conversationSessionId)
      syncOffer(active?.offer || null)
      session.value = active?.session || null
      if (session.value) {
        language.value = session.value.language || session.value.languages?.[0] || 'python3'
        sourceCode.value = restoreDraft(session.value)
        runView.value = session.value.latest_run || null
        const latestRunId = runView.value?.result?.run_id
        const latestOutcome = outcomeOf(runView.value)
        const feedbackPending = runView.value?.diagnosis_status === 'preparing'
        if (
          latestRunId
          && session.value.status === 'in_progress'
          && (!TERMINAL_OUTCOMES.has(latestOutcome) || feedbackPending)
        ) {
          const generation = ++runPollGeneration
          busy.value = true
          pollRun(latestRunId, generation)
            .then(completed => {
              if (completed?.result?.outcome === 'accepted' && session.value) {
                session.value = { ...session.value, status: 'finalized' }
              }
            })
            .catch(() => {
              error.value = '运行结果已恢复，但教学反馈暂时未完成。'
            })
            .finally(() => {
              if (generation === runPollGeneration) busy.value = false
            })
        }
      }
      if (offer.value?.status === 'preparing') pollOffer(offer.value.offer_id).catch(() => {})
      return active
    } catch {
      return null
    }
  }

  async function start(returnAnchor) {
    if (!offer.value?.offer_id || offer.value.status !== 'ready') return null
    busy.value = true
    error.value = ''
    try {
      const active = await startCodingChallenge(courseId, offer.value.offer_id, returnAnchor)
      syncOffer(active.offer)
      session.value = active.session
      language.value = active.session?.language || active.session?.languages?.[0] || 'python3'
      sourceCode.value = restoreDraft(active.session)
      return active
    } catch (startError) {
      error.value = startError?.message || '代码挑战暂时无法开始。'
      return null
    } finally {
      busy.value = false
    }
  }

  async function dismiss() {
    if (!offer.value?.offer_id) return
    busy.value = true
    try {
      syncOffer(await dismissCodingChallenge(courseId, offer.value.offer_id))
    } finally {
      busy.value = false
    }
  }

  async function replace() {
    if (!offer.value?.offer_id) return
    busy.value = true
    error.value = ''
    try {
      syncOffer(await replaceCodingChallenge(courseId, offer.value.offer_id))
      if (offer.value?.status === 'preparing') pollOffer(offer.value.offer_id).catch(() => {})
    } catch (replaceError) {
      error.value = replaceError?.message || '暂时无法更换题目。'
    } finally {
      busy.value = false
    }
  }

  async function pollRun(runId, generation) {
    let terminalFeedbackPolls = 0
    while (generation === runPollGeneration) {
      const next = await getCodingChallengeRun(courseId, runId)
      runView.value = next
      const outcome = outcomeOf(next)
      if (TERMINAL_OUTCOMES.has(outcome)) {
        if (next?.diagnosis_status && next.diagnosis_status !== 'preparing') return next
        terminalFeedbackPolls += 1
        // Judge0 result is already visible. Keep a bounded grace window for
        // the separate source-free TeachingAgent feedback transaction.
        if (terminalFeedbackPolls >= 8) return next
        await wait(500)
      } else {
        await wait(1000)
      }
    }
    return null
  }

  async function run() {
    if (!canRun.value) return null
    busy.value = true
    error.value = ''
    runView.value = null
    try {
      const created = await createCodingChallengeRun(
        courseId,
        session.value.session_id,
        { language: language.value, source_code: sourceCode.value },
        newIdempotencyKey(),
      )
      const generation = ++runPollGeneration
      const completed = await pollRun(created.run_id, generation)
      if (completed?.result?.outcome === 'accepted' && session.value) {
        session.value = { ...session.value, status: 'finalized' }
      }
      return completed
    } catch (runError) {
      error.value = runError?.message || '本次运行没有完成，请稍后重试。'
      return null
    } finally {
      busy.value = false
    }
  }

  async function revealHint() {
    const runId = runView.value?.result?.run_id
    if (!runId || !runView.value?.optional_hint_available || hintBusy.value) return null
    hintBusy.value = true
    error.value = ''
    try {
      const revealed = await revealCodingChallengeHint(courseId, runId)
      runView.value = revealed
      return revealed
    } catch (hintError) {
      error.value = hintError?.message || '可选提示暂时无法加载。'
      return null
    } finally {
      hintBusy.value = false
    }
  }

  async function close(reason = 'returned_to_course') {
    if (!session.value?.session_id) return null
    ++runPollGeneration
    busy.value = true
    try {
      const result = await closeCodingChallenge(courseId, session.value.session_id, reason)
      session.value = { ...session.value, status: result?.attempt_status || 'finalized' }
      return result
    } finally {
      busy.value = false
    }
  }

  watch(sourceCode, value => {
    if (!session.value?.session_id) return
    try {
      window.sessionStorage.setItem(draftStorageKey(session.value.session_id), value)
    } catch {
      // A browser draft is only a refresh recovery aid; the server evidence remains authoritative.
    }
  })

  onBeforeUnmount(() => {
    ++offerPollGeneration
    ++runPollGeneration
  })

  return {
    offer,
    session,
    sourceCode,
    language,
    runView,
    busy,
    hintBusy,
    error,
    canRun,
    adoptOffer,
    restore,
    start,
    dismiss,
    replace,
    run,
    revealHint,
    close,
  }
}
