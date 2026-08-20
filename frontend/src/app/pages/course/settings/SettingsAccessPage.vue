<script setup>
import { computed, inject, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { closeCourse, clearInviteCode, reopenCourse, setInviteCode } from '@/api/courses.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxField from '@/app/ui/SfxField.vue'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.courseId)
const courseContext = inject('courseContext')
const course = computed(() => courseContext.course.value)

const code = ref('')
const acting = ref('')
const notice = ref('')
const actionError = ref('')

const isPublished = computed(() => course.value?.status === 'published')
const isClosed = computed(() => course.value?.status === 'closed')

async function run(kind, action, success) {
  acting.value = kind
  notice.value = ''
  actionError.value = ''
  try {
    await action()
    notice.value = success
    code.value = ''
    await courseContext.reload?.()
  } catch (caught) {
    actionError.value = caught?.message || '操作失败'
  } finally {
    acting.value = ''
  }
}

function saveCode() {
  if (!isPublished.value) {
    actionError.value = '请先正式发布课程；草稿课程不能设置加入码。'
    return
  }
  if (!code.value.trim()) {
    actionError.value = '请输入加入码。'
    return
  }
  run('code', () => setInviteCode(courseId, code.value.trim()), '加入码已更新。')
}
</script>

<template>
  <div class="sfx-settings-page">
    <header class="sfx-settings-head">
      <div>
        <h1 class="sfx-t-title2">加入与发布</h1>
        <p class="sfx-t-ui sfx-t-secondary">课程发布后才可以在大厅出现、设置加入码和审核成员申请。</p>
      </div>
      <SfxBadge :tone="isClosed ? 'red' : isPublished ? 'green' : 'amber'">
        {{ isClosed ? '已关闭' : isPublished ? '已发布' : '草稿' }}
      </SfxBadge>
    </header>

    <p v-if="notice" class="sfx-settings-notice is-success" role="status">{{ notice }}</p>
    <p v-if="actionError" class="sfx-settings-notice is-error" role="alert">{{ actionError }}</p>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">加入码</h2>
      <p class="sfx-t-caption sfx-t-muted">设置新的加入码后，旧码即失效。草稿课程无法加入且不会出现在课程大厅。</p>
      <div class="sfx-access-row">
        <SfxField label="新加入码">
          <input v-model="code" class="sfx-input" :disabled="!isPublished" placeholder="例如 DS-2026-ALGO" @keydown.enter="saveCode" />
        </SfxField>
        <SfxButton :disabled="!isPublished" :loading="acting === 'code'" @click="saveCode">设置加入码</SfxButton>
        <SfxButton variant="danger" :disabled="!isPublished" :loading="acting === 'clear'" @click="run('clear', () => clearInviteCode(courseId), '加入码已清除。')">清除</SfxButton>
      </div>
    </section>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">成员申请</h2>
      <p class="sfx-t-caption sfx-t-muted">申请记录、批准、拒绝和补充信息均在成员页面执行。</p>
      <SfxButton variant="secondary" @click="router.push(`/app/course/${courseId}/members/requests`)">查看加入申请</SfxButton>
    </section>

    <section class="sfx-panel">
      <h2 class="sfx-panel-title">开放状态</h2>
      <p class="sfx-t-caption sfx-t-muted">关闭课程会拒绝新成员加入，不影响现有成员阅读已发布课程。</p>
      <SfxButton v-if="!isClosed" variant="danger" :loading="acting === 'close'" @click="run('close', () => closeCourse(courseId), '课程已关闭新成员加入。')">关闭课程加入</SfxButton>
      <SfxButton v-else :loading="acting === 'reopen'" @click="run('reopen', () => reopenCourse(courseId), '课程已重新开放。')">重新开放</SfxButton>
    </section>
  </div>
</template>

<style scoped>
.sfx-access-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-top: var(--space-3);
}

.sfx-access-row > :first-child {
  flex: 1;
  min-width: 240px;
}

/* 移动端（design.md §12.5）：输入区独占一行 */
@media (max-width: 760px) {
  .sfx-access-row > :first-child {
    flex-basis: 100%;
    min-width: 0;
  }
}
</style>
