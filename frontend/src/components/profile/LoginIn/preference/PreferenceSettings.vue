<template>
  <div class="preferences-modal">
    <!-- 顶部导航 -->
    <div class="modal-header">
      <button class="back-btn" @click="goBack"><ArrowLeft :size="16" /> 返回</button>
      <h2 class="modal-title">学习偏好设置</h2>
    </div>

    <!-- 选项列表 -->
    <div class="preferences-list">
      <!-- 界面主题 -->
      <div class="preference-item" @click="toggleTheme">
        <div class="item-left">
          <span class="icon"><Palette :size="20" /></span>
          <span class="label">界面主题</span>
        </div>
        <div class="item-right">
          <span class="value">跟随系统</span>
          <span class="arrow"><ChevronRight :size="18" /></span>
        </div>
      </div>

      <!-- AI 答疑模式 -->
      <div class="preference-item" @click="toggleAnswerMode">
        <div class="item-left">
          <span class="icon"><Bot :size="20" /></span>
          <span class="label">AI 答疑模式</span>
        </div>
        <div class="item-right">
          <span class="value">{{ answerMode === 'concise' ? '简洁模式' : '详细模式' }}</span>
          <span class="arrow"><ChevronRight :size="18" /></span>
        </div>
      </div>

      <!-- 消息通知 -->
      <div class="preference-item">
        <div class="item-left">
          <span class="icon"><Bell :size="20" /></span>
          <span class="label">消息通知</span>
        </div>
        <div class="notification-options">
          <label class="notification-option">
            <input type="checkbox" v-model="notifyParse" />
            <span>课件解析完成提醒</span>
          </label>
          <label class="notification-option">
            <input type="checkbox" v-model="notifyAnswer" />
            <span>AI 问答回复提醒</span>
          </label>
        </div>
      </div>

      <!-- 学习提醒频率 -->
      <div class="preference-item" @click="toggleRemindFreq">
        <div class="item-left">
          <span class="icon"><Calendar :size="20" /></span>
          <span class="label">学习提醒频率</span>
        </div>
        <div class="item-right">
          <span class="value">
            {{ remindFreq === 'daily' ? '每日提醒' : remindFreq === 'weekly' ? '每周提醒' : '不提醒' }}
          </span>
          <span class="arrow"><ChevronRight :size="18" /></span>
        </div>
      </div>
    </div>

    <!-- 底部保存按钮 -->
    <button class="save-btn" @click="savePreferences">保存偏好</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ArrowLeft, Palette, Bot, Bell, Calendar, ChevronRight } from 'lucide-vue-next'

// 状态
const answerMode = ref('concise')
const remindFreq = ref('daily')
const notifyParse = ref(false)
const notifyAnswer = ref(false)

// ========== ✅ 核心修复：返回上一页 ==========
const goBack = () => {
  window.history.go(-1)
}

// ========== ✅ 保存后 自动返回Profile ==========
const savePreferences = () => {
  alert("保存成功！")
  // 保存完 自动返回
  window.history.go(-1)
}

// 其他功能
const toggleTheme = () => {
  alert("切换主题")
}
const toggleAnswerMode = () => {
  answerMode.value = answerMode.value === 'concise' ? 'detailed' : 'concise'
}
const toggleRemindFreq = () => {
  const m = { daily: 'weekly', weekly: 'none', none: 'daily' }
  remindFreq.value = m[remindFreq.value]
}
</script>

<style scoped>
.preferences-modal {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  max-width: 420px;
  margin: 0 auto;
  box-shadow: var(--shadow-lg);
  font-family: var(--font-sans);
}

.modal-header {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-5);
}
.back-btn {
  background: none;
  border: none;
  font-size: var(--text-base);
  color: var(--color-primary);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.modal-title {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  margin-left: var(--space-3);
  color: var(--color-text);
}

.preferences-list {
  margin-bottom: var(--space-5);
}

.preference-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px var(--space-3);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-2);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease);
}
.preference-item:hover {
  background: var(--color-surface-2);
}

.item-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.icon {
  display: flex;
  align-items: center;
  color: var(--color-primary);
}
.label {
  font-size: var(--text-base);
  color: var(--color-text);
}

.item-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}
.value {
  font-size: var(--text-sm);
}
.arrow {
  display: flex;
  align-items: center;
  color: var(--color-text-muted);
}

.notification-options {
  display: flex;
  gap: var(--space-4);
}
.notification-option {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.save-btn {
  width: 100%;
  padding: 14px;
  border-radius: var(--radius-lg);
  border: none;
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: transform var(--duration-normal) var(--ease);
}
.save-btn:hover {
  transform: translateY(-2px);
}

@media (max-width: 768px) {
  .preferences-modal {
    max-width: 100%;
  }

  .notification-options {
    flex-direction: column;
    gap: var(--space-2);
  }
}
</style>
