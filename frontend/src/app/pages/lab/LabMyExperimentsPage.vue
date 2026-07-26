<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 我的实验（page-design §19.3）。
 * GET /lab/my-experiments 为 planned 契约：自主实验、课程任务副本、
 * 草稿代码、测试用例与提交版本。课程任务原件不可直接删除（§19.3）。
 */
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div>
        <h1 class="sfx-t-title1">我的实验</h1>
        <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">自主实验与课程任务副本</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="lab"
      title="我的实验 · 接口契约已冻结"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        契约实现后这里会保存：自主实验、课程任务副本、草稿代码、测试用例、最近运行、
        Agent 提示记录、可视化状态与提交版本（§19.3）。
        操作包含继续、创建副本、重命名、移动文件夹、关联课程与删除；
        课程任务原件不可直接删除，只能隐藏或创建副本。
      </p>
    </SfxPlannedPanel>
  </div>
</template>
