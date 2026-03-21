<template>
  <div class="preference-container">
    <div class="glass-card">
      <!-- 顶部返回栏 -->
      <div class="panel-header">
        <button class="back-btn" @click="$emit('close')">‹ 返回</button>
        <h4>学习偏好设置</h4>
      </div>

      <!-- 偏好选项 -->
      <div class="preference-list">
        <!-- 1. 主题切换 -->
        <div class="preference-item">
          <div class="item-info">
            <span class="icon">🎨</span>
            <span>界面主题</span>
          </div>
          <el-select v-model="preferences.theme" size="small" style="width: 120px">
            <el-option label="亮色模式" value="light" />
            <el-option label="暗色模式" value="dark" />
            <el-option label="跟随系统" value="auto" />
          </el-select>
        </div>

        <!-- 2. 语音播报偏好 -->
        <div class="preference-item">
          <div class="item-info">
            <span class="icon">🔊</span>
            <span>AI 语音播报</span>
          </div>
          <div class="voice-options">
            <el-select v-model="preferences.voiceSpeed" size="small" style="width: 100px; margin-right: 8px">
              <el-option label="慢速" value="slow" />
              <el-option label="标准" value="normal" />
              <el-option label="快速" value="fast" />
            </el-select>
            <el-select v-model="preferences.voiceTone" size="small" style="width: 100px">
              <el-option label="男声" value="male" />
              <el-option label="女声" value="female" />
            </el-select>
          </div>
        </div>

        <!-- 3. 通知开关 -->
        <div class="preference-item">
          <div class="item-info">
            <span class="icon">🔔</span>
            <span>消息通知</span>
          </div>
          <div class="notify-switches">
            <el-switch v-model="preferences.notify.course" />
            <span class="label">课件解析完成提醒</span>
            <el-switch v-model="preferences.notify.aiReply" style="margin-left: 16px" />
            <span class="label">AI 问答回复提醒</span>
          </div>
        </div>

        <!-- 4. 自动续播 -->
        <div class="preference-item">
          <div class="item-info">
            <span class="icon">▶️</span>
            <span>问答后自动续播</span>
          </div>
          <el-switch v-model="preferences.autoResume" />
        </div>
      </div>

      <!-- 保存按钮 -->
      <button class="submit-btn" @click="handleSave">保存偏好</button>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const emit = defineEmits(['close', 'save'])

// 初始化偏好（可从 localStorage 读取，这里用默认值）
const preferences = reactive({
  theme: 'light',
  voiceSpeed: 'normal',
  voiceTone: 'female',
  notify: {
    course: true,
    aiReply: true
  },
  autoResume: true
})

// 保存偏好
const handleSave = () => {
  localStorage.setItem('user-preferences', JSON.stringify(preferences))
  emit('save', preferences)
  emit('close')
}
</script>

<style scoped>
.preference-container {
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  pointer-events: none;
}
.glass-card {
  position: relative;
  width: 500px;
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  z-index: 10;
  pointer-events: auto;
}
.panel-header {
  display: flex;
  align-items: center;
  margin-bottom: 24px;
}
.back-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #888;
  cursor: pointer;
  padding-right: 12px;
  transition: color 0.2s;
}
.back-btn:hover { color: #333; }
.panel-header h4 {
  margin: 0;
  font-size: 16px;
  color: #333;
  font-weight: 500;
}
.preference-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 30px;
}
.preference-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
}
.item-info {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  color: #444;
}
.item-info .icon { font-size: 18px; }
.voice-options, .notify-switches { display: flex; align-items: center; }
.label { font-size: 13px; color: #666; margin-left: 6px; }
.submit-btn {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  border-radius: 12px;
  color: #fff;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}
.submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
}
</style>
