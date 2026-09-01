<script setup>
import { computed } from 'vue'
import { ArrowLeft, CheckCircle2, CircleAlert, Clock3, ShieldCheck } from 'lucide-vue-next'

import CodeEditor from '@/components/codebench/CodeEditor.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  offer: { type: Object, required: true },
  session: { type: Object, required: true },
  sourceCode: { type: String, default: '' },
  language: { type: String, default: 'python3' },
  runView: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  hintBusy: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['update:sourceCode', 'update:language', 'run', 'exit', 'reveal-hint'])

const outcomeLabels = {
  accepted: '全部测试通过',
  wrong_answer: '还有测试未通过',
  compilation_error: '编译未通过',
  runtime_error: '运行时错误',
  time_limit_exceeded: '运行超时',
  memory_limit_exceeded: '内存超限',
  sandbox_unavailable: '代码沙箱暂不可用',
  internal_error: '本次运行未完成',
  pending: '正在运行',
}

const terminalOutcomes = new Set(Object.keys(outcomeLabels).filter(item => item !== 'pending'))
const hasTerminalResult = computed(() => terminalOutcomes.has(props.runView?.result?.outcome))

function handleShortcut() {
  if (!props.busy && props.sourceCode.trim()) emit('run')
}

function handleHintToggle(event) {
  if (
    event.currentTarget.open
    && props.runView?.optional_hint_available
    && !props.runView?.teaching_feedback?.optional_hint
    && !props.hintBusy
  ) emit('reveal-hint')
}
</script>

<template>
  <section class="coding-stage" aria-label="代码挑战工作区">
    <header class="coding-stage-head">
      <div class="coding-stage-title">
        <SfxButton variant="tertiary" size="sm" :disabled="busy" @click="$emit('exit')">
          <template #icon><ArrowLeft :size="16" /></template>
          返回课程
        </SfxButton>
        <div>
          <p class="coding-stage-kicker">TeachingAgent · 代码挑战</p>
          <h2>{{ offer.title }}</h2>
          <p>{{ offer.why_now }}</p>
        </div>
      </div>
      <span class="coding-stage-safety"><ShieldCheck :size="15" /> 独立沙箱 · 隐藏测试受保护</span>
    </header>

    <div class="coding-stage-grid">
      <article class="coding-problem">
        <div class="coding-panel-head">
          <h3>题目</h3>
          <span>{{ offer.difficulty }} · 约 {{ offer.estimated_minutes }} 分钟</span>
        </div>
        <div class="coding-problem-body">
          <p>{{ session.problem?.description || '请根据题目要求补全代码，并通过公开与隐藏测试。' }}</p>
          <section v-if="session.problem?.public_examples?.length" class="coding-examples">
            <h4>公开样例</h4>
            <dl v-for="(item, index) in session.problem.public_examples" :key="index">
              <dt>输入</dt><dd><code>{{ item.stdin || '（无标准输入）' }}</code></dd>
              <dt>预期输出</dt><dd><code>{{ item.expected_stdout }}</code></dd>
            </dl>
          </section>
        </div>
      </article>

      <section class="coding-editor-panel" aria-label="代码编辑器">
        <div class="coding-panel-head is-dark">
          <h3>你的代码</h3>
          <label>
            <span class="sr-only">编程语言</span>
            <select :value="language" :disabled="busy" @change="$emit('update:language', $event.target.value)">
              <option v-for="item in session.languages" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
        </div>
        <div class="coding-editor-body">
          <CodeEditor
            :model-value="sourceCode"
            :language="language"
            :readonly="busy"
            @update:model-value="$emit('update:sourceCode', $event)"
            @run-shortcut="handleShortcut"
          />
        </div>
        <footer class="coding-runbar">
          <span>Ctrl / Cmd + Enter</span>
          <SfxButton variant="primary" :loading="busy" :disabled="!sourceCode.trim()" @click="$emit('run')">
            运行并获得反馈
          </SfxButton>
        </footer>
      </section>

      <aside class="coding-feedback" aria-label="运行结果与教学反馈">
        <div class="coding-panel-head"><h3>运行结果与反馈</h3></div>
        <div class="coding-feedback-body" aria-live="polite">
          <div v-if="busy && !hasTerminalResult" class="coding-empty"><Clock3 :size="24" /><p>Judge0 正在运行，反馈随后到达。</p></div>
          <div v-else-if="error && !hasTerminalResult" class="coding-result is-error" role="alert"><CircleAlert :size="18" /><p>{{ error }}</p></div>
          <div v-else-if="runView" class="coding-feedback-content">
            <section class="coding-result" :class="{ 'is-passed': runView.result?.outcome === 'accepted', 'is-error': runView.result?.outcome !== 'accepted' }">
              <CheckCircle2 v-if="runView.result?.outcome === 'accepted'" :size="18" />
              <CircleAlert v-else :size="18" />
              <div>
                <strong>{{ outcomeLabels[runView.result?.outcome] || runView.result?.outcome }}</strong>
                <p v-if="runView.result?.total_count">通过 {{ runView.result.passed_count }} / {{ runView.result.total_count }} 个测试</p>
              </div>
            </section>

            <template v-if="runView.teaching_feedback">
              <section v-for="item in [
                ['结果概览', 'result_overview'],
                ['已做对的部分', 'done_well'],
                ['当前问题', 'current_issue'],
                ['下一步建议', 'next_step'],
              ]" :key="item[1]" v-show="runView.teaching_feedback[item[1]]" class="coding-feedback-section">
                <h4>{{ item[0] }}</h4>
                <p>{{ runView.teaching_feedback[item[1]] }}</p>
              </section>
              <details
                v-if="runView.optional_hint_available"
                class="coding-hint-disclosure"
                @toggle="handleHintToggle"
              >
                <summary>查看可选提示</summary>
                <p v-if="runView.teaching_feedback.optional_hint">
                  {{ runView.teaching_feedback.optional_hint }}
                </p>
                <p v-else>{{ hintBusy ? '正在加载提示…' : '提示暂时不可用，请稍后再试。' }}</p>
              </details>
            </template>
            <div v-else-if="busy && hasTerminalResult" class="coding-feedback-waiting">
              Judge0 结果已返回，TeachingAgent 正在整理补充反馈…
            </div>
          </div>
          <div v-else class="coding-empty"><Clock3 :size="24" /><p>运行后，这里会先显示真实结果，再给出教学反馈。</p></div>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.coding-stage { flex: 1; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; background: var(--surface-page); }
