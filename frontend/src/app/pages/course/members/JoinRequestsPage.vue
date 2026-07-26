<script setup>
import SfxPlannedPanel from '@/app/ui/SfxPlannedPanel.vue'

/**
 * 加入申请（page-design §17.3）。
 * 申请审核状态机为 planned 契约（§3.2）：当前真实加入路径是邀请码
 * （available），本页如实说明，不伪造申请列表。
 */
</script>

<template>
  <div class="sfx-joinrequests">
    <header class="sfx-joinrequests-head">
      <div>
        <h1 class="sfx-t-title2">加入申请</h1>
        <p class="sfx-t-ui sfx-t-secondary">无邀请码时的加入申请与审核</p>
      </div>
    </header>

    <SfxPlannedPanel
      contract-key="join-requests"
      title="加入申请审核 · 接口契约已冻结"
      available-note="邀请码加入已是正式能力：学生可在「我的课程 → 加入课程」输入邀请码直接加入，教师可在「设置 → 加入与发布」管理邀请码。"
    >
      <p class="sfx-t-ui sfx-t-secondary">
        契约实现后，这里会显示申请人、申请时间、申请说明、来源与当前状态；
        审核动作（通过 / 拒绝 / 请求补充信息）会记录审核者与时间（§17.3）。
      </p>
    </SfxPlannedPanel>
  </div>
</template>

<style scoped>
.sfx-joinrequests {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
  max-width: 960px;
}

.sfx-joinrequests-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}
</style>
