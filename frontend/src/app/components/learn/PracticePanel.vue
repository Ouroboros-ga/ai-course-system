<script setup>
/**
 * 批次1 练习闭环：学生练习面板。
 *
 * 流程：加载已发布题目 -> 选择/填写答案 -> 提交 attempt -> 自动判分 -> 错题反馈 -> 下一题
 * 对接 /api/v1/question-bank 端点，仅展示已发布题目（后端强制）。
 * 判分结果写入评分型 LearningEvidence（后端 B1-4 已接线）。
 */
import { computed, onMounted, ref } from 'vue'
import { listCourseQuestions, submitAttempt } from '@/api/question_bank.js'

const props = defineProps({
  courseId: { type: Number, required: true },
  nodeIndex: { type: Number, default: null },
})
const emit = defineEmits(['exit'])

const questions = ref([])
const currentIndex = ref(0)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')

const selectedAnswer = ref(null)
const typedAnswer = ref('')
const lastResult = ref(null) // { is_correct, score, judgement_status }

const currentQuestion = computed(() => questions.value[currentIndex.value] ?? null)
const hasQuestions = computed(() => questions.value.length > 0)
const progressText = computed(() =>
  hasQuestions.value ? `${currentIndex.value + 1} / ${questions.value.length}` : ''
)

const isObjective = computed(() => {
  const t = currentQuestion.value?.question_type
  return ['single_choice', 'multi_choice', 'true_false', 'fill_blank'].includes(t)
})

async function loadQuestions() {
  loading.value = true
  error.value = ''
  try {
    const res = await listCourseQuestions(props.courseId, { page_size: 20 })
    questions.value = res?.items ?? []
    if (questions.value.length === 0) {
      error.value = '当前课程暂无已发布的练习题'
    }
  } catch (e) {
    error.value = e?.message || '题目加载失败'
  } finally {
    loading.value = false
  }
}

function resetAnswer() {
  selectedAnswer.value = null
  typedAnswer.value = ''
  lastResult.value = null
}

async function submitAnswer() {
  const q = currentQuestion.value
  if (!q) return

  let answer
  if (isObjective.value && q.question_type !== 'fill_blank') {
    answer = selectedAnswer.value
    if (answer === null || answer === undefined || answer === '') {
      error.value = '请先选择一个答案'
      return
    }
  } else {
    answer = typedAnswer.value.trim()
    if (!answer) {
      error.value = '请先填写答案'
      return
    }
  }

  error.value = ''
  submitting.value = true
  try {
    const res = await submitAttempt(props.courseId, q.id, answer)
    lastResult.value = res
  } catch (e) {
    error.value = e?.message || '提交失败，请重试'
  } finally {
    submitting.value = false
  }
}

function nextQuestion() {
  resetAnswer()
  if (currentIndex.value < questions.value.length - 1) {
    currentIndex.value++
  } else {
    currentIndex.value = 0
  }
}

function retryQuestion() {
  resetAnswer()
}

onMounted(() => {
  loadQuestions()
})
</script>

