<template>
  <div class="student-memory-manager">
    <h2 class="student-memory-manager__title">{{ title }}</h2>

    <!-- Memory enable/disable toggle -->
    <section class="student-memory-manager__section">
      <div class="student-memory-manager__toggle-row">
        <span class="student-memory-manager__toggle-label">
          Course Memory
        </span>
        <label class="student-memory-manager__toggle">
          <input
            type="checkbox"
            :checked="memoryEnabled"
            @change="toggleMemory"
          />
          <span class="student-memory-manager__toggle-slider"></span>
        </label>
        <span class="student-memory-manager__toggle-status">
          {{ memoryEnabled ? 'Enabled' : 'Disabled' }}
        </span>
      </div>
      <p class="student-memory-manager__description">
        When disabled, memory is neither read nor written for this course.
      </p>
    </section>

    <!-- Student Profile -->
    <section class="student-memory-manager__section">
      <h3 class="student-memory-manager__section-title">Student Profile</h3>
      <div v-if="profile" class="student-memory-manager__profile">
        <div class="student-memory-manager__profile-field">
          <span class="student-memory-manager__field-label">Background:</span>
          <span>{{ profile.known_background || 'Not specified' }}</span>
        </div>
        <div class="student-memory-manager__profile-field">
          <span class="student-memory-manager__field-label">Learning Style:</span>
          <span>{{ profile.learning_style || 'Not specified' }}</span>
        </div>
        <div class="student-memory-manager__profile-field">
          <span class="student-memory-manager__field-label">Goals:</span>
          <span v-if="profile.goals && profile.goals.length > 0">
            {{ profile.goals.join(', ') }}
          </span>
          <span v-else>No goals set</span>
        </div>
      </div>
      <p v-else class="student-memory-manager__empty">No profile data available.</p>
    </section>

    <!-- Memory Entries -->
    <section class="student-memory-manager__section">
      <h3 class="student-memory-manager__section-title">
        Memory Entries ({{ entries.length }})
      </h3>
      <div v-if="entries.length === 0" class="student-memory-manager__empty">
        No memory entries available.
      </div>
      <div
        v-for="entry in entries"
        :key="entry.entry_id"
        class="student-memory-manager__entry-card"
      >
        <div class="student-memory-manager__entry-header">
          <span class="student-memory-manager__entry-type">
            {{ entry.memory_type }}
          </span>
          <span class="student-memory-manager__entry-source">
            {{ entry.source }}
          </span>
          <span
            class="student-memory-manager__entry-confidence"
            :style="{ color: confidenceColor(entry.confidence) }"
          >
            {{ (entry.confidence * 100).toFixed(0) }}%
          </span>
        </div>
        <p class="student-memory-manager__entry-content">
          {{ entry.content }}
        </p>
        <div class="student-memory-manager__entry-meta">
          <span
            v-if="entry.evidence_refs && entry.evidence_refs.length > 0"
            class="student-memory-manager__entry-refs"
          >
            Evidence: {{ entry.evidence_refs.length }} reference(s)
          </span>
          <span class="student-memory-manager__entry-reason">
            {{ entry.generation_reason }}
          </span>
        </div>
        <div class="student-memory-manager__entry-actions">
          <button
            class="student-memory-manager__btn student-memory-manager__btn--danger"
            @click="requestDeletion(entry)"
            :disabled="!memoryEnabled"
          >
            Soft Delete
          </button>
        </div>
      </div>
    </section>

    <!-- Deletion confirmation dialog -->
    <div v-if="pendingDeletion" class="student-memory-manager__modal-overlay">
      <div class="student-memory-manager__modal">
        <h3>Confirm Deletion</h3>
        <p>
          Are you sure you want to delete this memory entry?
          This action can be audited.
        </p>
        <p class="student-memory-manager__modal-entry">
          "{{ pendingDeletion.content }}"
        </p>
        <div class="student-memory-manager__modal-actions">
          <button
            class="student-memory-manager__btn student-memory-manager__btn--danger"
            @click="confirmDeletion"
          >
            Delete
          </button>
          <button
            class="student-memory-manager__btn"
            @click="cancelDeletion"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>

    <!-- Error display -->
    <div v-if="error" class="student-memory-manager__error">
      {{ error }}
    </div>
  </div>
</template>

<script>
/**
 * StudentMemoryManager - isolated frontend feature for student memory.
 *
 * This component displays student profile, memory entries, and memory
 * enable/disable controls for a specific student+course scope.
 *
 * Props: studentId, courseId (integers)
 * Does NOT depend on router/request.js or existing dashboards.
 */

const MEMORY_VERSION = '1.0'

