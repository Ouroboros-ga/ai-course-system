<script setup>
import { computed } from 'vue'
import { CircleAlert, Lock, CloudOff } from 'lucide-vue-next'
import SfxButton from './SfxButton.vue'

/**
 * 错误状态（page-design §22.3）：发生了什么 / 影响什么 / 能做什么。
 * variant:
 *  - error       通用错误
 *  - unavailable 503：服务/能力未启用（如 teaching-agent 未注入、V2 影子未放量）
 *  - forbidden   403/401：权限不足（必须解释身份与所需权限，§22.5）
 */
const props = defineProps({
  variant: { type: String, default: 'error', validator: (v) => ['error', 'unavailable', 'forbidden'].includes(v) },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  retryable: { type: Boolean, default: true },
})

const emit = defineEmits(['retry'])

const presets = {
  error: {
    icon: CircleAlert,
    title: '加载失败',
    description: '数据暂时无法读取。已输入的内容不会丢失，请稍后重试。',
  },
  unavailable: {
    icon: CloudOff,
    title: '该能力暂未启用',
    description: '此能力依赖的后端服务当前未配置或未放量，系统没有返回可用数据。界面不会展示推测内容。',
  },
  forbidden: {
    icon: Lock,
    title: '当前账号暂无权限',
    description: '你当前的身份无法访问该数据。如需开通权限，请联系课程教师或平台管理员。',
  },
}

const iconComponent = computed(() => presets[props.variant].icon)
const finalTitle = computed(() => props.title || presets[props.variant].title)
const finalDescription = computed(() => props.description || presets[props.variant].description)
</script>

<template>
  <div class="sfx-error" :class="`is-${variant}`" role="alert">
    <div class="sfx-error-icon" aria-hidden="true">
      <component :is="iconComponent" :size="26" :stroke-width="1.9" />
    </div>
    <h3 class="sfx-error-title sfx-t-title3">{{ finalTitle }}</h3>
    <p class="sfx-error-desc sfx-t-ui sfx-t-secondary">{{ finalDescription }}</p>
    <div class="sfx-error-actions">
      <SfxButton v-if="retryable" variant="secondary" size="sm" @click="emit('retry')">重试</SfxButton>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.sfx-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--space-16) var(--space-6);
  gap: var(--space-3);
}

.sfx-error-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--red-100);
  color: var(--red-700);
}

.sfx-error.is-unavailable .sfx-error-icon { background: var(--amber-100); color: var(--amber-700); }
.sfx-error.is-forbidden .sfx-error-icon { background: var(--ink-100); color: var(--ink-700); }

.sfx-error-desc {
  max-width: 460px;
}

.sfx-error-actions {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-3);
}
</style>
