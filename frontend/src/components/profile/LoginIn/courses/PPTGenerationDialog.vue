<template>
  <Teleport to="body">
    <div v-if="visible" class="ppt-gen-overlay" @click="handleClose">
      <div class="ppt-gen-modal" @click.stop>
        <div class="modal-header">
          <h3>AI生成PPT课件</h3>
          <button class="close-btn" @click="handleClose"><X :size="20" /></button>
        </div>

        <div class="modal-body">
          <!-- 步骤1: 输入信息 -->
          <div v-if="step === 1" class="step-content">
            <div class="form-group">
              <label class="form-label">课程主题 <span class="required">*</span></label>
              <input
                v-model="form.topic"
                type="text"
                class="form-input"
                placeholder="例如：金属的晶体结构"
                maxlength="500"
              />
            </div>

            <div class="form-group">
              <label class="form-label">课程大纲</label>
              <textarea
                v-model="form.outline"
                class="form-textarea"
                placeholder="可选：输入课程大纲，帮助AI生成更精准的课件内容"
                rows="4"
              ></textarea>
            </div>

            <div class="form-group">
              <label class="form-label">知识点列表</label>
              <div class="knowledge-points-input">
                <div v-for="(kp, idx) in form.knowledgePoints" :key="idx" class="kp-row">
                  <input
                    v-model="form.knowledgePoints[idx]"
                    type="text"
                    class="form-input kp-input"
                    :placeholder="`知识点 ${idx + 1}`"
                  />
                  <button class="kp-remove" @click="removeKnowledgePoint(idx)" v-if="form.knowledgePoints.length > 1">
                    <X :size="16" />
                  </button>
                </div>
                <button class="kp-add" @click="addKnowledgePoint">
                  <Plus :size="14" />
                  添加知识点
                </button>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group half">
                <label class="form-label">PPT作者</label>
                <input v-model="form.author" type="text" class="form-input" placeholder="AI智课" />
              </div>
              <div class="form-group half">
                <label class="checkbox-label">
                  <input v-model="form.search" type="checkbox" />
                  联网搜索补充内容
                </label>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">PPT模板</label>
              <div class="template-select">
                <select v-model="form.templateId" class="form-select">
                  <option value="">默认模板</option>
                  <option v-for="t in templates" :key="t.id" :value="t.id">
                    {{ t.name }} ({{ t.style || '通用' }})
                  </option>
                </select>
                <button class="refresh-btn" @click="loadTemplates" :disabled="loadingTemplates">
                  {{ loadingTemplates ? '加载中...' : '刷新模板' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 步骤2: 生成中 -->
          <div v-if="step === 2" class="step-content generating">
            <div class="generating-animation">
              <div class="spinner large"></div>
            </div>
            <div class="generating-text">
              <h4>正在生成PPT课件...</h4>
              <p>{{ statusMessage }}</p>
            </div>
            <div class="progress-bar-container">
              <div class="progress-bar-fill" :style="{ width: progressPercent + '%' }"></div>
            </div>
          </div>

          <!-- 步骤3: 完成 -->
          <div v-if="step === 3" class="step-content result">
            <div class="result-icon success"><CheckCircle :size="48" /></div>
            <h4>PPT课件生成完成！</h4>
            <div class="result-info">
              <div class="info-item">
                <span class="info-label">课程ID:</span>
                <span class="info-value">{{ result.courseId }}</span>
              </div>
              <div class="info-item" v-if="result.totalNodes">
                <span class="info-label">知识点数量:</span>
                <span class="info-value">{{ result.totalNodes }}</span>
              </div>
              <div class="info-item" v-if="result.totalDuration">
                <span class="info-label">预计时长:</span>
                <span class="info-value">{{ Math.round(result.totalDuration / 60) }}分钟</span>
              </div>
            </div>
          </div>

          <!-- 步骤4: 失败 -->
          <div v-if="step === 4" class="step-content result">
            <div class="result-icon error"><XCircle :size="48" /></div>
            <h4>PPT生成失败</h4>
            <p class="error-message">{{ errorMessage }}</p>
            <button class="action-btn" @click="step = 1">重新尝试</button>
          </div>
        </div>

        <div class="modal-footer">
          <button v-if="step === 1" class="cancel-btn" @click="handleClose">取消</button>
          <button
            v-if="step === 1"
            class="generate-btn"
            @click="handleGenerate"
            :disabled="!form.topic.trim() || isGenerating"
          >
            {{ isGenerating ? '生成中...' : '生成PPT课件' }}
          </button>
          <button v-if="step === 2" class="cancel-btn" @click="handleCancelGenerate">取消生成</button>
          <button v-if="step === 3" class="generate-btn" @click="handleOpenCourse">打开课程</button>
          <button v-if="step === 3" class="cancel-btn" @click="handleClose">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { X, CheckCircle, XCircle, Plus } from 'lucide-vue-next'
import { generatePPTSync, getPPTThemes } from '@/api/ppt_generation.js'
import { showToast } from '@/utils/toast'

const props = defineProps({
  visible: Boolean,
  courseId: [Number, String],
})

const emit = defineEmits(['update:visible', 'generated'])

const router = useRouter()

const step = ref(1)
const isGenerating = ref(false)
const loadingTemplates = ref(false)
const templates = ref([])
const errorMessage = ref('')
const statusMessage = ref('')
const progressPercent = ref(0)
const result = reactive({
  courseId: null,
  totalNodes: null,
  totalDuration: null,
})

const form = reactive({
  topic: '',
  outline: '',
  knowledgePoints: [''],
  templateId: '',
  author: 'AI智课',
  search: false,
})

watch(() => props.visible, (val) => {
  if (val) {
    step.value = 1
    progressPercent.value = 0
    statusMessage.value = ''
    errorMessage.value = ''
    result.courseId = null
    result.totalNodes = null
    result.totalDuration = null
    loadTemplates()
  }
})

async function loadTemplates() {
  loadingTemplates.value = true
  try {
    const res = await getPPTThemes({ pay_type: 'free', page_size: 20 })
    if (res.data?.code === 200 && res.data?.data?.templateList) {
      templates.value = res.data.data.templateList.map(t => ({
        id: t.id || t.templateId,
        name: t.name || t.title,
        style: t.style,
      }))
    }
  } catch (e) {
    console.warn('加载模板列表失败:', e)
  } finally {
    loadingTemplates.value = false
  }
}

function addKnowledgePoint() {
  form.knowledgePoints.push('')
}

function removeKnowledgePoint(idx) {
  form.knowledgePoints.splice(idx, 1)
}

async function handleGenerate() {
  if (!form.topic.trim()) return

  isGenerating.value = true
  step.value = 2
  statusMessage.value = '步骤1/3: LLM扩展教学脚本...'
  progressPercent.value = 10

  try {
    // 模拟进度更新
    const progressTimer = setInterval(() => {
      if (progressPercent.value < 90) {
        progressPercent.value += 2
      }
    }, 3000)

    statusMessage.value = '步骤2/3: 调用讯飞PPT API生成课件...'

    const knowledgePoints = form.knowledgePoints.filter(kp => kp.trim())
    const res = await generatePPTSync({
      topic: form.topic.trim(),
      outline: form.outline.trim() || undefined,
      knowledge_points: knowledgePoints.length > 0 ? knowledgePoints : undefined,
      template_id: form.templateId || undefined,
      author: form.author || 'AI智课',
      search: form.search,
      auto_parse: true,
    })

    clearInterval(progressTimer)

    if (res.data?.code === 200) {
      progressPercent.value = 100
      statusMessage.value = '步骤3/3: 解析完成！'

      result.courseId = res.data.data.course_id
      result.totalNodes = res.data.data.total_nodes
      result.totalDuration = res.data.data.total_duration

      step.value = 3
      showToast('PPT课件生成完成！', 'success')
      emit('generated', res.data.data)
    } else {
      errorMessage.value = res.data?.message || '生成失败'
      step.value = 4
      showToast(errorMessage.value, 'error')
    }
  } catch (e) {
    errorMessage.value = e.message || '网络请求失败'
    step.value = 4
    showToast('PPT生成失败: ' + errorMessage.value, 'error')
  } finally {
    isGenerating.value = false
  }
}

function handleCancelGenerate() {
  step.value = 1
  isGenerating.value = false
}

function handleOpenCourse() {
  if (result.courseId) {
    handleClose()
    router.push(`/teacher?courseId=${result.courseId}`)
  }
}

function handleClose() {
  emit('update:visible', false)
}
</script>

<style scoped>
.ppt-gen-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal);
}

