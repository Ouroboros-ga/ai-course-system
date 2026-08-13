import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveExperimentWizardStage } from '../experimentPublishWorkflow.js'

test('draft without a version resumes at version and test authoring', () => {
  assert.equal(resolveExperimentWizardStage({ publish_status: 'draft', default_version_id: null }), 'version')
})

test('draft with an active version resumes at reference preview', () => {
  assert.equal(resolveExperimentWizardStage({ publish_status: 'draft', default_version_id: 'expv-1' }), 'preview')
})

test('published definition is a completed read-only workflow', () => {
  assert.equal(resolveExperimentWizardStage({ publish_status: 'published', default_version_id: 'expv-1' }), 'complete')
})
