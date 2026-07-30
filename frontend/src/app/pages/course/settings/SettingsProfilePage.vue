<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Trash2, TriangleAlert } from 'lucide-vue-next'
import { getCourseSettings, updateCourseProfile } from '@/api/course_lifecycle.js'
import { deleteCourse } from '@/api/courses.js'
import { showToast } from '@/utils/toast.js'
import UiModal from '@/components/ui/UiModal.vue'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'

const courseContext = inject('courseContext')
const router = useRouter()
const courseId = computed(() => courseContext.courseId.value)
const course = computed(() => courseContext.course.value ?? {})
const canDelete = computed(() => (
  courseContext.courseRole.value === 'owner'
  && Boolean(courseContext.allowed.value?.['course.delete'])
))
const form = ref({ title: '', description: '' })
const version = ref(null)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const deleteDialogOpen = ref(false)
const deleteConfirmation = ref('')
const deleting = ref(false)
const deleteError = ref('')
const deleteConfirmed = computed(() => (
  deleteConfirmation.value === String(course.value.title || '')
))

function resetFromCourse() {
  form.value = {
    title: course.value.title || '',
    description: course.value.description || '',
  }
}

async function load() {
  resetFromCourse()
  try {
    const settings = await getCourseSettings(courseId.value)
    version.value = settings?.version ?? null
    if (settings?.profile) form.value = { ...form.value, ...settings.profile }
  } catch {
    // The basic course fields remain editable when lifecycle settings are unavailable.
  }
}

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    await updateCourseProfile(courseId.value, form.value, version.value)
    saved.value = true
    await load()
  } catch (e) {
    error.value = e?.message || '保存课程资料失败'
  } finally {
    saving.value = false
  }
}

function openDeleteDialog() {
  deleteConfirmation.value = ''
  deleteError.value = ''
  deleteDialogOpen.value = true
}

async function permanentlyDeleteCourse() {
  if (!canDelete.value || !deleteConfirmed.value || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    const report = await deleteCourse(courseId.value, deleteConfirmation.value)
    deleteDialogOpen.value = false
    if (report?.cleanup_complete === false) {
      showToast('课程数据已删除，但部分外部文件清理失败，请查看服务端日志。', 'warning')
    } else {
      showToast('课程及其专属图谱、向量索引和课件已永久删除。', 'success')
    }
    await router.replace('/app/courses/building')
  } catch (e) {
    deleteError.value = e?.message || '删除课程失败'
  } finally {
    deleting.value = false
  }
}

watch(course, resetFromCourse, { deep: true })
onMounted(load)
</script>

<template>
  <div class="sfx-profile">
    <header class="sfx-profile-head">
      <div>
        <h1 class="sfx-t-title2">基础信息</h1>
        <p class="sfx-t-ui sfx-t-secondary">课程名称、简介与展示资料。保存采用版本校验，避免覆盖其他教师修改。</p>
      </div>
      <SfxBadge :tone="course.status === 'published' ? 'green' : 'amber'">
        {{ course.status || 'draft' }}
      </SfxBadge>
    </header>

    <form class="sfx-panel sfx-profile-form" @submit.prevent="save">
      <label>
        课程名称
        <input v-model.trim="form.title" class="sfx-input" maxlength="200" required />
      </label>
      <label>
        课程简介
        <textarea v-model.trim="form.description" class="sfx-input" rows="6" maxlength="4000" />
      </label>
      <SfxError v-if="error" :description="error" />
      <p v-if="saved" class="sfx-save-ok">已保存。</p>
      <SfxButton type="submit" :loading="saving">保存基础信息</SfxButton>
    </form>

    <section v-if="canDelete" class="sfx-panel sfx-danger-zone" aria-labelledby="danger-zone-title">
      <div>
        <p class="sfx-danger-kicker">危险操作</p>
        <h2 id="danger-zone-title">永久删除课程</h2>
        <p>删除课程数据库记录、专属课件、解析缓存、图谱 Bundle 和 LanceDB 索引。共享对象不会被删除。</p>
      </div>
      <SfxButton variant="danger" @click="openDeleteDialog">
        <template #icon><Trash2 :size="16" /></template>
        删除课程
      </SfxButton>
    </section>

    <UiModal v-model="deleteDialogOpen" title="永久删除课程" width="560px">
      <div class="sfx-delete-dialog">
        <div class="sfx-delete-warning">
          <TriangleAlert :size="22" aria-hidden="true" />
          <div>
            <strong>此操作不可恢复</strong>
            <p>运行中的解析或图谱任务会阻止删除。删除成功后，同一课件可重新上传并重新解析。</p>
          </div>
        </div>
        <label>
          输入课程名称 <strong>{{ course.title }}</strong> 以确认
          <input
            v-model="deleteConfirmation"
            class="sfx-input"
            autocomplete="off"
            :placeholder="course.title"
            @keyup.enter="permanentlyDeleteCourse"
          />
        </label>
        <SfxError v-if="deleteError" :description="deleteError" />
      </div>
      <template #footer>
        <SfxButton variant="secondary" :disabled="deleting" @click="deleteDialogOpen = false">取消</SfxButton>
        <SfxButton
          variant="danger"
          :disabled="!deleteConfirmed"
          :loading="deleting"
          @click="permanentlyDeleteCourse"
        >永久删除</SfxButton>
      </template>
    </UiModal>
  </div>
</template>

<style scoped>
.sfx-profile{display:flex;flex-direction:column;gap:var(--space-4);padding:var(--space-6);max-width:860px}
.sfx-profile-head{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--space-3)}
.sfx-profile-form{display:grid;gap:var(--space-4)}
.sfx-profile-form label,.sfx-delete-dialog label{display:grid;gap:var(--space-1)}
.sfx-save-ok{color:var(--green-700)}
.sfx-danger-zone{display:flex;align-items:center;justify-content:space-between;gap:var(--space-6);border-color:var(--red-300);margin-top:var(--space-6)}
.sfx-danger-zone h2{margin:2px 0 var(--space-2);font-size:var(--text-lg);color:var(--ink-900)}
.sfx-danger-zone p{margin:0;max-width:640px;color:var(--text-secondary);line-height:1.6}
.sfx-danger-kicker{font-size:var(--ui-sm-size);font-weight:700;color:var(--red-700)!important;letter-spacing:.06em}
.sfx-delete-dialog{display:grid;gap:var(--space-4)}
.sfx-delete-warning{display:flex;gap:var(--space-3);padding:var(--space-4);border:1px solid var(--red-300);border-radius:var(--radius-md);background:var(--red-100);color:var(--red-800)}
.sfx-delete-warning p{margin:var(--space-1) 0 0;line-height:1.55}
@media(max-width:640px){.sfx-profile{padding:var(--space-4)}.sfx-danger-zone{align-items:flex-start;flex-direction:column}}
</style>
