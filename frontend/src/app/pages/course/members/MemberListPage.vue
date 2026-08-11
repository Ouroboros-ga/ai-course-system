<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { UsersRound } from 'lucide-vue-next'
import { listCourseMembers, upsertCourseMember } from '@/api/course_access.js'
import { useCounterStore } from '@/stores/counter.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxField from '@/app/ui/SfxField.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 成员列表（page-design §17.2）。
 * 数据源（available）：GET/PUT /course-access/courses/{id}/members。
 *
 * 诚实边界：members 端点当前只返回 user_id/role/status/joined_at，不返回
 * 姓名与账号——列表如实显示用户 ID，姓名聚合由 planned facade 承担后不伪造。
 * 课程所有者不可通过成员接口修改（后端约束）。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)
const courseContext = inject('courseContext')
const counter = useCounterStore()

const status = ref('loading')
const forbidden = ref(false)
const members = ref([])

const canManage = computed(() => Boolean(courseContext.allowed.value['membership.role.change']))

// 角色编辑抽屉
const editTarget = ref(null)
const editRole = ref('student')
const editStatus = ref('active')
const saving = ref(false)
const actionError = ref('')

const roleMeta = {
  owner: { label: '课程所有者', tone: 'ink' },
  teacher: { label: '教师', tone: 'ink' },
  teaching_assistant: { label: '助教', tone: 'ink' },
  observer: { label: '观察者', tone: 'neutral' },
  student: { label: '学生', tone: 'green' },
}

const statusMeta = {
  active: { label: '在课', tone: 'green' },
  removed: { label: '已移除', tone: 'red' },
  withdrawn: { label: '已退出', tone: 'neutral' },
  pending: { label: '待生效', tone: 'amber' },
}

const roleOptions = [
  { value: 'student', label: '学生' },
  { value: 'teaching_assistant', label: '助教' },
  { value: 'observer', label: '观察者' },
  { value: 'teacher', label: '教师' },
]

const sortedMembers = computed(() => {
  const order = { owner: 0, teacher: 1, teaching_assistant: 2, observer: 3, student: 4 }
  return [...members.value].sort(
    (a, b) => (order[a.role] ?? 9) - (order[b.role] ?? 9) || a.user_id - b.user_id,
  )
})

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const data = await listCourseMembers(courseId)
    members.value = Array.isArray(data?.members) ? data.members : []
    status.value = 'ready'
  } catch (e) {
    forbidden.value = /403|权限|拒绝/.test(String(e?.message || ''))
    status.value = 'error'
  }
}

function openEdit(member) {
  editTarget.value = member
  editRole.value = member.role === 'owner' ? 'teacher' : member.role
  editStatus.value = member.status
  actionError.value = ''
}

async function saveEdit() {
  if (!editTarget.value || saving.value) return
  saving.value = true
  actionError.value = ''
  try {
    await upsertCourseMember(courseId, editTarget.value.user_id, {
      role: editRole.value,
      status: editStatus.value,
    })
    editTarget.value = null
    await load()
  } catch (e) {
    actionError.value = e?.message || '保存失败，请稍后重试。'
  } finally {
    saving.value = false
  }
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="sfx-members">
    <header class="sfx-members-head">
      <div>
        <h1 class="sfx-t-title2">成员列表</h1>
        <p class="sfx-t-ui sfx-t-secondary">
          共 {{ members.length }} 名成员。
        </p>
      </div>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" />

    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '成员列表需要课程的 membership.view 权限。' : '成员列表暂时无法读取，请稍后重试。'"
      @retry="load"
    />

    <SfxEmpty
      v-else-if="!members.length"
      title="课程还没有成员"
      description="通过邀请码或加入申请让学生加入后，成员会显示在这里。"
    >
      <template #icon><UsersRound :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <div v-else class="sfx-table-wrap">
      <table class="sfx-table">
        <thead>
          <tr>
            <th>用户 ID</th><th>课程角色</th><th>状态</th><th>加入时间</th><th>学情统计</th><th v-if="canManage">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="member in sortedMembers" :key="member.user_id">
            <td class="sfx-mono">
              #{{ member.user_id }}
              <span v-if="Number(counter.userData.id) === member.user_id" class="sfx-t-caption sfx-t-muted">（我）</span>
            </td>
            <td>
              <SfxBadge :tone="roleMeta[member.role]?.tone ?? 'neutral'">
                {{ roleMeta[member.role]?.label ?? member.role }}
              </SfxBadge>
            </td>
            <td>
              <SfxBadge :tone="statusMeta[member.status]?.tone ?? 'neutral'">
                {{ statusMeta[member.status]?.label ?? member.status }}
              </SfxBadge>
            </td>
            <td class="sfx-t-caption">{{ formatTime(member.joined_at) }}</td>
            <td class="sfx-t-caption">{{ member.analytics_excluded ? '不计入' : '计入' }}</td>
            <td v-if="canManage">
              <SfxButton
                v-if="member.role !== 'owner'"
                variant="tertiary"
                size="sm"
                @click="openEdit(member)"
              >调整角色</SfxButton>
              <span v-else class="sfx-t-caption sfx-t-muted">所有者不可改</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 调整成员抽屉 -->
    <SfxDrawer
      :open="Boolean(editTarget)"
      :title="`调整成员 #${editTarget?.user_id ?? ''}`"
      :width="420"
      @close="editTarget = null"
    >
      <SfxField label="课程角色">
        <select v-model="editRole" class="sfx-select">
          <option v-for="opt in roleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </SfxField>

      <SfxField label="成员状态" hint="「已移除」后该用户失去课程访问权；可再次改回「在课」恢复。">
        <select v-model="editStatus" class="sfx-select">
          <option value="active">在课</option>
          <option value="removed">已移除</option>
        </select>
      </SfxField>

      <p v-if="actionError" class="sfx-members-error sfx-t-ui" role="alert">{{ actionError }}</p>

      <template #footer>
        <SfxButton variant="tertiary" @click="editTarget = null">取消</SfxButton>
        <SfxButton variant="primary" :loading="saving" @click="saveEdit">保存</SfxButton>
      </template>
    </SfxDrawer>
  </div>
</template>

<script>
export default {}
</script>

<style scoped>
.sfx-members {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
}

.sfx-members-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.sfx-members-error {
  color: var(--red-700);
  background: var(--red-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}
</style>
