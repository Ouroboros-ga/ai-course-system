<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Lock } from 'lucide-vue-next'
import { getSafetyPolicy, updateSafetyPolicy } from '@/api/safety.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxField from '@/app/ui/SfxField.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 设置 · 安全与合规（page-design §18.5）。
 * 数据源（available）：GET/PUT /safety/course/{id}/safety-policy。
 * 三层边界：平台硬边界只读展示（教师不可关闭）；课程策略可编辑；
 * 运行时围栏在学生实验中展示。保存只提交有变化的字段。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)

const status = ref('loading') // loading | ready | error
const forbidden = ref(false)
const policy = ref(null)

const form = ref({
  course_type: 'basic',
  forbidden_topics: '',
  required_citation_topics: '',
  high_risk_confirmation_required: true,
  keyword_assist_enabled: false,
  status: 'draft',
})

const saving = ref(false)
const saveNotice = ref('')
const saveError = ref('')

const courseTypeOptions = [
  { value: 'basic', label: '基础教学' },
  { value: 'professional', label: '专业课程' },
  { value: 'cybersecurity', label: '网络安全课程' },
  { value: 'ctf', label: 'CTF 隔离课程' },
]

const statusOptions = [
  { value: 'draft', label: '策略草稿' },
  { value: 'dry_run', label: '试运行观察' },
  { value: 'active', label: '正式启用' },
]

const statusMeta = {
  draft: { label: '策略草稿', tone: 'amber' },
  dry_run: { label: '试运行观察', tone: 'ink' },
  active: { label: '正式启用', tone: 'green' },
  conflict: { label: '存在冲突', tone: 'red' },
}

const hardLimitLabel = {
  host_container_isolation: '宿主与容器隔离',
  intranet_protection: '内网保护',
  resource_limits: '资源限制',
  audit: '审计',
  no_malicious_persistence: '恶意持久化限制',
  high_risk_syscall_limit: '高风险系统调用限制',
}

