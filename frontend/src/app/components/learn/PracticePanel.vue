<script setup>
/**
 * 批次1 练习闭环：学生练习面板（P2 §三.1 增强）。
 *
 * 三阶段流程：
 *   intro       —— PRACTICE 首屏上下文（学习目标/任务说明/完成条件/沙箱权限摘要/返回位置）
 *   practicing  —— 加载题目 -> 选择/填写 -> 提交 attempt -> 判分 -> 错题反馈 -> 下一题
 *   verify      —— VERIFY 验证完成（本次做了什么/结果/证据/关注点/下一步）
 *
 * 对接 /api/v1/question-bank 端点，仅展示已发布题目（后端强制）。
 * 判分结果写入评分型 LearningEvidence（后端 B1-4 已接线）。
 * 对齐 page-design.md §12.6 PRACTICE 试一试 与 §12.10 VERIFY 验证完成。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { listCourseQuestions, submitAttempt } from '@/api/question_bank.js'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  courseId: { type: Number, required: true },
  nodeIndex: { type: Number, default: null },
})
const emit = defineEmits(['exit'])

// 三阶段：intro（上下文首屏） -> practicing（做题） -> verify（完成验证）
const practicePhase = ref('intro')

const questions = ref([])
const currentIndex = ref(0)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')

const selectedAnswer = ref(null)
const typedAnswer = ref('')
const lastResult = ref(null) // { is_correct, score, judgement_status }
// 提示使用埋点：作答前查看过提示则记 hint_used=true，随 attempt 上报，
// 写入 cognitive_context 供认知引擎计算 hint_dependency（提示依赖度）。
const hintUsed = ref(false)
const hintVisible = ref(false)

// 本次练习统计（用于 VERIFY 阶段）
const attempted = ref([]) // [{ questionId, isCorrect, score, judgementStatus }]

const currentQuestion = computed(() => questions.value[currentIndex.value] ?? null)
const hasQuestions = computed(() => questions.value.length > 0)
const progressText = computed(() =>
  hasQuestions.value ? `${currentIndex.value + 1} / ${questions.value.length}` : ''
)

const isMultiChoice = computed(() => currentQuestion.value?.question_type === 'multi_choice')

// 后端 options 是 dict（如 {"A": "...", "B": "..."}），无 .length 属性。
// 仅当 options 非空且题型为客观选择时才用选项面板；fill_blank/short_answer 回退到文本输入。
const hasOptions = computed(() => {
  const q = currentQuestion.value
  if (!q) return false
  const opts = q.options
  if (!opts || typeof opts !== 'object') return false
  return Object.keys(opts).length > 0
    && ['single_choice', 'multi_choice', 'true_false'].includes(q.question_type)
})

// 题目切换时按题型重置答案容器：多选为数组，其余为单值。
watch(currentQuestion, (q) => {
  selectedAnswer.value = q && q.question_type === 'multi_choice' ? [] : null
  typedAnswer.value = ''
  lastResult.value = null
  hintUsed.value = false
  hintVisible.value = false
})

// VERIFY 阶段统计
const stats = computed(() => {
  const total = attempted.value.length
  const judged = attempted.value.filter(a => a.judgementStatus === 'judged')
  const correct = judged.filter(a => a.isCorrect).length
  const wrong = judged.length - correct
  const pending = total - judged.length
  const avgScore = judged.length > 0
    ? judged.reduce((s, a) => s + (a.score ?? 0), 0) / judged.length
    : 0
  // 评分型证据数 = judged 的 attempt 数（后端 record_scored_evidence 对每个 judged attempt 写一条 QUIZ_ACCURACY 证据）
  const evidenceCount = judged.length
  return { total, judged: judged.length, correct, wrong, pending, avgScore, evidenceCount }
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
  // 多选题需绑定数组以支持 checkbox 多选；其余为单值
  selectedAnswer.value = isMultiChoice.value ? [] : null
  typedAnswer.value = ''
  lastResult.value = null
  hintUsed.value = false
  hintVisible.value = false
}

// 查看提示：标记 hint_used=true（随本次 attempt 上报），并展示一条通用提示。
// QuestionBankItem 暂无专用提示字段，故给出指向当前知识点讲解的通用引导。
function showHint() {
  hintUsed.value = true
  hintVisible.value = true
}

async function submitAnswer() {
  const q = currentQuestion.value
  if (!q) return

  let answer
  if (hasOptions.value) {
    // 选择题提交选项 key（后端 answer 存 key，如 "A" 或 "A,B,C"）
    if (isMultiChoice.value) {
      if (!Array.isArray(selectedAnswer.value) || selectedAnswer.value.length === 0) {
        error.value = '请至少选择一个选项'
        return
      }
      // 排序后逗号拼接；后端 _normalize_objective_answer 会按分隔符归一化
      answer = [...selectedAnswer.value].sort().join(',')
    } else {
      if (selectedAnswer.value === null || selectedAnswer.value === undefined || selectedAnswer.value === '') {
        error.value = '请先选择一个答案'
        return
      }
      answer = String(selectedAnswer.value)
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
    const res = await submitAttempt(props.courseId, q.id, answer, { hintUsed: hintUsed.value })
    lastResult.value = res
    // 记录到本次统计（按 questionId 去重，保留最新结果）
    const idx = attempted.value.findIndex(a => a.questionId === q.id)
    const entry = {
      questionId: q.id,
      isCorrect: res.is_correct,
      score: res.score,
      judgementStatus: res.judgement_status,
    }
    if (idx >= 0) attempted.value[idx] = entry
    else attempted.value.push(entry)
  } catch (e) {
    error.value = e?.message || '提交失败，请重试'
  } finally {
    submitting.value = false
  }
}

function nextQuestion() {
  if (currentIndex.value < questions.value.length - 1) {
    currentIndex.value++
  } else {
    currentIndex.value = 0
  }
  // 切换后按新题型重置；watch 也会触发，但循环回同一索引时 watch 不触发，故显式调用兜底
  resetAnswer()
}

function retryQuestion() {
  resetAnswer()
}

// 进入做题阶段
function startPracticing() {
  practicePhase.value = 'practicing'
}

// 完成练习，进入 VERIFY 阶段（page-design §12.10）
function finishPractice() {
  practicePhase.value = 'verify'
}

// VERIFY 阶段：再练一题（回到 practicing 并重置索引到第一题）
function practiceMore() {
  attempted.value = []
  currentIndex.value = 0
  resetAnswer()
  practicePhase.value = 'practicing'
}

onMounted(() => {
  loadQuestions()
})
</script>

<template>
  <div class="sfx-practice">
    <div class="sfx-practice-header">
      <h3 class="sfx-practice-title">试一试</h3>
      <span v-if="hasQuestions && practicePhase === 'practicing'" class="sfx-practice-progress">{{ progressText }}</span>
      <button class="sfx-practice-close" @click="emit('exit')">返回课程</button>
    </div>

    <!-- intro 阶段：PRACTICE 首屏上下文（page-design §12.6） -->
    <div v-if="practicePhase === 'intro'" class="sfx-practice-intro">
      <div class="sfx-practice-intro-section">
        <h4 class="sfx-practice-intro-title">为什么进入这个实践</h4>
        <p class="sfx-practice-intro-text">
          通过练习巩固当前课程知识点，将讲解内容转化为可验证的掌握度证据。
        </p>
      </div>
      <div class="sfx-practice-intro-section">
        <h4 class="sfx-practice-intro-title">学习目标</h4>
        <ul class="sfx-practice-intro-list">
          <li>检验对当前知识点的理解程度</li>
          <li>暴露薄弱环节，生成针对性补弱建议</li>
          <li>积累评分型证据，支撑六维认知状态计算</li>
        </ul>
      </div>
      <div class="sfx-practice-intro-section">
        <h4 class="sfx-practice-intro-title">任务说明</h4>
        <p class="sfx-practice-intro-text">
          依次作答已发布的练习题，提交后系统自动判分（客观题）或等待教师批改（主观题）。
          每道题作答后可查看反馈，答错可重试。
        </p>
      </div>
      <div class="sfx-practice-intro-section">
        <h4 class="sfx-practice-intro-title">完成条件</h4>
        <ul class="sfx-practice-intro-list">
          <li>至少作答 1 道题目</li>
          <li>可随时点击“完成练习”进入验证总结</li>
        </ul>
      </div>
      <div class="sfx-practice-intro-section">
        <h4 class="sfx-practice-intro-title">返回课程位置</h4>
        <p class="sfx-practice-intro-text">
          点击右上角“返回课程”可随时回到当前学习位置；练习进度会保留在本面板内。
        </p>
      </div>
      <div class="sfx-practice-intro-section">
        <h4 class="sfx-practice-intro-title">当前沙箱权限摘要</h4>
        <ul class="sfx-practice-intro-list sfx-practice-sandbox">
          <li>仅读取本课程已发布题目</li>
          <li>仅写入本人答题记录与评分型证据</li>
          <li>不修改课程图谱、不调用代码沙箱、不发起外部检索</li>
        </ul>
      </div>
      <div class="sfx-practice-intro-actions">
        <SfxButton variant="primary" :disabled="loading || !hasQuestions" @click="startPracticing">
          {{ loading ? '加载中…' : (hasQuestions ? '开始练习' : '暂无题目') }}
        </SfxButton>
        <p v-if="error && !hasQuestions" class="sfx-practice-error">{{ error }}</p>
      </div>
    </div>

    <!-- practicing 阶段 -->
    <div v-else-if="practicePhase === 'practicing'">
      <div v-if="loading" class="sfx-practice-loading">题目加载中…</div>

      <div v-else-if="error && !hasQuestions" class="sfx-practice-empty">
        <p>{{ error }}</p>
        <SfxButton variant="secondary" @click="loadQuestions">重新加载</SfxButton>
      </div>

      <div v-else-if="currentQuestion" class="sfx-practice-body">
        <div class="sfx-practice-q">
          <span class="sfx-practice-q-type">{{ currentQuestion.question_type }}</span>
          <span v-if="currentQuestion.difficulty" class="sfx-practice-q-diff">{{ currentQuestion.difficulty }}</span>
          <p class="sfx-practice-q-text">{{ currentQuestion.question_text }}</p>
        </div>

        <!-- 选择题：options 是 dict（如 {"A": "...", "B": "..."}），迭代 entries 取 key/text -->
        <div v-if="hasOptions" class="sfx-practice-options">
          <label
            v-for="([optKey, optText], i) in Object.entries(currentQuestion.options)"
            :key="i"
            class="sfx-practice-option"
            :class="{
              'is-selected': isMultiChoice
                ? Array.isArray(selectedAnswer) && selectedAnswer.includes(optKey)
                : selectedAnswer === optKey,
              'is-disabled': lastResult !== null,
            }"
          >
            <input
              :type="isMultiChoice ? 'checkbox' : 'radio'"
              :value="optKey"
              v-model="selectedAnswer"
              :disabled="lastResult !== null"
            />
            <span>{{ optKey }}. {{ optText }}</span>
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

        <!-- 提示使用埋点：作答前可查看提示，查看后本次 attempt 记 hint_used=true -->
        <div v-if="!lastResult" class="sfx-practice-hint">
          <SfxButton v-if="!hintVisible" variant="tertiary" size="sm" @click="showHint">
            查看提示
          </SfxButton>
          <p v-else class="sfx-practice-hint-text">
            提示：回顾当前知识点讲解中的关键概念与示例，再结合题干作答。
            <span class="sfx-practice-hint-tag">已记录提示使用</span>
          </p>
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
          <SfxButton v-if="!lastResult" variant="primary" :disabled="submitting" @click="submitAnswer">
            {{ submitting ? '提交中…' : '提交答案' }}
          </SfxButton>
          <template v-else>
            <SfxButton v-if="!lastResult.is_correct && lastResult.judgement_status === 'judged'" variant="secondary" @click="retryQuestion">
              重新作答
            </SfxButton>
            <SfxButton variant="tertiary" @click="nextQuestion">下一题</SfxButton>
          </template>
          <SfxButton
            v-if="attempted.length > 0"
            variant="primary"
            @click="finishPractice"
            title="结束练习并查看本次总结"
          >
            完成练习
          </SfxButton>
        </div>

        <p v-if="error" class="sfx-practice-error">{{ error }}</p>
      </div>
    </div>

    <!-- verify 阶段：VERIFY 验证完成（page-design §12.10） -->
    <div v-else class="sfx-practice-verify">
      <h4 class="sfx-practice-verify-title">本次练习总结</h4>

      <div class="sfx-practice-verify-section">
        <h5 class="sfx-practice-verify-subtitle">本次做了什么</h5>
        <p class="sfx-practice-verify-text">
          在本课程练习面板作答了 {{ stats.total }} 道题目，其中 {{ stats.judged }} 道已判分，
          {{ stats.pending }} 道等待教师批改。
        </p>
      </div>

      <div class="sfx-practice-verify-section">
        <h5 class="sfx-practice-verify-subtitle">获得了什么结果</h5>
        <p class="sfx-practice-verify-text">
          正确 {{ stats.correct }} 题，错误 {{ stats.wrong }} 题，
          平均得分 {{ Math.round(stats.avgScore * 100) }} 分。
        </p>
      </div>

      <div class="sfx-practice-verify-section">
        <h5 class="sfx-practice-verify-subtitle">哪些证据被记录</h5>
        <p class="sfx-practice-verify-text">
          已判分的 {{ stats.evidenceCount }} 次 attempt 会生成等量的评分型 LearningEvidence
          （类型 quiz_accuracy），写入六维认知状态计算，作为后续推荐的依据。
        </p>
      </div>

      <div class="sfx-practice-verify-section">
        <h5 class="sfx-practice-verify-subtitle">仍需关注什么</h5>
        <p class="sfx-practice-verify-text">
          <span v-if="stats.pending > 0">{{ stats.pending }} 道题等待教师批改，结果出来后会更新证据。</span>
          <span v-if="stats.wrong > 0">错误题 {{ stats.wrong }} 道，建议回顾相关知识点后重试。</span>
          <span v-if="stats.judged === 0">尚无已判分题目，无法生成本次掌握度结论。</span>
        </p>
      </div>

      <div class="sfx-practice-verify-section">
        <h5 class="sfx-practice-verify-subtitle">下一步</h5>
        <div class="sfx-practice-verify-actions">
          <button class="sfx-practice-verify-primary" @click="emit('exit')">返回课程</button>
          <SfxButton variant="secondary" @click="practiceMore">再练一题</SfxButton>
        </div>
      </div>
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
/* 移动端（design.md §12.5）：练习面板在纵向堆叠中作为独立区块 */
@media (max-width: 760px) {
  .sfx-practice {
    min-height: 60vh;
    border-top: 1px solid var(--border-default);
  }
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
.sfx-practice-intro {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sfx-practice-intro-section {
  padding: 12px;
  background: var(--surface-card, #fff);
  border-radius: 8px;
  border: 1px solid var(--border-default, #eee);
}
.sfx-practice-intro-title {
  margin: 0 0 6px 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary, #333);
}
.sfx-practice-intro-text {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text-secondary, #555);
}
.sfx-practice-intro-list {
  margin: 0;
  padding-left: 18px;
  font-size: 0.85rem;
  line-height: 1.6;
  color: var(--text-secondary, #555);
}
.sfx-practice-sandbox li {
  list-style: none;
  position: relative;
  padding-left: 14px;
}
.sfx-practice-sandbox li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--accent-primary, #4f8cf7);
}
.sfx-practice-intro-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
}
.sfx-practice-start {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.95rem;
  cursor: pointer;
}
.sfx-practice-start:disabled {
  opacity: 0.6;
  cursor: default;
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
.sfx-practice-hint {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sfx-practice-hint-btn {
  align-self: flex-start;
  padding: 4px 12px;
  border: 1px dashed var(--border-default, #ccc);
  border-radius: 6px;
  background: var(--surface-muted, #f7f7f7);
  color: var(--text-secondary, #666);
  font-size: 0.82rem;
  cursor: pointer;
}
.sfx-practice-hint-btn:hover {
  background: var(--surface-hover, #efefef);
}
.sfx-practice-hint-text {
  margin: 0;
  padding: 8px 12px;
  background: #fff8e1;
  border: 1px solid #ffe082;
  border-radius: 6px;
  font-size: 0.85rem;
  line-height: 1.5;
  color: #5d4037;
}
.sfx-practice-hint-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #ffe082;
  color: #5d4037;
  font-size: 0.75rem;
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
  flex-wrap: wrap;
}
.sfx-practice-submit,
.sfx-practice-next,
.sfx-practice-retry,
.sfx-practice-finish {
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
.sfx-practice-finish {
  margin-left: auto;
  background: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #a5d6a7;
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
.sfx-practice-verify {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sfx-practice-verify-title {
  margin: 0 0 8px 0;
  font-size: 1rem;
  font-weight: 600;
}
.sfx-practice-verify-section {
  padding: 10px 12px;
  background: var(--surface-card, #fff);
  border-radius: 8px;
  border: 1px solid var(--border-default, #eee);
}
.sfx-practice-verify-subtitle {
  margin: 0 0 4px 0;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #333);
}
.sfx-practice-verify-text {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text-secondary, #555);
}
.sfx-practice-verify-text span + span::before {
  content: ' ';
}
.sfx-practice-verify-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.sfx-practice-verify-primary {
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  background: var(--accent-primary, #4f8cf7);
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer;
}
.sfx-practice-verify-secondary {
  padding: 8px 20px;
  border: 1px solid var(--border-default, #ddd);
  border-radius: 6px;
  background: none;
  color: var(--text-primary, #333);
  font-size: 0.9rem;
  cursor: pointer;
}
</style>
