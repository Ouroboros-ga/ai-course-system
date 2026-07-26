<script setup>
import { onMounted, ref } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { getSandboxHealth, getSandboxLanguages } from '@/api/sandbox.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 实验大厅（page-design §19.1）。
 * 第一阶段只展示真实实现的计算机能力分类（§19.1）；实验目录
 * GET /lab/catalog 为 planned 契约，不伪造实验卡。
 * 沙箱语言与可用性为真实探测（available）。
 */
const categories = ['算法理解', '代码诊断', '数据结构操作', '复杂度分析', '编程练习']

const sandbox = ref(null)
const languages = ref([])

onMounted(async () => {
  const [health, langs] = await Promise.all([
    getSandboxHealth().catch(() => null),
    getSandboxLanguages().catch(() => null),
  ])
  sandbox.value = health
  languages.value = Array.isArray(langs?.languages) ? langs.languages : []
})
</script>

<template>
  <div class="sfx-page">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">实验大厅</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">不依附课程任务的自主实验</p>
      </div>
    </header>

    <section class="sfx-panel">
      <div class="sfx-lab-sandbox-head">
        <h2 class="sfx-panel-title"><FlaskConical :size="17" /> 运行环境（真实探测）</h2>
        <SfxBadge v-if="sandbox?.available" tone="green">沙箱可用</SfxBadge>
        <SfxBadge v-else tone="amber">沙箱当前不可用</SfxBadge>
      </div>
      <dl class="sfx-desc">
        <dt>能力分类</dt>
        <dd>
          <span class="sfx-lab-chips">
            <SfxBadge v-for="cat in categories" :key="cat" tone="ink">{{ cat }}</SfxBadge>
          </span>
        </dd>
        <dt>支持语言</dt>
        <dd>
          <span v-if="languages.length" class="sfx-lab-chips">
            <SfxBadge v-for="lang in languages" :key="lang" tone="neutral">{{ lang }}</SfxBadge>
          </span>
          <span v-else>未获取到语言列表</span>
        </dd>
      </dl>
    </section>

    <SfxPlannedPanel
      contract-key="lab"
      title="自主实验目录 · 接口契约已冻结"
      available-note="沙箱运行环境已在上方真实展示；课程内实验可使用同一沙箱能力。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        实验卡将包含：名称、类型、难度、预计时间、支持语言、是否包含可视化、安全预设，
        主操作「开始实验」（§19.1）。点击卡片进入详情抽屉展示目标、先修知识与完成条件。
      </p>
    </SfxPlannedPanel>
  </div>
</template>

<style scoped>
.sfx-lab-sandbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.sfx-lab-sandbox-head .sfx-panel-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 0;
}

.sfx-lab-chips {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
</style>
