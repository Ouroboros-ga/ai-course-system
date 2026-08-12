<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Lock } from 'lucide-vue-next'
import { getSandboxPolicy, updateSandboxPolicy } from '@/api/safety.js'
import { getSandboxLanguages } from '@/api/sandbox.js'
import {
  getCourseCapabilities,
  updateCodeSandboxExperimentPlatform,
} from '@/api/course_access.js'
import { isCodeSandboxExperimentPlatformEnabled } from '@/app/lib/courseExperimentPlatform.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxField from '@/app/ui/SfxField.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 设置 · 沙箱权限（page-design §18.6）。
 * 数据源（available）：GET/PUT /safety/course/{id}/sandbox-policy +
 * GET /sandbox/languages（平台允许语言）。
 * 教师不能设置宿主机路径、特权容器或公共互联网任意访问（§18.6）——
 * 平台硬边界只读展示，表单不包含这些选项。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)
const courseContext = inject('courseContext', null)

const status = ref('loading')
const forbidden = ref(false)
const policy = ref(null)
const platformLanguages = ref([])
const courseCapabilities = ref({})
const platformSaving = ref(false)
const experimentPlatformEnabled = computed(() =>
  isCodeSandboxExperimentPlatformEnabled(courseCapabilities.value),
)
const canManageExperimentPlatform = computed(() => Boolean(
  courseContext?.allowed?.value?.['course.edit'],
))

const form = ref({
  sandbox_preset: 'basic_programming',
  allowed_languages: [],
  network_mode: 'disabled',
  file_access_mode: 'temp_only',
  cpu_limit: 1,
  memory_limit: 262144,
  wall_time_limit: 30,
  environment_destroy_on_exit: true,
  log_retention_days: 30,
})

const saving = ref(false)
const saveNotice = ref('')
const saveError = ref('')

const presetOptions = [
  { value: 'basic_programming', label: '基础编程' },
  { value: 'algorithm', label: '算法实验' },
  { value: 'data_processing', label: '数据处理' },
  { value: 'cybersecurity_range', label: '网络安全隔离靶场' },
  { value: 'ctf_isolated', label: 'CTF 隔离环境' },
]

const networkOptions = [
  { value: 'disabled', label: '关闭网络' },
  { value: 'whitelist', label: '白名单' },
  { value: 'isolated_range', label: '隔离靶场' },
]

const fileOptions = [
  { value: 'temp_only', label: '仅临时文件' },
  { value: 'course_files', label: '课程文件' },
]

function toggleLanguage(lang) {
  const list = form.value.allowed_languages
  const idx = list.indexOf(lang)
  if (idx >= 0) list.splice(idx, 1)
  else list.push(lang)
}

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const [data, langs, capabilities] = await Promise.all([
      getSandboxPolicy(courseId),
      getSandboxLanguages().catch(() => null),
      getCourseCapabilities(courseId),
    ])
    policy.value = data
    platformLanguages.value = Array.isArray(langs?.languages) ? langs.languages : []
    courseCapabilities.value = capabilities?.capabilities ?? {}
    form.value = {
      sandbox_preset: data.sandbox_preset ?? 'basic_programming',
      allowed_languages: [...(data.allowed_languages ?? [])],
      network_mode: data.network_mode ?? 'disabled',
      file_access_mode: data.file_access_mode ?? 'temp_only',
      cpu_limit: data.cpu_limit ?? 1,
      memory_limit: data.memory_limit ?? 262144,
      wall_time_limit: data.wall_time_limit ?? 30,
      environment_destroy_on_exit: Boolean(data.environment_destroy_on_exit ?? true),
      log_retention_days: data.log_retention_days ?? 30,
    }
    status.value = 'ready'
  } catch (e) {
    forbidden.value = /403|权限|拒绝/.test(String(e?.message || ''))
    status.value = 'error'
  }
}

