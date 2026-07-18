<template>
  <aside class="sl-outline" aria-label="课程目录">
    <header class="sl-panel-heading">
      <div>
        <span>课程目录</span>
        <small>{{ nodes.length }} 个知识点</small>
      </div>
      <button
        v-if="closable"
        type="button"
        class="sl-icon-button"
        aria-label="收起课程目录"
        @click="$emit('close')"
      >
        <PanelLeftClose :size="18" />
      </button>
    </header>

    <label class="sl-outline-search">
      <Search :size="16" />
      <span class="sl-visually-hidden">搜索知识点</span>
      <input v-model="query" type="search" placeholder="搜索知识点" />
    </label>

    <nav class="sl-outline__list" aria-label="知识点列表">
      <button
        v-for="node in filteredNodes"
        :key="node.id"
        type="button"
        class="sl-outline-item"
        :class="{
          active: node.index === currentNodeIndex,
          completed: completedNodes.includes(node.id),
        }"
        :aria-current="node.index === currentNodeIndex ? 'step' : undefined"
        @click="$emit('select', node.index)"
      >
        <span class="sl-outline-item__state" aria-hidden="true">
          <CircleCheck v-if="completedNodes.includes(node.id)" :size="16" />
          <CirclePlay v-else-if="node.index === currentNodeIndex" :size="16" />
          <span v-else>{{ node.index + 1 }}</span>
        </span>
        <span class="sl-outline-item__copy">
          <strong>{{ node.title }}</strong>
          <small>
            第 {{ node.pageStart }}<template v-if="node.pageEnd !== node.pageStart">–{{ node.pageEnd }}</template> 页
            · {{ formatDuration(node.duration) }}
          </small>
        </span>
        <KeyRound v-if="node.isKeyPoint" :size="14" aria-label="重点知识" />
      </button>

      <div v-if="filteredNodes.length === 0" class="sl-panel-empty">
        <SearchX :size="28" />
        <p>没有匹配的知识点</p>
        <button type="button" @click="query = ''">清除搜索</button>
      </div>
    </nav>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import {
  CircleCheck,
  CirclePlay,
  KeyRound,
  PanelLeftClose,
  Search,
  SearchX,
} from 'lucide-vue-next'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  currentNodeIndex: { type: Number, default: 0 },
  completedNodes: { type: Array, default: () => [] },
  closable: { type: Boolean, default: true },
})

defineEmits(['select', 'close'])

const query = ref('')
const filteredNodes = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return props.nodes
  return props.nodes.filter(node => node.title.toLowerCase().includes(keyword))
})

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0)
  const minutes = Math.floor(value / 60)
  const remain = Math.floor(value % 60)
  return minutes + ':' + String(remain).padStart(2, '0')
}
</script>