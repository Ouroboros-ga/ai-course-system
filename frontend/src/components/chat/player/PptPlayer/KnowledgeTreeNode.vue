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
        {{ isExpanded ? '▼' : '▶' }}
      </span>
      <span v-else class="expand-placeholder"></span>
      
      <span class="node-icon">{{ getNodeIcon() }}</span>
      
      <span class="node-title" :title="nodeTitle">
        {{ nodeTitle }}
      </span>
      
      <span v-if="node.highlight" class="highlight-badge">⭐</span>
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
  if (isRoot.value) return '📚'
  if (hasChildren.value) return '📁'
  if (props.node.highlight) return '⭐'
  return '📄'
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
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  gap: 8px;
}

.node-header:hover {
  background: #f3f4f6;
}

.is-root > .node-header {
  font-weight: 600;
  color: #4f46e5;
  background: #f5f3ff;
}

.is-selected > .node-header {
  background: #e0e7ff;
  color: #4f46e5;
}

.expand-icon {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #9ca3af;
  cursor: pointer;
  transition: transform 0.2s ease;
}

.expand-icon:hover {
  color: #4f46e5;
}

.expand-placeholder {
  width: 16px;
  height: 16px;
}

.node-icon {
  font-size: 14px;
}

.node-title {
  flex: 1;
  font-size: 13px;
  color: #374151;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.is-selected .node-title {
  color: #4f46e5;
  font-weight: 500;
}

.highlight-badge {
  font-size: 12px;
}

.node-children {
  margin-left: 8px;
}
</style>