.ppt-gen-modal {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  width: 600px;
  max-width: 90vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  color: var(--color-text);
}

.close-btn {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background: var(--color-surface-2);
  color: var(--color-text);
}

.modal-body {
  padding: var(--space-5);
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
}

/* 表单样式 */
.form-group {
  margin-bottom: var(--space-4);
}

.form-group.half {
  flex: 1;
}

.form-label {
  display: block;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-text);
  margin-bottom: var(--space-1);
}

.required {
  color: var(--color-danger);
}

.form-input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  transition: border-color var(--duration-slow) var(--ease);
  box-sizing: border-box;
}

.form-input:focus {
  border-color: var(--color-primary);
  outline: none;
  box-shadow: 0 0 0 2px var(--color-primary-light);
}

.form-textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  resize: vertical;
  min-height: 80px;
  box-sizing: border-box;
}

.form-textarea:focus {
  border-color: var(--color-primary);
  outline: none;
}

.form-select {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.form-row {
  display: flex;
  gap: var(--space-4);
}

/* 知识点输入 */
.knowledge-points-input {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.kp-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.kp-input {
  flex: 1;
}

.kp-remove {
  background: none;
  border: none;
  color: var(--color-danger);
  cursor: pointer;
  padding: var(--space-1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.kp-add {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  background: none;
  border: 1px dashed var(--color-border);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-primary);
  font-size: 13px;
  transition: border-color var(--duration-slow) var(--ease);
}

.kp-add:hover {
  border-color: var(--color-primary);
}

/* 模板选择 */
.template-select {
  display: flex;
  gap: var(--space-2);
}

.refresh-btn {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}

.refresh-btn:hover {
  background: var(--color-surface-3);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text);
  padding-top: 28px;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  width: var(--space-4);
  height: var(--space-4);
  cursor: pointer;
}

/* 生成中 */
.generating {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-7) var(--space-5);
  text-align: center;
}

.generating-animation {
  margin-bottom: var(--space-5);
}

.spinner.large {
  width: var(--space-8);
  height: var(--space-8);
  border: 4px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: var(--radius-full);
  animation: spin 1s linear infinite;
}

.generating-text h4 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
  color: var(--color-text);
}