function linesToList(text) {
  return text.split('\n').map((s) => s.trim()).filter(Boolean)
}

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const data = await getSafetyPolicy(courseId)
    policy.value = data
    form.value = {
      course_type: data.course_type ?? 'basic',
      forbidden_topics: (data.forbidden_topics ?? []).join('\n'),
      required_citation_topics: (data.required_citation_topics ?? []).join('\n'),
      high_risk_confirmation_required: Boolean(data.high_risk_confirmation_required),
      keyword_assist_enabled: Boolean(data.keyword_assist_enabled),
      status: data.status === 'conflict' ? 'draft' : (data.status ?? 'draft'),
    }
    status.value = 'ready'
  } catch (e) {
    forbidden.value = /403|权限|拒绝/.test(String(e?.message || ''))
    status.value = 'error'
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  saveNotice.value = ''
  saveError.value = ''
  try {
    const p = policy.value ?? {}
    const payload = {}
    if (form.value.course_type !== p.course_type) payload.course_type = form.value.course_type
    const ft = linesToList(form.value.forbidden_topics)
    const rt = linesToList(form.value.required_citation_topics)
    if (JSON.stringify(ft) !== JSON.stringify(p.forbidden_topics ?? [])) payload.forbidden_topics = ft
    if (JSON.stringify(rt) !== JSON.stringify(p.required_citation_topics ?? [])) payload.required_citation_topics = rt
    if (form.value.high_risk_confirmation_required !== Boolean(p.high_risk_confirmation_required)) {
      payload.high_risk_confirmation_required = form.value.high_risk_confirmation_required
    }
    if (form.value.keyword_assist_enabled !== Boolean(p.keyword_assist_enabled)) {
      payload.keyword_assist_enabled = form.value.keyword_assist_enabled
    }
    if (form.value.status !== p.status) payload.status = form.value.status

    if (!Object.keys(payload).length) {
      saveNotice.value = '没有需要保存的变更。'
      return
    }
    const updated = await updateSafetyPolicy(courseId, payload)
    policy.value = updated
    saveNotice.value = '安全策略已保存。'
  } catch (e) {
    saveError.value = e?.message || '保存失败，请稍后重试。'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="sfx-settings-page sfx-safety">
    <header class="sfx-settings-head">
      <div>
        <h1 class="sfx-t-title2">安全与合规</h1>
        <p class="sfx-t-ui sfx-t-secondary">课程安全策略与平台安全底线</p>
      </div>
      <SfxBadge v-if="policy" :tone="statusMeta[policy.status]?.tone ?? 'neutral'">
        {{ statusMeta[policy.status]?.label ?? policy.status }}
      </SfxBadge>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="6" />

    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '安全策略需要课程查看权限。' : '安全策略暂时无法读取，请稍后重试。'"
      @retry="load"
    />

    <template v-else>
      <!-- 平台硬边界（教师不可关闭，§18.5） -->
      <section class="sfx-panel">
        <h2 class="sfx-panel-title"><Lock :size="16" /> 平台硬边界（不可关闭）</h2>
        <ul class="sfx-safety-hardlimits">
          <li v-for="(label, key) in hardLimitLabel" :key="key">
            <SfxBadge tone="green">已强制</SfxBadge>
            <span class="sfx-t-ui">{{ label }}</span>
          </li>
        </ul>
      </section>

      <!-- 课程安全策略 -->
      <section class="sfx-panel">
        <h2 class="sfx-panel-title">课程安全策略</h2>

        <div class="sfx-safety-form">
          <SfxField label="课程类型" hint="决定高风险内容的默认处置基线。">
            <select v-model="form.course_type" class="sfx-select">
              <option v-for="opt in courseTypeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </SfxField>

          <SfxField label="禁答主题" hint="每行一个主题；命中后课程智能体拒绝回答并说明。">
            <textarea v-model="form.forbidden_topics" class="sfx-textarea" rows="3" placeholder="例如：与课程无关的娱乐话题"></textarea>
          </SfxField>

          <SfxField label="必须引用主题" hint="每行一个主题；这些主题的回答必须附原文引用。">
            <textarea v-model="form.required_citation_topics" class="sfx-textarea" rows="3" placeholder="例如：复杂度证明"></textarea>
          </SfxField>

          <SfxField label="策略状态" hint="试运行只观察不阻断；正式启用后才执行阻断。">
            <select v-model="form.status" class="sfx-select">
              <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </SfxField>

          <label class="sfx-safety-check">
            <input v-model="form.high_risk_confirmation_required" type="checkbox" />
            <span class="sfx-t-ui">高风险任务需教师确认后执行</span>
          </label>

          <label class="sfx-safety-check">
            <input v-model="form.keyword_assist_enabled" type="checkbox" />
            <span class="sfx-t-ui">启用关键词辅助判定（结合课程类型与提问内容，仅作参考，不单独决定是否阻断）</span>
          </label>
        </div>

        <div v-if="policy?.keyword_assist_enabled || form.keyword_assist_enabled" class="sfx-safety-keywords">
          <p class="sfx-t-caption sfx-t-muted">平台关键词辅助列表（只读）：</p>
          <div class="sfx-safety-keyword-list">
            <SfxBadge v-for="kw in policy?.keyword_assist_list ?? []" :key="kw" tone="amber">{{ kw }}</SfxBadge>
          </div>
        </div>

        <p v-if="saveNotice" class="sfx-safety-notice sfx-t-ui" role="status">{{ saveNotice }}</p>
        <p v-if="saveError" class="sfx-safety-error sfx-t-ui" role="alert">{{ saveError }}</p>

        <div class="sfx-safety-actions">
          <SfxButton variant="primary" :loading="saving" @click="save">保存策略</SfxButton>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.sfx-panel-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.sfx-safety-hardlimits {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-safety-hardlimits li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.sfx-safety-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-safety-check {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.sfx-safety-check input { width: 16px; height: 16px; accent-color: var(--ink-700); }

.sfx-safety-keywords {
  margin-top: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sfx-safety-keyword-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sfx-safety-notice {
  color: var(--green-700);
  background: var(--green-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-4);
}

.sfx-safety-error {
  color: var(--red-700);
  background: var(--red-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-4);
}

.sfx-safety-actions {
  margin-top: var(--space-4);
  display: flex;
  justify-content: flex-end;
}
</style>
