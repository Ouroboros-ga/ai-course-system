<template>
  <div class="fanya-bind-panel">
    <div class="bind-header">
      <span class="bind-icon">🔗</span>
      <h3>泛雅平台课程绑定</h3>
      <span v-if="bindData.isBound" class="bound-badge">已绑定</span>
      <span v-else class="unbound-badge">未绑定</span>
    </div>

    <div v-if="isLoading" class="bind-loading">
      <div class="mini-spinner"></div>
      <span>查询绑定状态...</span>
    </div>

    <template v-else>
      <div class="bind-form">
        <div class="form-row">
          <label>泛雅课程ID</label>
          <div class="input-group">
            <input
              v-model="fanyaCourseId"
              type="text"
              placeholder="输入泛雅课程ID (如: KCH2024001)"
              :disabled="bindData.isBound"
            />
            <button
              v-if="!bindData.isBound"
              class="btn-fetch"
              @click="autoFetch"
              title="从泛雅获取"
            >🔍</button>
          </div>
        </div>

        <div v-if="bindData.fanyaCourseName" class="form-row">
          <label>课程名称</label>
          <input
            :value="bindData.fanyaCourseName"
            type="text"
            disabled
            class="readonly-input"
          />
        </div>
      </div>

      <div v-if="bindData.isBound" class="bind-info">
        <div class="info-item">
          <span class="info-label">泛雅课程ID</span>
          <span class="info-value">{{ bindData.fanyaCourseId }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">关联学生数</span>
          <span class="info-value highlight">{{ bindData.boundStudentCount }} 人</span>
        </div>

        <div v-if="bindData.boundStudents?.length" class="student-list">
          <label>已同步学生</label>
          <div class="student-tags">
            <span
              v-for="s in bindData.boundStudents"
              :key="s.localId"
              class="student-tag"
            >
              {{ s.username }}
              <small>({{ s.fanyaId }})</small>
            </span>
          </div>
        </div>
      </div>

      <div class="bind-effects" v-if="!bindData.isBound">
        <p class="effects-title">💡 绑定后效果</p>
        <ul>
          <li>✅ 泛雅侧学生可直接访问此智课</li>
          <li>✅ 学习进度自动回传至泛雅成绩单</li>
          <li>✅ 支持从泛雅侧一键进入智课学习</li>
          <li>✅ 支持SSO单点登录免重复登录</li>
        </ul>
      </div>

      <div class="bind-actions">
        <template v-if="!bindData.isBound">
          <button
            class="btn-primary btn-bind"
            @click="handleBind"
            :disabled="!fanyaCourseId.trim() || isBinding"
          >
            {{ isBinding ? '绑定中...' : '🔗 绑定泛雅课程' }}
          </button>
        </template>
        <template v-else>
          <button class="btn-danger btn-unbind" @click="handleUnbind" :disabled="isUnbinding">
            {{ isUnbinding ? '解除中...' : '🔗 解除绑定' }}
          </button>
        </template>
        <a href="#" class="btn-help" @click.prevent="showHelp = !showHelp">❓ 帮助</a>
      </div>

      <div v-if="showHelp" class="help-box">
        <h4>如何获取泛雅课程ID？</h4>
        <ol>
          <li>登录泛雅教学平台（学习通/超星）</li>
          <li>进入对应课程的「设置」或「课程信息」页面</li>
          <li>在URL或课程详情页找到课程编号（如 kch123456789）</li>
          <li>将此ID粘贴到上方输入框即可</li>
        </ol>
        <p class="help-note">如需自动同步，请联系管理员配置泛雅API对接</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getBindStatus, unbindCourse, syncCourse } from '@/api/platform.js'

const props = defineProps({
  courseId: { type: [Number, String], required: true }
})

const emit = defineEmits(['bound', 'unbound'])

const isLoading = ref(true)
const isBinding = ref(false)
const isUnbinding = ref(false)
const fanyaCourseId = ref('')
const showHelp = ref(false)

const bindData = ref({
  isBound: false,
  fanyaCourseId: null,
  fanyaCourseName: null,
  boundStudentCount: 0,
  boundStudents: [],
})

onMounted(() => {
  fetchStatus()
})

