<template>
  <div class="base-user-card">
    <div class="user-header">
      <div class="avatar">
        <span>{{ counter.userData.username ? counter.userData.username.charAt(0).toUpperCase() : 'U' }}</span>
      </div>
      <div class="user-info">
        <h3 class="username">{{ counter.userData.username || '未登录' }}</h3>
        <p class="user-id">ID: {{ counter.userData.id || '...' }}</p>
      </div>
    </div>
    <button class="logout-btn" @click="handleLogout">退出登录</button>
  </div>
</template>

<script setup>
import { useCounterStore } from '@/stores/counter.js'
const counter = useCounterStore()

const emit = defineEmits(['logout'])

const handleLogout = () => {
  if (confirm('确定要退出登录吗？')) {
    emit('logout')
  }
}
</script>

<style scoped>
.base-user-card {
  width: 100%;
  padding: 30px;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-lg);
}
.user-header {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-5);
}
.avatar {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-full);
  background: var(--gradient-primary);
  display: flex;
  justify-content: center;
  align-items: center;
  color: var(--color-text-inverse);
  font-size: var(--text-2xl);
  font-weight: var(--font-semibold);
  margin-right: var(--space-4);
  box-shadow: var(--shadow-primary);
}
.user-info .username {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--color-text);
}
.user-info .user-id {
  margin: var(--space-1) 0 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
.logout-btn {
  width: 100%;
  padding: var(--space-3);
  background: transparent;
  border: 1px solid var(--color-danger);
  border-radius: var(--radius-lg);
  color: var(--color-danger);
  font-size: 15px;
  cursor: pointer;
  transition: all var(--duration-slow) var(--ease);
}
.logout-btn:hover {
  background: var(--color-danger-light);
  border-color: var(--color-danger-hover);
  color: var(--color-danger-hover);
}
</style>
