<script setup>
import { computed, inject } from 'vue'
import { UsersRound, UserRoundPlus } from 'lucide-vue-next'
import SfxLocalRail from '@/app/ui/SfxLocalRail.vue'

/**
 * 课程成员布局（page-design §17.1）。
 * 第一阶段只实现「成员列表」和「加入申请」，不放空壳菜单（§17.1）；
 * 课程分组与泛雅同步为 planned 契约，实现后加入 Rail。
 */
const courseContext = inject('courseContext')
const courseId = computed(() => courseContext.courseId.value)

const railItems = computed(() => {
  const base = `/app/course/${courseId.value}/members`
  return [
    { key: 'list', label: '成员列表', to: `${base}/list`, icon: UsersRound },
    { key: 'requests', label: '加入申请', to: `${base}/requests`, icon: UserRoundPlus },
  ]
})
</script>

<template>
  <div class="sfx-members-layout">
    <SfxLocalRail :items="railItems" aria-label="成员工作区" storage-key="members" />
    <div class="sfx-members-main">
      <router-view v-slot="{ Component, route }">
        <Transition name="sfx-page" mode="out-in">
          <component :is="Component" :key="route.path" />
        </Transition>
      </router-view>
    </div>
  </div>
</template>

<style scoped>
.sfx-members-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.sfx-members-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

/* 移动端（design.md §12.5）：rail 横向条置顶，内容区纵向滚动 */
@media (max-width: 760px) {
  .sfx-members-layout { flex-direction: column; }
  .sfx-members-main { min-height: 0; }
}
</style>