async function fetchStatus() {
  isLoading.value = true
  try {
    const res = await getBindStatus(props.courseId)
    if (res) {
      bindData.value = res
      if (res.fanyaCourseId) {
        fanyaCourseId.value = res.fanyaCourseId
      }
    }
  } catch (e) {
    console.error('获取绑定状态失败:', e)
  }
  isLoading.value = false
}

function autoFetch() {
  alert('请输入从泛雅平台获取的课程ID\n\n提示：在泛雅课程管理页面可查看课程ID')
}

async function handleBind() {
  if (!fanyaCourseId.value.trim()) return

  isBinding.value = true
  try {
    await syncCourse({
      fanya_course_id: fanyaCourseId.value.trim(),
      fanya_course_name: '',
      teacher_fanya_id: '',
    })
    emit('bound', fanyaCourseId.value.trim())
    await fetchStatus()
  } catch (e) {
    alert('绑定失败: ' + (e.response?.data?.message || e.message))
  }
  isBinding.value = false
}

async function handleUnbind() {
  if (!confirm('确定要解除泛雅绑定吗？解除后泛雅侧学生将无法直接访问此课程。')) return

  isUnbinding.value = true
  try {
    await unbindCourse(props.courseId)
    emit('unbound')
    await fetchStatus()
  } catch (e) {
    alert('解除失败: ' + (e.response?.data?.message || e.message))
  }
  isUnbinding.value = false
}
</script>

<style scoped>
.fanya-bind-panel {
  background: #fff;
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  padding: 20px;
  margin-top: 16px;
}

.bind-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #eee;
}

.bind-icon { font-size: 20px; }

.bind-header h3 {
  font-size: 16px;
  color: #333;
  margin: 0;
  flex: 1;
}

.bound-badge,
.unbound-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
}

.bound-badge {
  background: #e8fdf0;
  color: #22c55e;
}

.unbound-badge {
  background: #fef3e2;
  color: #f59e0b;
}

.bind-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #888;
  padding: 20px;
  justify-content: center;
}

.mini-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid #e0e0e0;
  border-top-color: #667eea;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.form-row {
  margin-bottom: 14px;
}

.form-row label {
  display: block;
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
  font-weight: 500;
}

.input-group {
  display: flex;
  gap: 8px;
}

.input-group input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.input-group input:focus {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

.input-group input:disabled {
  background: #f5f5f5;
  cursor: not-allowed;
}

.btn-fetch {
  width: 38px;
  height: 38px;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #f8f9fa;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all 0.2s;
}

.btn-fetch:hover {
  background: #667eea;
  color: white;
  border-color: #667eea;
}

.readonly-input {
  background: #f5f5f5;
  color: #555;
}

.bind-info {
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 14px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
}

.info-label { color: #888; }

.info-value { color: #333; font-weight: 500; }

.info-value.highlight { color: #667eea; }

.student-list label {
  display: block;
  font-size: 13px;
  color: #666;
  margin-bottom: 8px;
  margin-top: 8px;
}

.student-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.student-tag {
  background: #eef2ff;
  color: #4f46e5;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
}

.student-tag small {
  color: #999;
  margin-left: 4px;
}

.bind-effects {
  background: #fffbf0;
  border: 1px solid #fef3c7;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 16px;
}

.effects-title {
  font-size: 13px;
  font-weight: 600;
  color: #92400e;
  margin: 0 0 8px;
}

.bind-effects ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.bind-effects li {
  font-size: 13px;
  color: #78350f;
  padding: 3px 0;
}

.bind-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-primary,
.btn-danger {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.35);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-danger {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.btn-danger:hover:not(:disabled) {
  background: #fee2e2;
}

.btn-help {
  font-size: 13px;
  color: #888;
  text-decoration: none;
  margin-left: auto;
}

.help-box {
  margin-top: 16px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  padding: 14px;
}

.help-box h4 {
  font-size: 14px;
  color: #0369a1;
  margin: 0 0 8px;
}

.help-box ol {
  padding-left: 18px;
  margin: 0;
}

.help-box li {
  font-size: 13px;
  color: #0c4a6e;
  padding: 2px 0;
}

.help-note {
  font-size: 12px;
  color: #64748b;
  margin: 10px 0 0;
}
</style>
