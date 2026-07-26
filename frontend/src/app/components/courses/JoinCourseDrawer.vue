<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { CheckCircle2, KeyRound } from 'lucide-vue-next'
import { joinByCode } from '@/api/courses.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import SfxField from '@/app/ui/SfxField.vue'

/**
 * 加入课程抽屉（page-design §9.4，API 契约 §3.2 join-by-code: available）。
 * 内容顺序：1. 输入邀请码 → 2. 浏览课程大厅 → 3. 泛雅发现（planned）→ 4. 申请状态（planned）。
 * 邀请码结果全量区分：有效 / 不存在 / 课程已关闭 / 已加入 / 无资格。
 */
const props = defineProps({
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'joined'])
const router = useRouter()

const code = ref('')
const submitting = ref(false)
// result: null | { kind: 'success'|'already'|'invalid'|'closed'|'forbidden'|'error', courseId?, message }
const result = ref(null)

const canSubmit = computed(() => code.value.trim().length >= 4 && !submitting.value)

watch(
  () => props.open,
  (value) => {
    if (value) {
      // 保留草稿（§5.5：关闭不丢已输入内容），仅重置提交结果
      result.value = null
      submitting.value = false
    }
  },
)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  result.value = null
  try {
    const data = await joinByCode(code.value.trim())
    if (data?.already_enrolled) {
      result.value = { kind: 'already', courseId: data.course_id, message: '你已经是该课程的学生，无需重复加入。' }
    } else {
      result.value = {
        kind: 'success',
        courseId: data?.course_id,
        message: data?.reactivated ? '已重新加入课程，你的历史学习进度仍然保留。' : '加入成功，你现在是该课程的学生。',
      }
      emit('joined', data)
    }
  } catch (e) {
    const msg = String(e?.response?.data?.detail || e?.message || '')
    const status = e?.response?.status
    if (status === 404 || /邀请码无效|不存在/.test(msg)) {
      result.value = { kind: 'invalid', message: '邀请码不存在或已失效，请核对后重试。' }
    } else if (/不接受新成员|已关闭|CLOSED|ARCHIVED|DRAFT/i.test(msg)) {
      result.value = { kind: 'closed', message: '该课程当前已关闭加入，请联系课程教师。' }
    } else if (status === 403 || /仅学生|无资格|停用/.test(msg)) {
      result.value = { kind: 'forbidden', message: '当前账号无法通过邀请码加入课程（仅学生账号可用邀请码加入）。' }
    } else {
      result.value = { kind: 'error', message: msg || '加入失败，请稍后重试。' }
    }
  } finally {
    submitting.value = false
  }
}

function enterCourse() {
  if (!result.value?.courseId) return
  emit('close')
  router.push(`/app/course/${result.value.courseId}/overview`)
}

function goHall() {
  emit('close')
  router.push('/app/courses/hall')
}
</script>

<template>
  <SfxDrawer :open="open" title="加入课程" :width="420" @close="emit('close')">
    <!-- 1. 邀请码加入 -->
    <section class="sfx-join-section">
      <h3 class="sfx-t-ui sfx-join-heading"><KeyRound :size="15" /> 输入邀请码</h3>
      <SfxField
        label="课程邀请码"
        hint="邀请码由课程教师提供，区分大小写。"
        :error="result && ['invalid', 'closed', 'forbidden', 'error'].includes(result.kind) ? result.message : ''"
      >
        <input
          v-model="code"
          class="sfx-input sfx-mono"
          placeholder="例如 ABCD-1234"
          :disabled="submitting"
          @keydown.enter="submit"
        />
      </SfxField>

      <div
        v-if="result && ['success', 'already'].includes(result.kind)"
        class="sfx-join-success"
        role="status"
      >
        <CheckCircle2 :size="18" aria-hidden="true" />
        <div>
          <p class="sfx-t-ui">{{ result.message }}</p>
          <p class="sfx-t-caption">课程角色：学生</p>
        </div>
      </div>
    </section>

    <!-- 2. 课程大厅 -->
    <section class="sfx-join-section">
      <h3 class="sfx-t-ui sfx-join-heading">没有邀请码？</h3>
      <p class="sfx-t-ui sfx-t-secondary">到课程大厅浏览已公开课程，查看加入条件。</p>
      <SfxButton variant="secondary" size="sm" @click="goHall">浏览课程大厅</SfxButton>
    </section>

    <!-- 3/4. planned 能力如实标注 -->
    <section class="sfx-join-section sfx-join-planned">
      <p class="sfx-t-caption sfx-t-muted">
        泛雅同步发现课程、加入申请与审核状态属于冻结契约（planned），后端实现后开放。
      </p>
    </section>

    <template #footer>
      <SfxButton variant="tertiary" @click="emit('close')">取消</SfxButton>
      <SfxButton
        v-if="result && ['success', 'already'].includes(result.kind)"
        variant="primary"
        @click="enterCourse"
      >进入课程</SfxButton>
      <SfxButton v-else variant="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">
        确认加入
      </SfxButton>
    </template>
  </SfxDrawer>
</template>

<style scoped>
.sfx-join-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  align-items: flex-start;
}

.sfx-join-section:last-child { border-bottom: none; }

.sfx-join-heading {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-primary);
}

.sfx-join-success {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  background: var(--green-100);
  color: var(--green-700);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  width: 100%;
}

.sfx-join-planned {
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  background: var(--surface-cool);
}
</style>
