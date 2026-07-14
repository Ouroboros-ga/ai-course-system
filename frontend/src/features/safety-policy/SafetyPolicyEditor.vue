<template>
  <div class="safety-policy-editor">
    <h2 class="safety-policy-editor__title">{{ title }}</h2>

    <!-- Platform policy (read-only summary) -->
    <section class="safety-policy-editor__section">
      <h3 class="safety-policy-editor__section-title">
        Platform Safety Policy
        <span class="safety-policy-editor__badge">Immutable</span>
      </h3>
      <p class="safety-policy-editor__description">
        Platform-level safety rules that cannot be disabled by course settings.
      </p>
      <table class="safety-policy-editor__table" v-if="platformRules.length > 0">
        <thead>
          <tr>
            <th>Rule ID</th>
            <th>Action</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rule in platformRules" :key="rule.rule_id">
            <td><code>{{ rule.rule_id }}</code></td>
            <td>{{ rule.action }}</td>
            <td>{{ rule.description }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="safety-policy-editor__empty">No platform rules defined.</p>
    </section>

    <!-- Course-level policy (editable) -->
    <section class="safety-policy-editor__section">
      <h3 class="safety-policy-editor__section-title">Course Safety Rules</h3>
      <p class="safety-policy-editor__description">
        Configure course-specific safety rules. These cannot override platform rules.
      </p>

      <div class="safety-policy-editor__actions">
        <button class="safety-policy-editor__btn" @click="addKeywordRule">
          + Add Keyword Rule
        </button>
        <button class="safety-policy-editor__btn" @click="addRegexRule">
          + Add Regex Rule
        </button>
      </div>

      <div v-if="courseRules.length === 0" class="safety-policy-editor__empty">
        No course rules configured.
      </div>

      <div
        v-for="(rule, index) in courseRules"
        :key="index"
        class="safety-policy-editor__rule-card"
      >
        <div class="safety-policy-editor__rule-header">
          <strong>Rule #{{ index + 1 }}</strong>
          <button
            class="safety-policy-editor__btn safety-policy-editor__btn--danger"
            @click="removeRule(index)"
          >
            Remove
          </button>
        </div>

        <!-- Rule type selector -->
        <div class="safety-policy-editor__field">
          <label>Type:</label>
          <select v-model="rule.rule_type" disabled>
            <option value="keyword">Keyword</option>
            <option value="regex">Regex</option>
          </select>
        </div>

        <!-- Action selector -->
        <div class="safety-policy-editor__field">
          <label>Action:</label>
          <select v-model="rule.action">
            <option value="deny">Deny</option>
            <option value="restrict">Restrict</option>
            <option value="require-citation">Require Citation</option>
            <option value="homework-answer">Homework Answer (Hint Only)</option>
          </select>
        </div>

        <!-- Keywords (for keyword rules) -->
        <div class="safety-policy-editor__field" v-if="rule.rule_type === 'keyword'">
          <label>Keywords (comma-separated):</label>
          <input
            type="text"
            v-model="rule.keywords"
            placeholder="e.g., exam answer, quiz solution"
          />
        </div>

        <!-- Pattern (for regex rules) -->
        <div class="safety-policy-editor__field" v-if="rule.rule_type === 'regex'">
          <label>Regex Pattern:</label>
          <input
            type="text"
            v-model="rule.pattern"
            placeholder="e.g., \b(quiz|exam)\s+answer\b"
          />
        </div>

        <!-- Match type (for regex rules) -->
        <div class="safety-policy-editor__field" v-if="rule.rule_type === 'regex'">
          <label>Match Type:</label>
          <select v-model="rule.match_type">
            <option value="search">Search</option>
            <option value="fullmatch">Full Match</option>
          </select>
        </div>

        <!-- Enabled toggle -->
        <div class="safety-policy-editor__field safety-policy-editor__field--inline">
          <label>
            <input type="checkbox" v-model="rule.enabled" />
            Enabled
          </label>
        </div>

        <!-- Description -->
        <div class="safety-policy-editor__field">
          <label>Description:</label>
          <input
            type="text"
            v-model="rule.description"
            placeholder="Why this rule exists"
          />
        </div>
      </div>
    </section>

    <!-- Save / Reset -->
    <div class="safety-policy-editor__footer">
      <button
        class="safety-policy-editor__btn safety-policy-editor__btn--primary"
        @click="savePolicy"
        :disabled="saving"
      >
        {{ saving ? 'Saving...' : 'Save Policy' }}
      </button>
      <button
        class="safety-policy-editor__btn"
        @click="resetPolicy"
        :disabled="saving"
      >
        Reset
      </button>
      <span v-if="saveMessage" class="safety-policy-editor__message">
        {{ saveMessage }}
      </span>
    </div>
  </div>
</template>

<script>
/**
 * SafetyPolicyEditor - Independent teacher safety-policy configuration component.
 *
 * This component is designed to be mounted independently by P1-09.
 * It does NOT import router/index.js or utils/request.js.
 * All API calls are made through an injected `apiClient` or the provided
 * `savePolicy` / `loadPolicy` props.
 */
export default {
  name: "SafetyPolicyEditor",
  props: {
    title: {
      type: String,
      default: "Safety Policy Settings",
    },
    /** Array of platform rule objects (read-only display) */
    platformRules: {
      type: Array,
      default: () => [],
    },
    /** Array of course rule objects (editable) */
    courseRules: {
      type: Array,
      default: () => [],
    },
    /** Called when user clicks Save */
    onSave: {
      type: Function,
      default: null,
    },
    /** Called when user clicks Reset */
    onReset: {
      type: Function,
      default: null,
    },
    saving: {
      type: Boolean,
      default: false,
    },
  },
  emits: ["save", "reset", "update:courseRules"],
  data() {
    return {
      localCourseRules: [],
      saveMessage: "",
    };
  },
  watch: {
    courseRules: {
      immediate: true,
      handler(val) {
        this.localCourseRules = JSON.parse(JSON.stringify(val || []));
      },
    },
  },
  methods: {
    addKeywordRule() {
      this.localCourseRules.push({
        rule_type: "keyword",
        action: "deny",
        keywords: "",
        enabled: true,
        description: "",
      });
    },
    addRegexRule() {
      this.localCourseRules.push({
        rule_type: "regex",
        action: "deny",
        pattern: "",
        match_type: "search",
        enabled: true,
        description: "",
      });
    },
    removeRule(index) {
      this.localCourseRules.splice(index, 1);
    },
    async savePolicy() {
      this.saveMessage = "";
      if (this.onSave) {
        try {
          await this.onSave(this.localCourseRules);
          this.saveMessage = "Policy saved successfully.";
        } catch (e) {
          this.saveMessage = `Error: ${e.message || "Save failed"}`;
        }
      } else {
        this.$emit("save", this.localCourseRules);
        this.saveMessage = "Policy saved (no external handler).";
      }
    },
    resetPolicy() {
      this.saveMessage = "";
      if (this.onReset) {
        this.onReset();
      } else {
        this.$emit("reset");
        // Reset to original courseRules
        this.localCourseRules = JSON.parse(
          JSON.stringify(this.$props.courseRules || [])
        );
      }
    },
  },
};
</script>

<style scoped>
.safety-policy-editor {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 800px;
  margin: 0 auto;
  padding: 24px;
  color: #333;
}

.safety-policy-editor__title {
  font-size: 1.5rem;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 2px solid #e0e0e0;
}

.safety-policy-editor__section {
  margin-bottom: 32px;
}

.safety-policy-editor__section-title {
  font-size: 1.15rem;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.safety-policy-editor__badge {
  font-size: 0.7rem;
  background: #e3f2fd;
  color: #1565c0;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}

.safety-policy-editor__description {
  font-size: 0.875rem;
  color: #666;
  margin-bottom: 12px;
}

.safety-policy-editor__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.safety-policy-editor__table th,
.safety-policy-editor__table td {
  border: 1px solid #e0e0e0;
  padding: 8px 12px;
  text-align: left;
}

.safety-policy-editor__table th {
  background: #f5f5f5;
  font-weight: 600;
}

.safety-policy-editor__table code {
  font-size: 0.8rem;
  background: #f0f0f0;
  padding: 1px 4px;
  border-radius: 2px;
}

.safety-policy-editor__empty {
  color: #999;
  font-style: italic;
  padding: 16px 0;
}

.safety-policy-editor__actions {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.safety-policy-editor__btn {
  padding: 6px 16px;
  border: 1px solid #ccc;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 0.875rem;
  transition: background 0.2s;
}

.safety-policy-editor__btn:hover:not(:disabled) {
  background: #f0f0f0;
}

.safety-policy-editor__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.safety-policy-editor__btn--primary {
  background: #1976d2;
  color: #fff;
  border-color: #1976d2;
}

.safety-policy-editor__btn--primary:hover:not(:disabled) {
  background: #1565c0;
}

.safety-policy-editor__btn--danger {
  color: #d32f2f;
  border-color: #d32f2f;
}

.safety-policy-editor__btn--danger:hover:not(:disabled) {
  background: #ffebee;
}

.safety-policy-editor__rule-card {
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 12px;
  background: #fafafa;
}

.safety-policy-editor__rule-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.safety-policy-editor__field {
  margin-bottom: 10px;
}

.safety-policy-editor__field label {
  display: block;
  font-size: 0.8rem;
  font-weight: 600;
  margin-bottom: 4px;
  color: #555;
}

.safety-policy-editor__field--inline label {
  display: inline;
  margin-left: 4px;
}

.safety-policy-editor__field input[type="text"],
.safety-policy-editor__field select {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 0.875rem;
  box-sizing: border-box;
}

.safety-policy-editor__field input[type="checkbox"] {
  margin-right: 4px;
}

.safety-policy-editor__footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid #e0e0e0;
}

.safety-policy-editor__message {
  font-size: 0.875rem;
  color: #2e7d32;
}
</style>
