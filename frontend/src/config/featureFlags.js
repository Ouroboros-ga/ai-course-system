function readBooleanFlag(value) {
  return String(value ?? '').trim().toLowerCase() === 'true'
}

const viteEnv = import.meta.env ?? {}

export const featureFlags = Object.freeze({
  studentLearningWorkspace: readBooleanFlag(
    viteEnv.VITE_ENABLE_STUDENT_LEARNING_WORKSPACE
  ),
  // Keep the established teacher Dashboard as the production fallback while
  // the course production workspace is rolled out and verified separately.
  teacherProductionWorkspace: readBooleanFlag(
    viteEnv.VITE_ENABLE_TEACHER_PRODUCTION_WORKSPACE
  ),
  // Mapping governance is independently gated because it depends on the
  // existing Mapping API but deliberately excludes future Evidence/Graph UI.
  knowledgeMappingWorkspace: readBooleanFlag(
    viteEnv.VITE_ENABLE_KNOWLEDGE_MAPPING_WORKSPACE
  ),
  // Graph browser is independently gated. It only renders data provable by
  // real endpoints (mapping + evidence-v2); the retrieval-trace layer is not
  // fabricated while the V2 shadow is unwired/unreleased.
  graphBrowser: readBooleanFlag(
    viteEnv.VITE_ENABLE_GRAPH_BROWSER
  ),
  // Shadow-1 is a separate local demonstration surface. It never changes the
  // default student/chat route and remains visibly disabled unless opt-in.
  retrievalDemo: readBooleanFlag(
    viteEnv.VITE_ENABLE_RETRIEVAL_DEMO
  ),
})

export { readBooleanFlag }
