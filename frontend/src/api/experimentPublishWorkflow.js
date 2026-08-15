export function resolveExperimentWizardStage(definition) {
  if (definition?.publish_status === 'published') return 'complete'
  return definition?.default_version_id ? 'preview' : 'version'
}