.coding-stage-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-6); border-bottom: 1px solid var(--border-default); background: var(--surface-panel); }
.coding-stage-title { display: flex; align-items: flex-start; gap: var(--space-3); min-width: 0; }
.coding-stage-kicker { margin: 0 0 var(--space-1); color: var(--text-muted); font-size: var(--caption-size); font-weight: 600; }
.coding-stage h2 { margin: 0; color: var(--ink-900); font-size: var(--title-2-size); line-height: var(--title-2-line); }
.coding-stage-title p:last-child { margin: var(--space-1) 0 0; color: var(--text-secondary); font-size: var(--ui-sm-size); }
.coding-stage-safety { display: inline-flex; align-items: center; gap: var(--space-1); color: var(--green-700); font-size: var(--ui-sm-size); white-space: nowrap; }
.coding-stage-grid { min-height: 0; display: grid; grid-template-columns: minmax(220px, .72fr) minmax(380px, 1.35fr) minmax(280px, .85fr); grid-template-rows: minmax(0, 1fr); }
.coding-problem,
.coding-editor-panel,
.coding-feedback { min-height: 0; display: flex; flex-direction: column; overflow: hidden; border-right: 1px solid var(--border-default); background: var(--surface-panel); }
.coding-feedback { border-right: 0; }
.coding-panel-head { min-height: 48px; display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border-default); }
.coding-panel-head h3 { margin: 0; font-size: var(--ui-md-size); color: var(--text-primary); }
.coding-panel-head span { color: var(--text-muted); font-size: var(--caption-size); }
.coding-panel-head.is-dark { border-color: var(--code-border); background: var(--code-panel); }
.coding-panel-head.is-dark h3 { color: var(--code-text); }
.coding-panel-head select { min-height: 32px; border: 1px solid var(--code-border); border-radius: var(--radius-sm); background: var(--code-bg); color: var(--code-text); padding: 0 var(--space-2); }
.coding-problem-body,
.coding-feedback-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--space-5); }
.coding-problem-body > p { margin: 0; color: var(--text-primary); font-size: var(--body-md-size); line-height: var(--body-md-line); white-space: pre-wrap; }
.coding-examples { margin-top: var(--space-6); }
.coding-examples h4,
.coding-feedback-section h4 { margin: 0 0 var(--space-2); color: var(--ink-900); font-size: var(--ui-sm-size); }
.coding-examples dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--space-2); margin: var(--space-3) 0; }
.coding-examples dt { color: var(--text-muted); font-size: var(--caption-size); }
.coding-examples dd { margin: 0; min-width: 0; }
.coding-examples code { display: block; padding: var(--space-2); overflow-x: auto; border-radius: var(--radius-sm); background: var(--surface-cool); white-space: pre-wrap; }
.coding-editor-panel { background: var(--code-bg); border-color: var(--code-border); }
.coding-editor-body { flex: 1; min-height: 0; }
.coding-runbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-top: 1px solid var(--code-border); background: var(--code-panel); }
.coding-runbar > span { color: var(--code-muted); font-size: var(--caption-size); }
.coding-feedback-body { background: var(--surface-cool); }
.coding-feedback-content { display: flex; flex-direction: column; gap: var(--space-4); }
.coding-result { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--red-300); border-radius: var(--radius-md); background: var(--red-100); color: var(--red-700); }
.coding-result.is-passed { border-color: var(--green-300); background: var(--green-100); color: var(--green-700); }
.coding-result p { margin: var(--space-1) 0 0; font-size: var(--caption-size); }
.coding-feedback-section { padding-bottom: var(--space-4); border-bottom: 1px solid var(--border-subtle); }
.coding-feedback-section:last-child { border-bottom: 0; }
.coding-feedback-section p { margin: 0; color: var(--text-secondary); font-size: var(--ui-md-size); line-height: 1.7; }
.coding-hint-disclosure { padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); color: var(--text-secondary); }
.coding-hint-disclosure summary { cursor: pointer; color: var(--text-link); font-size: var(--ui-sm-size); font-weight: 600; }
.coding-hint-disclosure p { margin: var(--space-3) 0 0; font-size: var(--ui-md-size); line-height: 1.7; }
.coding-empty { min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-3); color: var(--text-muted); text-align: center; }
.coding-empty p { margin: 0; max-width: 260px; line-height: 1.7; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

@media (max-width: 1100px) {
  .coding-stage-grid { grid-template-columns: minmax(220px, .7fr) minmax(360px, 1.3fr); }
  .coding-feedback { position: absolute; right: 0; top: 0; bottom: 0; width: min(380px, 42%); border-left: 1px solid var(--border-default); box-shadow: var(--shadow-sm); }
  .coding-stage-grid { position: relative; padding-right: min(380px, 42%); }
}

@media (max-width: 760px) {
  .coding-stage { overflow-y: auto; grid-template-rows: auto auto; }
  .coding-stage-head { flex-direction: column; padding: var(--space-3); }
  .coding-stage-title { flex-direction: column; }
  .coding-stage-grid { display: flex; flex-direction: column; padding-right: 0; overflow: visible; }
  .coding-problem,
  .coding-editor-panel,
  .coding-feedback { flex: 0 0 auto; }
  .coding-problem { max-height: none; overflow: visible; }
  .coding-editor-panel { min-height: 58vh; }
  .coding-feedback { position: static; width: auto; min-height: 0; overflow: visible; border-left: 0; }
  .coding-problem-body,
  .coding-feedback-body { flex: 0 0 auto; overflow: visible; }
  .coding-runbar { position: sticky; bottom: 0; }
}
</style>
