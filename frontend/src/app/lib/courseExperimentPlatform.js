/**
 * The only experiment implementation currently available to a course is the
 * code sandbox. Keep the navigation gate explicit so future non-code labs can
 * introduce their own capability instead of accidentally exposing this UI.
 */
export function isCodeSandboxExperimentPlatformEnabled(capabilities = {}) {
  return Boolean(capabilities.experiment && capabilities.coding_sandbox)
}

/**
 * The current experiment platform is atomic: enabling it exposes both the
 * experiment workflow and the code-execution runtime; disabling it removes
 * both. This avoids an experiment entry that cannot execute any task.
 */
export function withCodeSandboxExperimentPlatform(capabilities = {}, enabled) {
  const platformEnabled = Boolean(enabled)

  return {
    ...capabilities,
    experiment: platformEnabled,
    coding_sandbox: platformEnabled,
  }
}