<template>
  <div class="sfx-practice">
    <div class="sfx-practice-header">
      <h3 class="sfx-practice-title">试一试</h3>
      <span v-if="hasQuestions" class="sfx-practice-progress">{{ progressText }}</span>
      <button class="sfx-practice-close" @click="emit('exit')">返回课程</button>
    </div>

    <div v-if="loading" class="sfx-practice-loading">题目加载中…</div>

    <div v-else-if="error && !hasQuestions" class="sfx-practice-empty">
      <p>{{ error }}</p>
      <button class="sfx-practice-retry-btn" @click="loadQuestions">重新加载</button>
    </div>

    <div v-else-if="currentQuestion" class="sfx-practice-body">
      <div class="sfx-practice-q">
        <span class="sfx-practice-q-type">{{ currentQuestion.question_type }}</span>
        <span v-if="currentQuestion.difficulty" class="sfx-practice-q-diff">{{ currentQuestion.difficulty }}</span>
        <p class="sfx-practice-q-text">{{ currentQuestion.question_text }}</p>
      </div>

      <!-- 选择题 -->
      <div v-if="currentQuestion.options && currentQuestion.options.length && currentQuestion.question_type !== 'fill_blank'" class="sfx-practice-options">
        <label
          v-for="(opt, i) in currentQuestion.options"
          :key="i"
          class="sfx-practice-option"
          :class="{
            'is-selected': selectedAnswer === opt,
            'is-disabled': lastResult !== null,
          }"
        >
          <input
            :type="currentQuestion.question_type === 'multi_choice' ? 'checkbox' : 'radio'"
            :value="opt"
            v-model="selectedAnswer"
            :disabled="lastResult !== null"
          />
          <span>{{ opt }}</span>
        </label>
      </div>

      <!-- 填空/简答 -->
      <div v-else class="sfx-practice-input">
        <textarea
          v-model="typedAnswer"
          :disabled="lastResult !== null"
          placeholder="在此输入你的答案…"
          rows="3"
        ></textarea>
      </div>

      <!-- 判分结果与错题反馈 -->
      <div v-if="lastResult" class="sfx-practice-result" :class="lastResult.is_correct ? 'is-correct' : 'is-wrong'">
        <template v-if="lastResult.judgement_status === 'judged'">
          <p v-if="lastResult.is_correct" class="sfx-practice-verdict correct">回答正确</p>
          <div v-else class="sfx-practice-wrong-feedback">
            <p class="sfx-practice-verdict wrong">回答不正确</p>
            <p class="sfx-practice-feedback-hint">
              错题反馈：请回顾当前知识点后重试，或继续学习讲义中相关内容。
            </p>
          </div>
          <p class="sfx-practice-score">得分：{{ Math.round((lastResult.score ?? 0) * 100) }}分</p>
        </template>
        <template v-else>
          <p class="sfx-practice-verdict pending">已提交，等待教师批改</p>
        </template>
      </div>

      <!-- 操作按钮 -->
      <div class="sfx-practice-actions">
        <button v-if="!lastResult" class="sfx-practice-submit" :disabled="submitting" @click="submitAnswer">
          {{ submitting ? '提交中…' : '提交答案' }}
        </button>
        <template v-else>
          <button v-if="!lastResult.is_correct && lastResult.judgement_status === 'judged'" class="sfx-practice-retry" @click="retryQuestion">
            重新作答
          </button>
          <button class="sfx-practice-next" @click="nextQuestion">下一题</button>
        </template>
      </div>

      <p v-if="error" class="sfx-practice-error">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.sfx-practice {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  overflow-y: auto;
}
.sfx-practice-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.sfx-practice-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}
.sfx-practice-progress {
  color: var(--text-muted, #888);
  font-size: 0.85rem;
}
.sfx-practice-close {
  margin-left: auto;
  background: none;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
  font-size: 0.85rem;
}
.sfx-practice-close:hover {
  background: var(--surface-hover, #f5f5f5);
}
.sfx-practice-q {
  padding: 12px;
  background: var(--surface-card, #fff);
  border-radius: 8px;
  border: 1px solid var(--border-default, #eee);
}
.sfx-practice-q-type,
.sfx-practice-q-diff {
  display: inline-block;
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-muted, #f0f0f0);
  color: var(--text-secondary, #666);
  margin-right: 6px;
}
.sfx-practice-q-text {
  margin: 8px 0 0 0;
  font-size: 1rem;
  line-height: 1.5;
}
.sfx-practice-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sfx-practice-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-default, #eee);
  border-radius: 6px;
  cursor: pointer;
}
.sfx-practice-option.is-selected {
  border-color: var(--accent-primary, #4f8cf7);
  background: var(--accent-bg, #e8f0fe);
}
.sfx-practice-option.is-disabled {
  cursor: default;
  opacity: 0.7;
}
.sfx-practice-input textarea {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  font-size: 0.95rem;
  resize: vertical;
}
.sfx-practice-result {
  padding: 12px;
  border-radius: 8px;
}
.sfx-practice-result.is-correct {
  background: #e8f5e9;
  border: 1px solid #a5d6a7;
}
.sfx-practice-result.is-wrong {
  background: #ffebee;
  border: 1px solid #ef9a9a;
}
.sfx-practice-verdict {
  margin: 0 0 4px 0;
  font-weight: 600;
}
.sfx-practice-verdict.correct { color: #2e7d32; }
.sfx-practice-verdict.wrong { color: #c62828; }
.sfx-practice-verdict.pending { color: #f57f17; }
.sfx-practice-feedback-hint {
  margin: 4px 0 0 0;
  font-size: 0.85rem;
  color: #555;
}
.sfx-practice-score {
  margin: 4px 0 0 0;
  font-size: 0.85rem;
  color: #666;
}
.sfx-practice-actions {
  display: flex;
  gap: 8px;
}
.sfx-practice-submit,
.sfx-practice-next,
.sfx-practice-retry {
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  font-size: 0.9rem;
  cursor: pointer;
}
.sfx-practice-submit {
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
}
.sfx-practice-submit:disabled {
  opacity: 0.6;
  cursor: default;
}
.sfx-practice-next {
  background: var(--surface-muted, #e0e0e0);
  color: #333;
}
.sfx-practice-retry {
  background: #fff3e0;
  color: #e65100;
  border: 1px solid #ffcc80;
}
.sfx-practice-error {
  color: #c62828;
  font-size: 0.85rem;
}
.sfx-practice-loading,
.sfx-practice-empty {
  text-align: center;
  padding: 32px;
  color: var(--text-muted, #888);
}
.sfx-practice-retry-btn {
  margin-top: 8px;
  padding: 6px 16px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  cursor: pointer;
}
</style>
