<template>
  <div class="student-dashboard">
    <div class="dashboard-header">
      <h2>我的课程学习</h2>
      <p class="subtitle">选择课程开始学习</p>
    </div>

    <!-- 课程选择区域 -->
    <div class="courses-section" v-if="!selectedCourse">
      <div class="section-title">可用课程</div>
      <div class="courses-grid">
        <div
          v-for="course in availableCourses"
          :key="course.id"
          class="course-card"
          @click="selectCourse(course)"
        >
          <div class="course-icon">{{ course.icon }}</div>
          <div class="course-info">
            <h3 class="course-title">{{ course.title }}</h3>
            <p class="course-desc">{{ course.description }}</p>
            <div class="course-meta">
              <span class="meta-item">📖 {{ course.chapters }} 章</span>
              <span class="meta-item">⏱️ {{ course.duration }}</span>
            </div>
          </div>
          <div class="course-action">
            <button class="start-btn">开始学习</button>
          </div>
        </div>
      </div>

      <div v-if="availableCourses.length === 0" class="empty-state">
        <div class="empty-icon">📚</div>
        <p>暂无可用课程</p>
        <p class="empty-hint">请联系老师添加课程</p>
      </div>
    </div>

    <!-- 课程学习界面 -->
    <div v-else class="learning-interface">
      <div class="learning-header">
        <button class="back-btn" @click="goBack">
          ← 返回课程列表
        </button>
        <div class="course-title-bar">
          <h3>{{ selectedCourse.title }}</h3>
          <span class="progress-text">进度: {{ currentChapter + 1 }} / {{ selectedCourse.chapters.length }}</span>
        </div>
      </div>

      <div class="learning-content">
        <!-- 章节导航 -->
        <div class="chapter-nav">
          <div class="nav-title">章节目录</div>
          <div class="chapter-list">
            <div
              v-for="(chapter, index) in selectedCourse.chapters"
              :key="index"
              class="chapter-item"
              :class="{ active: currentChapter === index, completed: index < currentChapter }"
              @click="goToChapter(index)"
            >
              <span class="chapter-status">
                {{ index < currentChapter ? '✅' : (index === currentChapter ? '📍' : '⭕') }}
              </span>
              <span class="chapter-name">{{ chapter.title }}</span>
            </div>
          </div>
        </div>

        <!-- 内容展示区 -->
        <div class="content-area">
          <div class="content-header">
            <h4>{{ selectedCourse.chapters[currentChapter]?.title || '' }}</h4>
          </div>
          <div class="content-body">
            <div class="text-content">
              {{ selectedCourse.chapters[currentChapter]?.content || '加载中...' }}
            </div>
          </div>

          <!-- 问答区域 -->
          <div class="qa-section">
            <div class="qa-header">
              <span>💬 智能问答</span>
            </div>
            <div class="qa-input-area">
              <input
                type="text"
                v-model="question"
                placeholder="输入您的问题..."
                @keyup.enter="askQuestion"
                class="qa-input"
              />
              <button class="qa-send-btn" @click="askQuestion">发送</button>
            </div>
            <div v-if="qaHistory.length > 0" class="qa-history">
              <div
                v-for="(item, index) in qaHistory"
                :key="index"
                class="qa-item"
                :class="item.role"
              >
                <div class="qa-label">{{ item.role === 'user' ? '👤 我' : '🤖 AI' }}</div>
                <div class="qa-text">{{ item.content }}</div>
              </div>
            </div>
          </div>

          <!-- 导航按钮 -->
          <div class="navigation-buttons">
            <button
              class="nav-button"
              :disabled="currentChapter <= 0"
              @click="previousChapter"
            >
              ◀ 上一章
            </button>
            <button
              class="nav-button primary"
              :disabled="currentChapter >= selectedCourse.chapters.length - 1"
              @click="nextChapter"
            >
              下一章 ▶
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { showToast } from '@/utils/toast'

const selectedCourse = ref(null)
const currentChapter = ref(0)
const question = ref('')
const qaHistory = ref([])

const availableCourses = ref([
  {
    id: 1,
    icon: '📐',
    title: '线性系统理论',
    description: '线性系统的时域分析法、频域分析法等核心内容',
    chapters: 13,
    duration: '32课时',
    chaptersList: [
      { title: '线性系统的时域分析法', content: '牛顿莱布尼茨公式是微积分的基本定理，它建立了微分和积分之间的联系。' },
      { title: '拉普拉斯变换', content: '拉普拉斯变换是一种积分变换，常用于求解微分方程。' },
      { title: '传递函数', content: '传递函数是描述线性时不变系统输入输出关系的数学模型。' },
    ]
  },
  {
    id: 2,
    icon: '🔬',
    title: '信号与系统',
    description: '信号处理基础理论与系统分析方法',
    chapters: 10,
    duration: '28课时',
    chaptersList: []
  },
  {
    id: 3,
    icon: '💻',
    title: '自动控制原理',
    description: '控制系统分析与设计方法',
    chapters: 15,
    duration: '40课时',
    chaptersList: []
  }
])

