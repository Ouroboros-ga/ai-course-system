function readBooleanFlag(value) {
  return String(value ?? '').trim().toLowerCase() === 'true'
}

const viteEnv = import.meta.env ?? {}

export const featureFlags = Object.freeze({
  studentLearningWorkspace: readBooleanFlag(
    viteEnv.VITE_ENABLE_STUDENT_LEARNING_WORKSPACE
  ),
})

export { readBooleanFlag }
