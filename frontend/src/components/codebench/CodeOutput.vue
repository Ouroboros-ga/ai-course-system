<script setup>
import { computed } from 'vue'
import { CheckCircle, XCircle, Clock, LoaderCircle, AlertTriangle, Terminal } from 'lucide-vue-next'

const props = defineProps({
  stdout: { type: String, default: '' },
  stderr: { type: String, default: '' },
  status: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'running', 'success', 'error', 'timeout', 'memory_limit', 'runtime_error', 'compile_error'].includes(v),
  },
  executionTime: { type: Number, default: 0 }, // ms
  memory: { type: Number, default: 0 }, // KB
  exitCode: { type: Number, default: null },
  title: { type: String, default: '输出结果' },
})

const statusConfig = computed(() => {
  const configs = {
    idle: {
      label: '等待运行',
      color: 'var(--code-muted)',
      bgColor: 'transparent',
      icon: Terminal,
    },
    running: {
      label: '运行中…',
      color: 'var(--ink-300)',
      bgColor: 'rgba(53, 92, 125, 0.15)',
      icon: LoaderCircle,
      spinning: true,
    },
    success: {
      label: '运行成功',
      color: 'var(--green-500)',
      bgColor: 'rgba(94, 140, 97, 0.15)',
      icon: CheckCircle,
    },
    error: {
      label: '运行错误',
      color: 'var(--red-500)',
      bgColor: 'rgba(184, 92, 92, 0.15)',
      icon: XCircle,
    },
    timeout: {
      label: '时间超限',
      color: 'var(--amber-500)',
      bgColor: 'rgba(198, 139, 44, 0.15)',
      icon: Clock,
    },
    memory_limit: {
      label: '内存超限',
      color: 'var(--amber-500)',
      bgColor: 'rgba(198, 139, 44, 0.15)',
      icon: AlertTriangle,
    },
    runtime_error: {
      label: '运行时错误',
      color: 'var(--red-500)',
      bgColor: 'rgba(184, 92, 92, 0.15)',
      icon: XCircle,
    },
    compile_error: {
      label: '编译错误',
      color: 'var(--red-500)',
      bgColor: 'rgba(184, 92, 92, 0.15)',
      icon: XCircle,
    },
  }
  return configs[props.status] || configs.idle
})

const formattedTime = computed(() => {
  if (!props.executionTime) return '—'
  if (props.executionTime < 1000) return `${props.executionTime} ms`
  return `${(props.executionTime / 1000).toFixed(2)} s`
})

const formattedMemory = computed(() => {
  if (!props.memory) return '—'
  if (props.memory < 1024) return `${props.memory} KB`
  return `${(props.memory / 1024).toFixed(2)} MB`
})

const hasOutput = computed(() => {
  return props.stdout?.trim() || props.stderr?.trim()
})
</script>

<template>
  <div class="code-output">
    <div class="output-header">
      <div class="output-title">
        <Terminal :size="16" :stroke-width="1.8" />
        <span>{{ title }}</span>
      </div>
      <div class="output-status" :style="{ color: statusConfig.color }">
        <component :is="statusConfig.icon" :size="14" :class="{ 'is-spinning': statusConfig.spinning }" />
        <span>{{ statusConfig.label }}</span>
      </div>
    </div>

    <div class="output-meta" v-if="status !== 'idle' && status !== 'running'">
      <div class="meta-item">
        <span class="meta-label">时间</span>
        <span class="meta-value">{{ formattedTime }}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">内存</span>
        <span class="meta-value">{{ formattedMemory }}</span>
      </div>
      <div class="meta-item" v-if="exitCode !== null">
        <span class="meta-label">退出码</span>
        <span class="meta-value">{{ exitCode }}</span>
      </div>
    </div>

    <div class="output-body">
      <!-- 空状态 -->
      <div v-if="status === 'idle' && !hasOutput" class="output-empty">
        <Terminal :size="32" :stroke-width="1.5" />
        <p>运行代码后，输出结果将显示在这里</p>
        <p class="empty-hint">使用 Ctrl+Enter 或 Cmd+Enter 快速运行</p>
      </div>

      <!-- 运行中状态 -->
      <div v-else-if="status === 'running'" class="output-running">
        <LoaderCircle :size="24" class="spinner" />
        <p>代码正在执行…</p>
      </div>

      <!-- 输出内容 -->
      <div v-else class="output-content">
        <!-- Stdout -->
        <div v-if="stdout?.trim()" class="output-section">
          <div class="section-label stdout-label">标准输出</div>
          <pre class="output-pre stdout">{{ stdout }}</pre>
        </div>

        <!-- Stderr -->
        <div v-if="stderr?.trim()" class="output-section">
          <div class="section-label stderr-label">错误输出</div>
          <pre class="output-pre stderr">{{ stderr }}</pre>
        </div>

        <!-- 无输出提示 -->
        <div v-if="!hasOutput && status === 'success'" class="output-no-content">
          <p>程序运行成功，但未产生任何输出</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.code-output {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--code-panel);
  color: var(--code-text);
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
}

.output-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--code-border);
  background: rgba(0, 0, 0, 0.15);
}

.output-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--code-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.output-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
}

.output-status .is-spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.output-meta {
  flex-shrink: 0;
  display: flex;
  gap: 24px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--code-border);
  font-size: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-label {
  color: var(--code-muted);
}

.meta-value {
  color: var(--code-text);
  font-weight: 500;
}

.output-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px;
}

.output-empty,
.output-running {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 120px;
  color: var(--code-muted);
  gap: 8px;
}

.output-empty p,
.output-running p {
  margin: 0;
  font-size: 13px;
}

.empty-hint {
  font-size: 11px !important;
  opacity: 0.7;
}

.spinner {
  animation: spin 0.9s linear infinite;
  color: var(--ink-400);
}

.output-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.output-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stdout-label {
  color: var(--green-500);
}

.stderr-label {
  color: var(--red-500);
}

.output-pre {
  margin: 0;
  padding: 10px 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  border: 1px solid var(--code-border);
}

.stdout {
  background: rgba(94, 140, 97, 0.08);
  color: var(--code-text);
}

.stderr {
  background: rgba(184, 92, 92, 0.08);
  color: #F08080;
}

.output-no-content {
  color: var(--code-muted);
  font-style: italic;
}

.output-no-content p {
  margin: 0;
}
</style>
