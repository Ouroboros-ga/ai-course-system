<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { getCourseSettings, updateCourseAgentPolicy } from '@/api/course_lifecycle.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const allowed = computed(() => courseContext.allowed.value?.['agent.policy.configure'])

const form = ref({
  enabled_tools: [],
  require_teacher_confirmation: true,
  web_research_enabled: false,
})
const version = ref(null)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

const tools = [
  ['graph_read', '图谱检索'],
  ['course_retrieval', '课程内容检索'],
  ['question_bank', '题库'],
  ['sandbox', '代码沙箱'],
  ['visualization', '可视化演示'],
  ['learning_event', '学习行为记录'],
  ['web_research', '外部资料检索'],
]

async function load() {
  try {
    const data = await getCourseSettings(courseId.value)
    version.value = data?.version ?? null
    form.value = { ...form.value, ...(data?.agent_policy ?? {}) }
  } catch (e) {
    error.value = e?.message || '智能体策略读取失败'
  }
}

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await updateCourseAgentPolicy(courseId.value, form.value, version.value)
    saved.value = true
    await load()
  } catch (e) {
    error.value = e?.message || '保存智能体策略失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="sfx-settings-page">
    <header class="sfx-settings-head">
      <div>
        <h1 class="sfx-t-title2">智能体策略</h1>
        <p class="sfx-t-ui sfx-t-secondary">选择本课程允许智能体使用的能力，并决定高风险动作是否需要教师确认。</p>
      </div>
    </header>

    <form class="sfx-panel sfx-agent-form" @submit.prevent="save">
      <div class="sfx-agent-section">
        <h2 class="sfx-panel-title">可用能力</h2>
        <label v-for="[tool, toolLabel] in tools" :key="tool" class="sfx-check">
          <input v-model="form.enabled_tools" type="checkbox" :value="tool" :disabled="!allowed" />
          <span class="sfx-t-ui">{{ toolLabel }}</span>
        </label>
      </div>

      <div class="sfx-agent-section">
        <h2 class="sfx-panel-title">行为约束</h2>
        <label class="sfx-check">
          <input v-model="form.require_teacher_confirmation" type="checkbox" :disabled="!allowed" />
          <span class="sfx-t-ui">高风险教学动作必须教师确认</span>
        </label>
        <label class="sfx-check">
          <input v-model="form.web_research_enabled" type="checkbox" :disabled="!allowed" />
          <span class="sfx-t-ui">允许补充外部资料（仅供回答参考，不改变课程内容）</span>
        </label>
      </div>

      <SfxError v-if="error" :description="error" />
      <p v-if="saved" class="sfx-settings-notice is-success">已保存。</p>

      <div class="sfx-settings-actions">
        <SfxButton type="submit" :disabled="!allowed" :loading="saving">保存智能体策略</SfxButton>
      </div>
    </form>
  </div>
</template>

<style scoped>
.sfx-agent-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.sfx-agent-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-agent-section .sfx-panel-title {
  margin-bottom: 0;
}

.sfx-check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.sfx-check input {
  width: 16px;
  height: 16px;
  accent-color: var(--ink-700);
}
</style>