const selectCourse = (course) => {
  selectedCourse.value = {
    ...course,
    chapters: course.chaptersList.length > 0 ? course.chaptersList : [
      { title: '第一章 简介', content: '课程简介内容...' },
      { title: '第二章 基础概念', content: '基础概念内容...' },
    ]
  }
  currentChapter.value = 0
  showToast(`已选择课程: ${course.title}`, 'success')
}

const goBack = () => {
  selectedCourse.value = null
  currentChapter.value = 0
  qaHistory.value = []
}

const goToChapter = (index) => {
  currentChapter.value = index
}

const previousChapter = () => {
  if (currentChapter.value > 0) {
    currentChapter.value--
  }
}

const nextChapter = () => {
  if (currentChapter.value < selectedCourse.value.chapters.length - 1) {
    currentChapter.value++
  }
}

const askQuestion = () => {
  if (!question.value.trim()) {
    showToast('请输入问题', 'warning')
    return
  }

  qaHistory.value.push({
    role: 'user',
    content: question.value
  })

  const userQuestion = question.value
  question.value = ''

  // 模拟AI回复（实际应调用后端API）
  setTimeout(() => {
    qaHistory.value.push({
      role: 'assistant',
      content: `关于"${userQuestion}"的回答：这是一个很好的问题。根据当前章节的内容，我们可以从以下几个方面来理解...`
    })
  }, 1000)
}
</script>

<style scoped>
.student-dashboard {
  width: 100%;
  min-height: calc(100vh - 80px);
  background: #f5f7fa;
  padding: 20px;
  box-sizing: border-box;
}

.dashboard-header {
  margin-bottom: 24px;
}

.dashboard-header h2 {
  font-size: 24px;
  color: #111827;
  font-weight: 700;
  margin-bottom: 4px;
}

.subtitle {
  font-size: 14px;
  color: #6b7280;
}

/* 课程列表 */
.courses-section {
  max-width: 1200px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 16px;
}

.courses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
}

.course-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.course-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.course-icon {
  font-size: 48px;
  text-align: center;
}

.course-info {
  flex: 1;
}

.course-title {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 8px;
}

.course-desc {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
  margin-bottom: 12px;
}

.course-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #9ca3af;
}

.start-btn {
  width: 100%;
  padding: 10px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.start-btn:hover {
  transform: scale(1.02);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #9ca3af;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.empty-hint {
  font-size: 13px;
  margin-top: 8px;
}

/* 学习界面 */
.learning-interface {
  max-width: 1400px;
  margin: 0 auto;
}

.learning-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e5e7eb;
}

.back-btn {
  padding: 8px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #374151;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.back-btn:hover {
  background: #f3f4f6;
}

.course-title-bar {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 16px;
}

.course-title-bar h3 {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
}

.progress-text {
  font-size: 13px;
  color: #6b7280;
}

.learning-content {
  display: flex;
  gap: 20px;
  height: calc(100vh - 220px);
}

/* 章节导航 */
.chapter-nav {
  width: 280px;
  background: white;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow-y: auto;
  flex-shrink: 0;
}

.nav-title {
  font-size: 15px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
}

.chapter-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chapter-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #4b5563;
  transition: all 0.2s ease;
}

.chapter-item:hover {
  background: #f3f4f6;
}

.chapter-item.active {
  background: #eef2ff;
  color: #4f46e5;
  font-weight: 500;
}

.chapter-item.completed {
  opacity: 0.7;
}

.chapter-status {
  font-size: 14px;
}

.chapter-name {
  flex: 1;
}

/* 内容区 */
.content-area {
  flex: 1;
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
}

.content-header h4 {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.content-body {
  flex: 1;
}

.text-content {
  font-size: 15px;
  line-height: 1.8;
  color: #374151;
  padding: 20px;
  background: #f9fafb;
  border-radius: 8px;
  min-height: 200px;
}

/* 问答区域 */
.qa-section {
  border-top: 1px solid #e5e7eb;
  padding-top: 16px;
}

.qa-header {
  font-size: 15px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
}

.qa-input-area {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.qa-input {
  flex: 1;
  padding: 10px 16px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
}

.qa-input:focus {
  outline: none;
  border-color: #6366f1;
}

.qa-send-btn {
  padding: 10px 24px;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.qa-send-btn:hover {
  background: #5558e6;
}

.qa-history {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
}

.qa-item {
  padding: 12px;
  border-radius: 8px;
  font-size: 13px;
}

.qa-item.user {
  background: #eff6ff;
  margin-left: 40px;
}

.qa-item.assistant {
  background: #f9fafb;
  margin-right: 40px;
}

.qa-label {
  font-weight: 600;
  margin-bottom: 4px;
  color: #374151;
}

.qa-text {
  color: #4b5563;
  line-height: 1.5;
}

.navigation-buttons {
  display: flex;
  justify-content: space-between;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
}

.nav-button {
  padding: 10px 24px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: white;
  color: #374151;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.nav-button:hover:not(:disabled) {
  background: #f3f4f6;
}

.nav-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nav-button.primary {
  background: #6366f1;
  color: white;
  border-color: #6366f1;
}

.nav-button.primary:hover:not(:disabled) {
  background: #5558e6;
}
</style>
