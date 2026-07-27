<script setup>
import { computed, inject, ref } from 'vue'
import { useRoute } from 'vue-router'
import { closeCourse, clearInviteCode, reopenCourse, setInviteCode } from '@/api/courses.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxField from '@/app/ui/SfxField.vue'
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 设置 · 加入与发布（page-design §18.3）。
 * 真实能力（available，契约 §2 成员与邀请码）：
 * - 设置 / 清除邀请码：POST/DELETE invite-code；
 * - 关闭 / 重开课程：POST close / reopen（课程状态来自课程详情真实数据）。
 * 公开到大厅、申请审核、开课时间等为 planned 契约，如实标注。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)
const courseContext = inject('courseContext')

const course = computed(() => courseContext.course.value)

const newCode = ref('')
const acting = ref('') // '' | 'set' | 'clear' | 'close' | 'reopen'
const notice = ref('') // 成功反馈（真实服务端返回后显示）
const actionError = ref('')

const isClosed = computed(() => course.value?.status === 'closed')
const isPublished = computed(() => course.value?.status === 'published')

async function run(kind, fn, successText) {
  acting.value = kind
  notice.value = ''
  actionError.value = ''
  try {
    await fn()
    notice.value = successText
    newCode.value = ''
    // 刷新课程上下文（状态/权限可能已变化）
    await courseContext.reload?.()
  } catch (e) {
    actionError.value = e?.message || '操作失败，请稍后重试。'
  } finally {
    acting.value = ''
  }
}

function submitSetCode() {
  if (!isPublished.value) {
    actionError.value = '请先在课程建设中完成发布；草稿课程不能设置邀请码。'
    return
  }
  const code = newCode.value.trim()
  if (!code) {
    actionError.value = '请输入邀请码。'
    return
  }
  run('set', () => setInviteCode(courseId, code), '邀请码已更新，学生可通过该码加入课程。')
}

function submitClearCode() {
  run('clear', () => clearInviteCode(courseId), '邀请码已清除，课程不再接受邀请码加入。')
}

function submitClose() {
  run('close', () => closeCourse(courseId), '课程已关闭：拒绝新成员加入，已加入学生可继续学习。')
}

function submitReopen() {
  run('reopen', () => reopenCourse(courseId), '课程已重新开放。')
}
</script>

<template>
  <div class="sfx-access">
    <header class="sfx-access-head">
      <div>
        <h1 class="sfx-t-title2">加入与发布</h1>
        <p class="sfx-t-ui sfx-t-secondary">邀请码与课程开放状态</p>
      </div>
      <SfxBadge :tone="isClosed ? 'red' : course?.status === 'published' ? 'green' : 'amber'">
        {{ isClosed ? '已关闭加入' : course?.status === 'published' ? '已发布' : '草稿' }}
      </SfxBadge>
    </header>

    <p v-if="notice" class="sfx-access-notice sfx-t-ui" role="status">{{ notice }}</p>
    <p v-if="actionError" class="sfx-access-error sfx-t-ui" role="alert">{{ actionError }}</p>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">邀请码</h2>
      <p class="sfx-t-ui sfx-t-secondary sfx-access-hint">
        设置后学生可在「我的课程 → 加入课程」输入邀请码直接加入。当前已生效的邀请码不在接口中返回，
        重新设置即覆盖旧码。
      </p>
      <p v-if="!isPublished" class="sfx-access-draft-note sfx-t-ui" role="status">
        当前课程仍是草稿。发布后才能设置邀请码，草稿课程也不会出现在课程大厅。
      </p>
      <div class="sfx-access-code-row">
        <SfxField label="新邀请码" for-id="sfx-invite-code">
          <input
            id="sfx-invite-code"
            v-model="newCode"
            class="sfx-input sfx-mono"
            placeholder="例如 DS-2026-ALGO"
            :disabled="!isPublished"
            @keydown.enter="submitSetCode"
          />
        </SfxField>
        <div class="sfx-access-code-actions">
          <SfxButton variant="primary" size="sm" :disabled="!isPublished" :loading="acting === 'set'" @click="submitSetCode">设置邀请码</SfxButton>
          <SfxButton variant="danger" size="sm" :disabled="!isPublished" :loading="acting === 'clear'" @click="submitClearCode">清除邀请码</SfxButton>
        </div>
      </div>
    </section>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">开放状态</h2>
      <p class="sfx-t-ui sfx-t-secondary sfx-access-hint">
        关闭课程将拒绝所有新成员加入（含邀请码），已加入学生的学习不受影响。
      </p>
      <SfxButton v-if="!isClosed" variant="danger" size="sm" :loading="acting === 'close'" @click="submitClose">
        关闭课程加入
      </SfxButton>
      <SfxButton v-else variant="primary" size="sm" :loading="acting === 'reopen'" @click="submitReopen">
        重新开放加入
      </SfxButton>
    </section>

    <SfxPlannedPanel
      contract-key="course-settings"
      title="公开发布与申请审核 · 接口契约已冻结"
      available-note="邀请码与关闭/重开为真实能力，上方操作直接生效。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        是否公开出现在课程大厅、申请审核、开课与结束时间、发布后通知学生、学生退出与章节跳转
        设置将随课程发布契约一并开放（§18.3）。
      </p>
    </SfxPlannedPanel>
  </div>
</template>

<style scoped>
.sfx-access {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
  max-width: 860px;
}

.sfx-access-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.sfx-access-hint { margin-bottom: var(--space-4); }

.sfx-access-code-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.sfx-access-code-row > *:first-child { flex: 1; min-width: 240px; }

.sfx-access-code-actions {
  display: flex;
  gap: var(--space-2);
}

.sfx-access-notice {
  color: var(--green-700);
  background: var(--green-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.sfx-access-error {
  color: var(--red-700);
  background: var(--red-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}
.sfx-access-draft-note { color: var(--amber-800); background: var(--amber-100); border-radius: var(--radius-sm); padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3); }
</style>