async function setExperimentPlatform(enabled) {
  if (platformSaving.value || !canManageExperimentPlatform.value) return

  platformSaving.value = true
  saveNotice.value = ''
  saveError.value = ''
  try {
    const updated = await updateCodeSandboxExperimentPlatform(courseId, enabled)
    courseCapabilities.value = {
      ...courseCapabilities.value,
      ...(updated?.capabilities ?? {}),
    }
    await courseContext?.reload?.()
    saveNotice.value = enabled
      ? '实验平台（代码沙箱）已启用。'
      : '实验平台已关闭，师生侧的“实验任务”入口已隐藏。'
  } catch (e) {
    saveError.value = e?.message || '实验平台设置保存失败，请稍后重试。'
  } finally {
    platformSaving.value = false
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  saveNotice.value = ''
  saveError.value = ''
  try {
    const payload = {
      sandbox_preset: form.value.sandbox_preset,
      allowed_languages: form.value.allowed_languages,
      network_mode: form.value.network_mode,
      file_access_mode: form.value.file_access_mode,
      cpu_limit: Number(form.value.cpu_limit),
      memory_limit: Number(form.value.memory_limit),
      wall_time_limit: Number(form.value.wall_time_limit),
      environment_destroy_on_exit: form.value.environment_destroy_on_exit,
      log_retention_days: Number(form.value.log_retention_days),
    }
    const updated = await updateSandboxPolicy(courseId, payload)
    policy.value = updated
    saveNotice.value = '沙箱策略已保存。'
  } catch (e) {
    saveError.value = e?.message || '保存失败，请检查数值范围（内存 ≥ 16384KB，保留 1–365 天）。'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="sfx-settings-page sfx-sandbox">
    <header class="sfx-settings-head">
      <div>
        <h1 class="sfx-t-title2">沙箱权限</h1>
        <p class="sfx-t-ui sfx-t-secondary">课程代码运行的资源与网络边界</p>
      </div>
      <SfxBadge v-if="experimentPlatformEnabled && policy" tone="ink">{{ presetOptions.find((o) => o.value === policy.sandbox_preset)?.label ?? policy.sandbox_preset }}</SfxBadge>
      <SfxBadge v-else tone="amber">实验平台未启用</SfxBadge>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="6" />

    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '沙箱策略需要课程查看权限。' : '沙箱策略暂时无法读取，请稍后重试。'"
      @retry="load"
    />

    <template v-else>
      <section class="sfx-panel">
        <div class="sfx-experiment-platform-head">
          <div>
            <h2 class="sfx-panel-title">实验平台（代码沙箱）</h2>
            <p class="sfx-t-ui sfx-t-secondary">
              当前实验平台只支持代码运行。关闭后，教师端与学生端都不会显示“实验任务”。
            </p>
          </div>
          <SfxButton
            :variant="experimentPlatformEnabled ? 'secondary' : 'primary'"
            :loading="platformSaving"
            :disabled="!canManageExperimentPlatform"
            @click="setExperimentPlatform(!experimentPlatformEnabled)"
          >
            {{ experimentPlatformEnabled ? '关闭实验平台' : '启用实验平台' }}
          </SfxButton>
        </div>
        <p v-if="!canManageExperimentPlatform" class="sfx-t-caption sfx-t-muted">
          当前课程角色没有变更实验平台设置的权限。
        </p>
        <p v-else-if="!experimentPlatformEnabled" class="sfx-t-caption sfx-t-muted">
          汽车工程等暂不使用代码沙箱的课程应保持关闭；将来接入非代码实验时会使用独立能力，不复用此开关。
        </p>
        <p v-if="saveNotice" class="sfx-sandbox-notice sfx-t-ui" role="status">{{ saveNotice }}</p>
        <p v-if="saveError" class="sfx-sandbox-error sfx-t-ui" role="alert">{{ saveError }}</p>
      </section>

      <section class="sfx-panel">
        <h2 class="sfx-panel-title"><Lock :size="16" /> 平台硬边界（不可设置）</h2>
        <ul class="sfx-sandbox-hardlimits">
          <li><SfxBadge tone="green">已强制</SfxBadge><span class="sfx-t-ui">禁止访问服务器文件</span></li>
          <li><SfxBadge tone="green">已强制</SfxBadge><span class="sfx-t-ui">禁止获取管理员权限</span></li>
          <li><SfxBadge tone="green">已强制</SfxBadge><span class="sfx-t-ui">禁止随意访问互联网</span></li>
        </ul>
      </section>

      <section v-if="experimentPlatformEnabled" class="sfx-panel">
        <h2 class="sfx-panel-title">课程沙箱策略</h2>

        <div class="sfx-sandbox-form">
          <SfxField label="沙箱预设">
            <select v-model="form.sandbox_preset" class="sfx-select">
              <option v-for="opt in presetOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </SfxField>

          <SfxField label="允许语言" hint="来自平台允许的语言集合；不选表示跟随预设默认。">
            <div class="sfx-sandbox-langs">
              <label
                v-for="lang in platformLanguages"
                :key="lang"
                class="sfx-sandbox-lang"
                :class="{ 'is-checked': form.allowed_languages.includes(lang) }"
              >
                <input
                  type="checkbox"
                  :checked="form.allowed_languages.includes(lang)"
                  @change="toggleLanguage(lang)"
                />
                <span class="sfx-t-ui sfx-mono">{{ lang }}</span>
              </label>
              <p v-if="!platformLanguages.length" class="sfx-t-caption sfx-t-muted">平台语言列表未获取到，保存时将沿用当前策略。</p>
            </div>
          </SfxField>

          <div class="sfx-sandbox-grid">
            <SfxField label="网络">
              <select v-model="form.network_mode" class="sfx-select">
                <option v-for="opt in networkOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </SfxField>

            <SfxField label="文件访问">
              <select v-model="form.file_access_mode" class="sfx-select">
                <option v-for="opt in fileOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </SfxField>

            <SfxField label="CPU（核）">
              <input v-model.number="form.cpu_limit" type="number" min="1" class="sfx-input" />
            </SfxField>

            <SfxField label="内存（KB）" hint="最低 16384 KB">
              <input v-model.number="form.memory_limit" type="number" min="16384" step="1024" class="sfx-input" />
            </SfxField>

            <SfxField label="单次运行时长（秒）">
              <input v-model.number="form.wall_time_limit" type="number" min="1" class="sfx-input" />
            </SfxField>

            <SfxField label="日志保留（天）" hint="1–365 天">
              <input v-model.number="form.log_retention_days" type="number" min="1" max="365" class="sfx-input" />
            </SfxField>
          </div>

          <label class="sfx-sandbox-check">
            <input v-model="form.environment_destroy_on_exit" type="checkbox" />
            <span class="sfx-t-ui">运行结束后销毁环境</span>
          </label>
        </div>

        <div class="sfx-sandbox-actions">
          <SfxButton variant="primary" :loading="saving" @click="save">保存沙箱策略</SfxButton>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.sfx-experiment-platform-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.sfx-panel-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-sandbox-hardlimits {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-sandbox-hardlimits li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.sfx-sandbox-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-sandbox-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.sfx-sandbox-langs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-sandbox-lang {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-secondary);
}

.sfx-sandbox-lang.is-checked {
  border-color: var(--ink-500);
  background: var(--ink-100);
  color: var(--ink-900);
}

.sfx-sandbox-lang input { accent-color: var(--ink-700); }

.sfx-sandbox-check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.sfx-sandbox-check input { width: 16px; height: 16px; accent-color: var(--ink-700); }

.sfx-sandbox-notice {
  color: var(--green-700);
  background: var(--green-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-4);
}

.sfx-sandbox-error {
  color: var(--red-700);
  background: var(--red-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-4);
}

.sfx-sandbox-actions {
  margin-top: var(--space-4);
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 640px) {
  .sfx-experiment-platform-head {
    flex-direction: column;
  }
}
</style>
