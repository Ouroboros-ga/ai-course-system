<template>
  <div class="tree-node" :class="{ 'is-root': isRoot, 'is-selected': isSelected }">
    <div
      class="node-header"
      :style="{ paddingLeft: (level * 16) + 'px' }"
      @click="handleSelect"
    >
      <span
        v-if="hasChildren"
        class="expand-icon"
        @click.stop="handleToggle"
      >
        <ChevronDown v-if="isExpanded" :size="14" />
        <ChevronRight v-else :size="14" />
      </span>
      <span v-else class="expand-placeholder"></span>
      
      <span class="node-icon"><component :is="getNodeIcon()" :size="14" /></span>
      
      <span class="node-title" :title="nodeTitle">
        {{ nodeTitle }}
      </span>
      
      <span v-if="node.highlight" class="highlight-badge"><Star :size="12" /></span>
    </div>
    
    <div v-if="hasChildren && isExpanded" class="node-children">
      <KnowledgeTreeNode
        v-for="child in nodeChildren"
        :key="child.node_id || child.id || child.text"
        :node="child"
        :selected-id="selectedId"
        :expanded-ids="expandedIds"
        :level="level + 1"
        @select="$emit('select', $event)"
        @toggle="$emit('toggle', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { BookOpen, Folder, Star, FileText, ChevronDown, ChevronRight } from 'lucide-vue-next'

const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  selectedId: {
    type: String,
    default: null
  },
  expandedIds: {
    type: Set,
    default: () => new Set()
  },
  level: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['select', 'toggle'])

const isRoot = computed(() => props.level === 0)

const nodeTitle = computed(() => {
  return props.node.text || props.node.title || props.node.name || '未命名节点'
})

const nodeId = computed(() => {
  return props.node.node_id || props.node.id || `node_${nodeTitle.value}`
})

const nodeChildren = computed(() => {
  return props.node.children || []
})

const hasChildren = computed(() => {
  return nodeChildren.value && nodeChildren.value.length > 0
})

const isExpanded = computed(() => {
  return props.expandedIds.has(nodeId.value)
})

const isSelected = computed(() => {
  return props.selectedId === nodeId.value
})

const getNodeIcon = () => {
  if (isRoot.value) return BookOpen
  if (hasChildren.value) return Folder
  if (props.node.highlight) return Star
  return FileText
}

const handleSelect = () => {
  emit('select', nodeId.value)
}

const handleToggle = () => {
  emit('toggle', nodeId.value)
}
</script>

<style scoped>
.tree-node {
  user-select: none;
}

.node-header {
  display: flex;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--duration-normal) var(--ease);
  gap: var(--space-2);
}

.node-header:hover {
  background: var(--color-surface-2);
}

.is-root > .node-header {
  font-weight: 600;
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.is-selected > .node-header {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.expand-icon {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: color var(--duration-normal) var(--ease);
}

.expand-icon:hover {
  color: var(--color-primary);
}

.expand-placeholder {
  width: 16px;
  height: 16px;
}

.node-icon {
  display: flex;
  align-items: center;
  color: var(--color-text-secondary);
}

.is-root .node-icon,
.is-selected .node-icon {
  color: var(--color-primary);
}

.node-title {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.is-selected .node-title {
  color: var(--color-primary);
  font-weight: 500;
}

.is-root .node-title {
  color: var(--color-primary);
}

.highlight-badge {
  display: flex;
  align-items: center;
  color: var(--color-warning);
}

.node-children {
  margin-left: var(--space-2);
}
</style>
