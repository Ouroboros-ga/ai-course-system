<template>
  <div class="fanya-bind-panel">
    <div class="bind-header">
      <Link class="bind-icon" :size="20" />
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
            ><Search :size="16" /></button>
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
        <p class="effects-title"><Lightbulb :size="14" /> 绑定后效果</p>
        <ul>
          <li><CheckCircle :size="14" /> 泛雅侧学生可直接访问此智课</li>
          <li><CheckCircle :size="14" /> 学习进度自动回传至泛雅成绩单</li>
          <li><CheckCircle :size="14" /> 支持从泛雅侧一键进入智课学习</li>
          <li><CheckCircle :size="14" /> 支持SSO单点登录免重复登录</li>
        </ul>
      </div>

      <div class="bind-actions">
        <template v-if="!bindData.isBound">
          <button
            class="btn-primary btn-bind"
            @click="handleBind"
            :disabled="!fanyaCourseId.trim() || isBinding"
          >
            <template v-if="isBinding">绑定中...</template>
            <template v-else><Link :size="14" /> 绑定泛雅课程</template>
          </button>
        </template>
        <template v-else>
          <button class="btn-danger btn-unbind" @click="handleUnbind" :disabled="isUnbinding">
            <template v-if="isUnbinding">解除中...</template>
            <template v-else><Link :size="14" /> 解除绑定</template>
          </button>
        </template>
        <a href="#" class="btn-help" @click.prevent="showHelp = !showHelp"><HelpCircle :size="14" /> 帮助</a>
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
import { Link, Search, Lightbulb, CheckCircle, HelpCircle } from 'lucide-vue-next'
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
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  margin-top: var(--space-4);
}

.bind-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.bind-icon { flex-shrink: 0; color: var(--color-primary); }

.bind-header h3 {
  font-size: var(--text-base);
  color: var(--color-text);
  margin: 0;
  flex: 1;
}

.bound-badge,
.unbound-badge {
  font-size: var(--text-xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-md);
}

.bound-badge {
  background: var(--color-success-light);
  color: var(--color-success);
}

.unbound-badge {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.bind-loading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  padding: var(--space-5);
  justify-content: center;
}

.mini-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: var(--radius-full);
  animation: spin 0.6s linear infinite;
}

.form-row {
  margin-bottom: var(--space-3);
}

.form-row label {
  display: block;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
  font-weight: var(--font-medium);
}

.input-group {
  display: flex;
  gap: var(--space-2);
}

.input-group input {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--duration-normal) var(--ease);
}

.input-group input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.input-group input:disabled {
  background: var(--color-surface-2);
  cursor: not-allowed;
}

.btn-fetch {
  width: 38px;
  height: 38px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-all);
}

.btn-fetch:hover {
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border-color: var(--color-primary);
}

.readonly-input {
  background: var(--color-surface-2);
  color: var(--color-text-secondary);
}

.bind-info {
  background: var(--color-bg);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  margin-bottom: var(--space-3);
}

.info-item {
  display: flex;
  justify-content: space-between;
  padding: var(--space-2) 0;
  font-size: var(--text-xs);
}

.info-label { color: var(--color-text-muted); }

.info-value { color: var(--color-text); font-weight: var(--font-medium); }

.info-value.highlight { color: var(--color-primary); }

.student-list label {
  display: block;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
  margin-top: var(--space-2);
}

.student-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.student-tag {
  background: var(--color-primary-light);
  color: var(--color-primary-hover);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-lg);
  font-size: var(--text-xs);
}

.student-tag small {
  color: var(--color-text-muted);
  margin-left: var(--space-1);
}

.bind-effects {
  background: var(--color-warning-light);
  border: 1px solid var(--color-warning-light);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  margin-bottom: var(--space-4);
}

.effects-title {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--color-warning-hover);
  margin: 0 0 var(--space-2);
}

.bind-effects ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.bind-effects li {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-warning-hover);
  padding: 2px 0;
}

.bind-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.btn-primary,
.btn-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-5);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: var(--transition-all);
}

.btn-primary {
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
}

.btn-primary:hover:not(:disabled) {
  box-shadow: var(--shadow-primary);
  transform: translateY(-2px);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-danger {
  background: var(--color-danger-light);
  color: var(--color-danger);
  border: 1px solid var(--color-danger-light);
}

.btn-danger:hover:not(:disabled) {
  background: var(--color-danger-light);
}

.btn-help {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-decoration: none;
  margin-left: auto;
}

.help-box {
  margin-top: var(--space-4);
  background: var(--color-info-light);
  border: 1px solid var(--color-info-light);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}

.help-box h4 {
  font-size: var(--text-sm);
  color: var(--color-info);
  margin: 0 0 var(--space-2);
}

.help-box ol {
  padding-left: var(--space-4);
  margin: 0;
}

.help-box li {
  font-size: var(--text-xs);
  color: var(--color-info);
  padding: 2px 0;
}

.help-note {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  margin: var(--space-2) 0 0;
}
</style>
