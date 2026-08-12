<script setup>
import { computed, ref } from 'vue'
import { CheckCircle2, CircleDot, ListTodo, Plus, RotateCcw } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  todos: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['create', 'update'])

const title = ref('')
const priority = ref(2)
const orderedTodos = computed(() => [...props.todos].sort((left, right) => (
  right.priority - left.priority || left.position - right.position
)))

const statusLabel = {
  pending: '待开始',
  in_progress: '进行中',
  completed: '已完成',
  cancelled: '已取消',
}

function createTodo() {
  const normalized = title.value.trim()
  if (!normalized) return
  emit('create', { title: normalized, priority: Number(priority.value) })
  title.value = ''
}

function nextAction(todo) {
  if (todo.status === 'pending') return { status: 'in_progress', label: '开始', icon: CircleDot }
  if (todo.status === 'in_progress') return { status: 'completed', label: '完成', icon: CheckCircle2 }
  return { status: 'pending', label: '重新打开', icon: RotateCcw }
}

function badgeTone(status) {
  if (status === 'completed') return 'green'
  if (status === 'in_progress') return 'ink'
  if (status === 'cancelled') return 'red'
  return 'neutral'
}
</script>

<template>
  <section class="harness-panel" aria-labelledby="todo-title">
    <header class="panel-heading">
      <div>
        <p class="panel-kicker">HarnessEngineer · Todo</p>
        <h2 id="todo-title" class="sfx-t-title2">研究任务</h2>
      </div>
      <SfxBadge tone="ink">{{ todos.length }} 项</SfxBadge>
    </header>

    <form class="create-row" @submit.prevent="createTodo">
      <label class="field-grow">
        <span>新任务</span>
        <input v-model="title" maxlength="300" placeholder="例如：核验关键论文的实验数据集" />
      </label>
      <label class="priority-field">
        <span>优先级</span>
        <select v-model="priority">
          <option :value="3">高</option>
          <option :value="2">中</option>
          <option :value="1">低</option>
          <option :value="0">稍后</option>
        </select>
      </label>
      <SfxButton type="submit" variant="primary" :loading="loading" :disabled="disabled || !title.trim()">
        <template #icon><Plus :size="16" /></template>
        添加任务
      </SfxButton>
    </form>

    <div v-if="!orderedTodos.length" class="panel-empty">
      <ListTodo :size="30" />
      <strong>还没有研究任务</strong>
      <span>把检索、核验、复现与写作拆成可跟踪步骤。</span>
    </div>
    <ol v-else class="todo-list">
      <li v-for="todo in orderedTodos" :key="todo.todo_id" class="todo-row">
        <span class="priority-mark" :class="`is-p${todo.priority}`">P{{ todo.priority }}</span>
        <div class="todo-copy">
          <strong>{{ todo.title }}</strong>
          <span v-if="todo.description">{{ todo.description }}</span>
        </div>
        <SfxBadge :tone="badgeTone(todo.status)">{{ statusLabel[todo.status] || todo.status }}</SfxBadge>
        <SfxButton
          size="sm"
          variant="secondary"
          :loading="loading"
          :disabled="disabled || todo.status === 'cancelled'"
          @click="emit('update', { todo_id: todo.todo_id, status: nextAction(todo).status, expected_version: todo.version })"
        >
          <template #icon><component :is="nextAction(todo).icon" :size="15" /></template>
          {{ nextAction(todo).label }}
        </SfxButton>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.harness-panel { display: flex; flex-direction: column; gap: var(--space-5); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.panel-kicker { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--caption-size); margin-bottom: var(--space-1); }
.create-row { display: grid; grid-template-columns: minmax(0, 1fr) 112px auto; align-items: end; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); }
.field-grow, .priority-field { display: flex; flex-direction: column; gap: var(--space-2); color: var(--text-secondary); font-size: var(--ui-sm-size); }
input, select { height: var(--control-height); border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-page); color: var(--text-primary); padding: 0 var(--space-3); font: inherit; outline: 0; }
input:focus, select:focus { border-color: var(--ink-500); box-shadow: 0 0 0 2px var(--ink-100); }
.panel-empty { min-height: 260px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); color: var(--text-muted); text-align: center; }
.todo-list { display: flex; flex-direction: column; border-top: 1px solid var(--border-default); }
.todo-row { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto auto; align-items: center; gap: var(--space-3); padding: var(--space-4) var(--space-2); border-bottom: 1px solid var(--border-default); }
.priority-mark { font-family: var(--font-mono); font-size: var(--caption-size); color: var(--text-muted); }
.priority-mark.is-p3 { color: var(--red-700); }
.priority-mark.is-p2 { color: var(--amber-700); }
.todo-copy { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.todo-copy strong { color: var(--ink-900); font-size: var(--body-md-size); }
.todo-copy span { color: var(--text-muted); font-size: var(--caption-size); }
@media (max-width: 900px) { .create-row { grid-template-columns: 1fr; } .todo-row { grid-template-columns: 32px minmax(0, 1fr); } .todo-row :deep(.sfx-badge), .todo-row :deep(.sfx-btn) { grid-column: 2; justify-self: start; } }
</style>

