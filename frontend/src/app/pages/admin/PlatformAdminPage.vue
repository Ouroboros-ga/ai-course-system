<script setup>
import { onMounted, ref } from 'vue'
import { ShieldCheck } from 'lucide-vue-next'
import { changeUserRole, getUserList } from '@/api/user.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const state = ref('loading')
const users = ref([])
const changingId = ref(null)
const error = ref('')

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const data = await getUserList()
    users.value = Array.isArray(data?.users) ? data.users : []
    state.value = users.value.length ? 'ready' : 'empty'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || ''
    state.value = caught?.response?.status === 403 ? 'forbidden' : 'error'
  }
}

async function updateRole(user, event) {
  const role = event.target.value
  if (role === user.role) return
  if (!window.confirm(`将 ${user.username} 的角色改为 ${role}？`)) {
    event.target.value = user.role
    return
  }
  changingId.value = user.id
  try {
    await changeUserRole({ userId: user.id, role })
    user.role = role
  } catch (caught) {
    event.target.value = user.role
    error.value = caught?.response?.data?.detail || caught?.message || '角色更新失败。'
  } finally {
    changingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1"><ShieldCheck :size="25" /> 平台管理</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">管理平台账户与角色。课程内权限仍由 Course Access v1 单独决定。</p>
      </div>
      <SfxButton variant="secondary" size="sm" @click="load">刷新</SfxButton>
    </header>
    <SfxSkeleton v-if="state === 'loading'" :lines="5" block />
    <SfxError v-else-if="state === 'forbidden'" variant="forbidden" :retryable="false" description="当前账户没有平台管理员权限。" />
    <SfxError v-else-if="state === 'error'" :description="error || '无法读取用户列表。'" @retry="load" />
    <SfxEmpty v-else-if="state === 'empty'" title="还没有可管理的账户" description="新注册的账户会显示在这里。" />
    <section v-else class="sfx-panel admin-table-wrap">
      <table class="admin-table">
        <thead><tr><th>ID</th><th>账户</th><th>角色</th><th>状态</th><th>创建时间</th></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.id }}</td><td>{{ user.username }}</td>
            <td><select :value="user.role" :disabled="changingId === user.id" class="sfx-select" @change="updateRole(user, $event)"><option value="student">学生</option><option value="teacher">教师</option><option value="admin">管理员</option></select></td>
            <td>{{ user.isActive ? '正常' : '停用' }}</td><td>{{ user.createdAt ? new Date(user.createdAt).toLocaleString('zh-CN') : '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="error" class="admin-error" role="alert">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
.sfx-page-header h1 { display: flex; align-items: center; gap: var(--space-2); }
.admin-table-wrap { overflow-x: auto; }
.admin-table { width: 100%; border-collapse: collapse; font-size: var(--ui-sm-size); }
.admin-table th, .admin-table td { padding: var(--space-3); border-bottom: 1px solid var(--border-subtle); text-align: left; white-space: nowrap; }
.admin-table th { color: var(--text-secondary); font-weight: var(--ui-md-weight); }
.admin-error { margin-top: var(--space-3); color: var(--red-700); }
</style>