.generating-text p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.progress-bar-container {
  width: 100%;
  max-width: 400px;
  height: 6px;
  background: var(--color-border);
  border-radius: var(--radius-sm);
  margin-top: var(--space-5);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: var(--gradient-primary);
  border-radius: var(--radius-sm);
  transition: width var(--duration-slow) var(--ease);
}

/* 结果 */
.result {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 30px var(--space-5);
  text-align: center;
}

.result-icon {
  margin-bottom: var(--space-4);
}

.result-icon.success {
  color: var(--color-success);
}

.result-icon.error {
  color: var(--color-danger);
}

.result h4 {
  margin: 0 0 var(--space-4);
  font-size: var(--text-lg);
  color: var(--color-text);
}

.result-info {
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  width: 100%;
  max-width: 400px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  padding: var(--space-1) 0;
  font-size: var(--text-sm);
}

.info-label {
  color: var(--color-text-secondary);
}

.info-value {
  color: var(--color-text);
  font-weight: var(--font-medium);
}

.error-message {
  color: var(--color-danger);
  font-size: var(--text-sm);
  margin: var(--space-3) 0;
  max-width: 400px;
}

/* 按钮 */
.cancel-btn {
  padding: var(--space-2) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--color-text);
  transition: all var(--duration-normal) var(--ease);
}

.cancel-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.generate-btn {
  padding: var(--space-2) var(--space-5);
  border: none;
  border-radius: var(--radius-sm);
  background: var(--gradient-primary);
  color: var(--color-text-inverse);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  transition: all var(--duration-normal) var(--ease);
}

.generate-btn:hover:not(:disabled) {
  transform: translateY(-2px);
}

.generate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn {
  padding: var(--space-2) var(--space-5);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-primary);
  cursor: pointer;
  font-size: var(--text-sm);
  margin-top: var(--space-3);
  transition: all var(--duration-normal) var(--ease);
}

.action-btn:hover {
  background: var(--color-primary-light);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .ppt-gen-modal {
    width: 95vw;
    max-height: 90vh;
  }

  .form-row {
    flex-direction: column;
    gap: 0;
  }

  .checkbox-label {
    padding-top: 0;
  }

  .template-select {
    flex-direction: column;
  }
}
</style>