export default {
  name: 'StudentMemoryManager',
  props: {
    studentId: {
      type: Number,
      required: true,
    },
    courseId: {
      type: Number,
      required: true,
    },
    title: {
      type: String,
      default: 'Student Memory Manager',
    },
  },
  data() {
    return {
      memoryEnabled: true,
      profile: null,
      entries: [],
      pendingDeletion: null,
      error: null,
    }
  },
  methods: {
    confidenceColor(confidence) {
      if (confidence >= 0.8) return 'var(--color-success)'
      if (confidence >= 0.5) return 'var(--color-warning)'
      return 'var(--color-danger)'
    },
    toggleMemory(event) {
      this.memoryEnabled = event.target.checked
      if (!this.memoryEnabled) {
        this.profile = null
        this.entries = []
      }
    },
    requestDeletion(entry) {
      this.pendingDeletion = entry
    },
    confirmDeletion() {
      if (!this.pendingDeletion) return
      this.entries = this.entries.filter(
        (e) => e.entry_id !== this.pendingDeletion.entry_id
      )
      this.pendingDeletion = null
    },
    cancelDeletion() {
      this.pendingDeletion = null
    },
  },
}
</script>

<style scoped>
.student-memory-manager {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
  color: #333;
}

.student-memory-manager__title {
  font-size: 1.5rem;
  font-weight: 600;
  margin-bottom: 20px;
  color: #1a1a2e;
}

.student-memory-manager__section {
  margin-bottom: 24px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

.student-memory-manager__section-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 12px;
  color: #334155;
}

.student-memory-manager__description {
  font-size: 0.85rem;
  color: #64748b;
  margin-top: 8px;
}

.student-memory-manager__empty {
  color: #94a3b8;
  font-style: italic;
  padding: 12px 0;
}

.student-memory-manager__toggle-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.student-memory-manager__toggle-label {
  font-weight: 500;
}

.student-memory-manager__toggle {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
}

.student-memory-manager__toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.student-memory-manager__toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #cbd5e1;
  border-radius: 24px;
  transition: 0.3s;
}

.student-memory-manager__toggle input:checked + .student-memory-manager__toggle-slider {
  background-color: #3b82f6;
}

.student-memory-manager__toggle-slider::before {
  content: '';
  position: absolute;
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

.student-memory-manager__toggle input:checked + .student-memory-manager__toggle-slider::before {
  transform: translateX(20px);
}

.student-memory-manager__toggle-status {
  font-size: 0.9rem;
  font-weight: 500;
  color: #64748b;
}

.student-memory-manager__profile-field {
  margin-bottom: 8px;
  line-height: 1.5;
}

.student-memory-manager__field-label {
  font-weight: 500;
  color: #475569;
  margin-right: 8px;
}

.student-memory-manager__entry-card {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
  background: #f8fafc;
}

.student-memory-manager__entry-header {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.student-memory-manager__entry-type {
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  color: #3b82f6;
  background: #eff6ff;
  padding: 2px 8px;
  border-radius: 4px;
}

.student-memory-manager__entry-source {
  font-size: 0.8rem;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 4px;
}

.student-memory-manager__entry-confidence {
  font-size: 0.85rem;
  font-weight: 600;
  margin-left: auto;
}

.student-memory-manager__entry-content {
  font-size: 0.95rem;
  line-height: 1.5;
  margin-bottom: 8px;
  color: #1e293b;
}

.student-memory-manager__entry-meta {
  font-size: 0.8rem;
  color: #64748b;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.student-memory-manager__entry-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.student-memory-manager__btn {
  padding: 6px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #ffffff;
  color: #334155;
  cursor: pointer;
  font-size: 0.85rem;
  transition: 0.2s;
}

.student-memory-manager__btn:hover {
  background: #f1f5f9;
}

.student-memory-manager__btn--danger {
  border-color: #fca5a5;
  color: #dc2626;
}

.student-memory-manager__btn--danger:hover {
  background: #fef2f2;
}

.student-memory-manager__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.student-memory-manager__modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.student-memory-manager__modal {
  background: white;
  padding: 24px;
  border-radius: 8px;
  max-width: 500px;
  width: 90%;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
}

.student-memory-manager__modal h3 {
  margin-bottom: 12px;
  color: #1e293b;
}

.student-memory-manager__modal p {
  margin-bottom: 12px;
  color: #475569;
  line-height: 1.5;
}

.student-memory-manager__modal-entry {
  font-style: italic;
  color: #64748b;
  background: #f1f5f9;
  padding: 8px 12px;
  border-radius: 4px;
}

.student-memory-manager__modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
}

.student-memory-manager__error {
  margin-top: 16px;
  padding: 12px;
  background: #fef2f2;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  color: #dc2626;
  font-size: 0.9rem;
}
</style>
