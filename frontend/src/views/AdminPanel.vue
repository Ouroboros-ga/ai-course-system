<template>
  <div class="admin-panel">
    <div class="panel-header">
      <h2>👥 用户管理</h2>
      <p class="subtitle">管理系统中的所有用户及其角色</p>
    </div>

    <div v-if="isLoading" class="loading-state">
      <div class="spinner"></div>
      <span>正在加载用户列表...</span>
    </div>

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
        <div class="empty-icon">📭</div>
        <p>暂无用户数据</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '@/api/index.js'
import { useCounterStore } from '@/stores/counter.js'
import { showToast } from '@/utils/toast'

const counter = useCounterStore()

const users = ref([])
const isLoading = ref(true)

const currentUserId = computed(() => {
  return parseInt(counter.userData.id)
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
    console.error('加载用户列表失败:', error)
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
    console.error('修改角色失败:', error)
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
  padding: 24px;
}

.panel-header {
  margin-bottom: 24px;
}

.panel-header h2 {
  font-size: 24px;
  color: #111827;
  margin: 0 0 8px 0;
  font-weight: 700;
}

.subtitle {
  font-size: 14px;
  color: #6b7280;
  margin: 0;
}

.loading-state {
  text-align: center;
  padding: 60px 20px;
  color: #6b7280;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.user-table-wrapper {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.user-table {
  width: 100%;
  border-collapse: collapse;
}

.user-table thead {
  background: #f8fafc;
}

.user-table th {
  padding: 14px 16px;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
}

.user-table td {
  padding: 14px 16px;
  font-size: 14px;
  color: #374151;
  border-bottom: 1px solid #f3f4f6;
}

.user-table tbody tr:hover {
  background: #f9fafb;
}

.user-table tbody tr.is-self {
  background: #eff6ff;
}

.user-table tbody tr.is-self:hover {
  background: #dbeafe;
}

.td-id {
  color: #9ca3af;
  font-size: 13px;
  width: 60px;
}

.td-username {
  display: flex;
  align-items: center;
  gap: 8px;
}

.username-text {
  font-weight: 500;
  color: #111827;
}

.self-badge {
  padding: 2px 8px;
  background: #dbeafe;
  color: #1e40af;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.role-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.role-student {
  background: #dbeafe;
  color: #1e40af;
}

.role-teacher {
  background: #fef3c7;
  color: #92400e;
}

.role-admin {
  background: #ede9fe;
  color: #5b21b6;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d1d5db;
  margin-right: 6px;
}

.status-dot.active {
  background: #22c55e;
}

.role-select {
  padding: 6px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  color: #374151;
  background: white;
  cursor: pointer;
  transition: all 0.2s ease;
  outline: none;
}

.role-select:hover:not(.disabled) {
  border-color: #6366f1;
}

.role-select:focus:not(.disabled) {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.role-select.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #f9fafb;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #9ca3af;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

@media (max-width: 768px) {
  .admin-panel {
    padding: 16px;
  }

  .user-table th,
  .user-table td {
    padding: 10px 8px;
    font-size: 12px;
  }

  .td-id {
    display: none;
  }
}
</style>
