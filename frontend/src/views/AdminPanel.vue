<template>
  <div class="admin-panel">
    <div class="panel-header">
      <h2><Users class="header-icon" :size="24" /> 用户管理</h2>
      <p class="subtitle">管理系统中的所有用户及其角色</p>
    </div>

    <LoadingSpinner v-if="isLoading" text="正在加载用户列表..." />

    <div v-else class="user-table-wrapper">
      <table class="user-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>当前角色</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id" :class="{ 'is-self': user.id === currentUserId }">
            <td class="td-id">{{ user.id }}</td>
            <td class="td-username">
              <span class="username-text">{{ user.username }}</span>
              <span v-if="user.id === currentUserId" class="self-badge">当前用户</span>
            </td>
            <td class="td-role">
              <span class="role-badge" :class="'role-' + user.role">
                {{ getRoleLabel(user.role) }}
              </span>
            </td>
            <td class="td-status">
              <span class="status-dot" :class="{ active: user.isActive }"></span>
              {{ user.isActive ? '正常' : '禁用' }}
            </td>
            <td class="td-action">
              <div class="role-switcher">
                <select
                  :value="user.role"
                  :disabled="user.id === currentUserId"
                  @change="handleRoleChange(user, $event)"
                  class="role-select"
                  :class="{ disabled: user.id === currentUserId }"
                >
                  <option value="student">学生</option>
                  <option value="teacher">教师</option>
                  <option value="admin">管理员</option>
                </select>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="users.length === 0" class="empty-state">
        <Inbox class="empty-icon" :size="48" />
        <p>暂无用户数据</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { Users, Inbox } from 'lucide-vue-next'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import api from '@/api/index.js'
import { useCounterStore } from '@/stores/counter.js'
import { showToast } from '@/utils/toast'

const counter = useCounterStore()

const users = ref([])
const isLoading = ref(true)

const currentUserId = computed(() => {
  const id = parseInt(counter.userData.id)
  return isNaN(id) ? null : id
})

function getRoleLabel(role) {
  const map = { student: '学生', teacher: '教师', admin: '管理员' }
  return map[role] || role
}

async function loadUsers() {
  isLoading.value = true
  try {
    const res = await api.user.getUserList()
    users.value = res.users || []
  } catch (error) {
    showToast('加载用户列表失败', 'error')
  } finally {
    isLoading.value = false
  }
}

async function handleRoleChange(user, event) {
  const newRole = event.target.value
  if (newRole === user.role) return

  if (!confirm(`确定将用户 "${user.username}" 的角色从 ${getRoleLabel(user.role)} 修改为 ${getRoleLabel(newRole)} 吗？`)) {
    event.target.value = user.role
    return
  }

  try {
    const res = await api.user.changeUserRole({
      userId: user.id,
      role: newRole
    })
    user.role = newRole
    showToast(`用户 "${user.username}" 角色已修改为 ${getRoleLabel(newRole)}`, 'success')
  } catch (error) {
    event.target.value = user.role
    showToast(error?.message || '修改角色失败', 'error')
  }
}

onMounted(() => {
  loadUsers()
})
</script>

<style scoped>
.admin-panel {
  max-width: 1000px;
  margin: 0 auto;
  padding: var(--space-5);
}

.panel-header {
  margin-bottom: var(--space-5);
}

.panel-header h2 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-2xl);
  color: var(--color-text);
  margin: 0 0 var(--space-2) 0;
  font-weight: var(--font-bold);
}

.header-icon {
  color: var(--color-primary);
}

.subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
}

.loading-state {
  text-align: center;
  padding: var(--space-8) var(--space-5);
  color: var(--color-text-secondary);
}

.user-table-wrapper {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow-x: auto;
}

.user-table {
  width: 100%;
  border-collapse: collapse;
}

.user-table thead {
  background: var(--color-bg);
}

.user-table th {
  padding: var(--space-3) var(--space-4);
  text-align: left;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}

.user-table td {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}

.user-table tbody tr:hover {
  background: var(--color-surface-2);
}

.user-table tbody tr.is-self {
  background: var(--color-primary-light);
}

.user-table tbody tr.is-self:hover {
  background: var(--color-primary-light);
}

.td-id {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  width: 60px;
}

.td-username {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.username-text {
  font-weight: var(--font-medium);
  color: var(--color-text);
}

.self-badge {
  padding: 2px var(--space-2);
  background: var(--color-primary-light);
  color: var(--color-primary-hover);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.role-badge {
  display: inline-block;
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-lg);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
}

.role-student {
  background: var(--color-primary-light);
  color: var(--color-primary-hover);
}

.role-teacher {
  background: var(--color-warning-light);
  color: var(--color-warning-hover);
}

.role-admin {
  background: var(--color-secondary-light);
  color: var(--color-secondary-hover);
}

.status-dot {
  display: inline-block;
  width: var(--space-2);
  height: var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-border-hover);
  margin-right: var(--space-2);
}

.status-dot.active {
  background: var(--color-success);
}

.role-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  cursor: pointer;
  transition: var(--transition-all);
  outline: none;
}

.role-select:hover:not(.disabled) {
  border-color: var(--color-primary);
}

.role-select:focus:not(.disabled) {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.role-select.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--color-surface-2);
}

.empty-state {
  text-align: center;
  padding: var(--space-8) var(--space-5);
  color: var(--color-text-muted);
}

.empty-icon {
  margin-bottom: var(--space-3);
  color: var(--color-text-muted);
}

@media (max-width: 768px) {
  .admin-panel {
    padding: var(--space-4);
  }

  .user-table th,
  .user-table td {
    padding: var(--space-2);
    font-size: var(--text-xs);
  }

  .td-id {
    display: none;
  }
}
</style>
