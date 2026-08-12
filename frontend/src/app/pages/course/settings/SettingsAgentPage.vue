<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { getCourseSettings, updateCourseAgentPolicy } from '@/api/course_lifecycle.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)
const allowed = computed(() => courseContext.allowed.value?.['agent.policy.configure'])

const form = ref({
  enabled: true,
})
const version = ref(null)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

async function load() {
  try {
    const data = await getCourseSettings(courseId.value)
    version.value = data?.version ?? null
    const policy = data?.agent_policy ?? {}
    form.value = {
      enabled: policy.enabled !== false,
    }
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
        <h1 class="sfx-t-title2">智能体设置</h1>
        <p class="sfx-t-ui sfx-t-secondary">控制学生是否可以使用本课程的教学智能体。</p>
      </div>
    </header>

    <form class="sfx-panel sfx-agent-form" @submit.prevent="save">
      <div class="sfx-agent-section">
        <h2 class="sfx-panel-title">智能体启动</h2>
        <label class="sfx-check">
          <input v-model="form.enabled" type="checkbox" :disabled="!allowed" />
          <span class="sfx-t-ui">启用课程智能体（关闭后学生侧教学问答入口不可用）</span>
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
