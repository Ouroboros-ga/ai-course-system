<script setup>
import { FileCode2 } from 'lucide-vue-next'
import SfxCapabilityTag from './SfxCapabilityTag.vue'

/**
 * Planned 能力说明面板（API 契约 §1.1/§4）。
 *
 * planned = 冻结的未来契约，当前后端未实现。本组件展示契约内容与边界，
 * 绝不伪造数据或伪装成已完成能力（page-design §0.1/§22）。
 */
const props = defineProps({
  contractKey: { type: String, required: true },
  title: { type: String, default: '' },
  // 页面已经可用的真实能力说明（可选），避免用户误以为整页不可用
  availableNote: { type: String, default: '' },
})

</script>

<template>
  <div class="sfx-planned" role="status">
    <div class="sfx-planned-head">
      <span class="sfx-planned-icon" aria-hidden="true"><FileCode2 :size="20" :stroke-width="1.9" /></span>
      <div>
        <h3 class="sfx-t-title3">{{ title || '该功能暂不可用' }}</h3>
        <p class="sfx-t-ui sfx-t-secondary">此能力尚未完整接入；不会伪造数据或操作成功状态。</p>
      </div>
      <SfxCapabilityTag level="experimental" />
    </div>

    <p class="sfx-planned-summary sfx-t-ui">功能边界会在可用时由真实接口和页面状态说明。</p>

    <p v-if="availableNote" class="sfx-planned-available sfx-t-ui">
      <strong>当前可用：</strong>{{ availableNote }}
    </p>

    <div v-if="$slots.default" class="sfx-planned-extra">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.sfx-planned {
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface-cool);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-planned-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.sfx-planned-head > div { flex: 1; min-width: 0; }

.sfx-planned-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--ink-100);
  color: var(--ink-700);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sfx-planned-summary { color: var(--text-secondary); }

.sfx-planned-endpoints ul {
  margin: var(--space-1) 0 0;
  padding-left: var(--space-5, 20px);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  color: var(--text-secondary);
}

.sfx-planned-available {
  color: var(--green-700);
  background: var(--green-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}
</style>
