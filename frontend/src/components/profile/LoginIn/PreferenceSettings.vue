<template>
  <div class="preferences-modal">
    <!-- 顶部导航 -->
    <div class="modal-header">
      <button class="back-btn" @click="goBack">← 返回</button>
      <h2 class="modal-title">学习偏好设置</h2>
    </div>

    <!-- 选项列表 -->
    <div class="preferences-list">
      <!-- 界面主题 -->
      <div class="preference-item" @click="toggleTheme">
        <div class="item-left">
          <span class="icon">🎨</span>
          <span class="label">界面主题</span>
        </div>
        <div class="item-right">
          <span class="value">跟随系统</span>
          <span class="arrow">›</span>
        </div>
      </div>

      <!-- AI 答疑模式 -->
      <div class="preference-item" @click="toggleAnswerMode">
        <div class="item-left">
          <span class="icon">🤖</span>
          <span class="label">AI 答疑模式</span>
        </div>
        <div class="item-right">
          <span class="value">{{ answerMode === 'concise' ? '简洁模式' : '详细模式' }}</span>
          <span class="arrow">›</span>
        </div>
      </div>

      <!-- 消息通知 -->
      <div class="preference-item">
        <div class="item-left">
          <span class="icon">🔔</span>
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
          <span class="icon">📅</span>
          <span class="label">学习提醒频率</span>
        </div>
        <div class="item-right">
          <span class="value">
            {{ remindFreq === 'daily' ? '每日提醒' : remindFreq === 'weekly' ? '每周提醒' : '不提醒' }}
          </span>
          <span class="arrow">›</span>
        </div>
      </div>
    </div>

    <!-- 底部保存按钮 -->
    <button class="save-btn" @click="savePreferences">保存偏好</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

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
  background: #fff;
  border-radius: 20px;
  padding: 20px;
  max-width: 420px;
  margin: 0 auto;
  box-shadow: 0 8px 30px rgba(0,0,0,0.1);
  font-family: 'Segoe UI', Roboto, sans-serif;
}

.modal-header {
  display: flex;
  align-items: center;
  margin-bottom: 24px;
}
.back-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: #4f46e5;
  cursor: pointer;
}
.modal-title {
  font-size: 20px;
  font-weight: 600;
  margin-left: 12px;
  color: #0f172a;
}

.preferences-list {
  margin-bottom: 24px;
}

.preference-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 12px;
  border-radius: 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: background 0.2s ease;
}
.preference-item:hover {
  background: #f8fafc;
}

.item-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.icon {
  font-size: 20px;
}
.label {
  font-size: 16px;
  color: #0f172a;
}

.item-right {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
}
.value {
  font-size: 14px;
}
.arrow {
  font-size: 18px;
  color: #94a3b8;
}

.notification-options {
  display: flex;
  gap: 16px;
}
.notification-option {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #64748b;
}

.save-btn {
  width: 100%;
  padding: 14px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  color: #fff;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.2s ease;
}
.save-btn:hover {
  transform: translateY(-2px);
}
</style>
