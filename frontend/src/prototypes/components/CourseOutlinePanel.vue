<script setup>
import { computed } from 'vue'
import { ChevronDown, ChevronRight, CircleCheck, Circle, Clock3, Search, X } from 'lucide-vue-next'

const props = defineProps({
  chapters: { type: Array, required: true },
  activeId: { type: String, required: true },
  query: { type: String, default: '' },
  prerequisite: { type: Object, required: true },
  mobile: { type: Boolean, default: false }
})

const emit = defineEmits(['select', 'update:query', 'close', 'start-prerequisite', 'toggle-chapter'])

const filteredChapters = computed(() => {
  const q = props.query.trim().toLowerCase()
  if (!q) return props.chapters
  return props.chapters
    .map((chapter) => ({
      ...chapter,
      expanded: true,
      points: chapter.points.filter((point) => point.title.toLowerCase().includes(q))
    }))
    .filter((chapter) => chapter.title.toLowerCase().includes(q) || chapter.points.length)
})

const iconFor = (status) => {
  if (status === 'completed') return CircleCheck
  if (status === 'current') return Clock3
  return Circle
}
</script>

<template>
  <aside class="fd-rail fd-outline" aria-label="课程目录">
    <div class="fd-rail__header">
      <div>
        <p class="fd-eyebrow">课程导航</p>
        <h2>课程目录</h2>
      </div>
      <button v-if="mobile" class="fd-icon-button" type="button" aria-label="关闭课程目录" @click="emit('close')">
        <X :size="18" />
      </button>
    </div>

    <label class="fd-search">
      <Search :size="16" aria-hidden="true" />
      <span class="fd-sr-only">搜索章节或知识点</span>
      <input
        :value="query"
        type="search"
        placeholder="搜索章节或知识点"
        @input="emit('update:query', $event.target.value)"
      />
    </label>

    <nav class="fd-outline__tree" aria-label="章节与知识点">
      <section v-for="chapter in filteredChapters" :key="chapter.id" class="fd-chapter">
        <button
          class="fd-chapter__toggle"
          type="button"
          :aria-expanded="chapter.expanded"
          @click="emit('toggle-chapter', chapter.id)"
        >
          <component :is="chapter.expanded ? ChevronDown : ChevronRight" :size="16" />
          <span>{{ chapter.title }}</span>
          <small>{{ chapter.progress }}</small>
        </button>
        <ul v-if="chapter.expanded">
          <li v-for="point in chapter.points" :key="point.id">
            <button
              class="fd-point"
              :class="{ 'is-active': point.id === activeId }"
              type="button"
              :aria-current="point.id === activeId ? 'true' : undefined"
              @click="emit('select', point)"
            >
              <component :is="iconFor(point.status)" :size="15" aria-hidden="true" />
              <span>{{ point.title }}</span>
              <small>{{ point.duration }}</small>
            </button>
          </li>
        </ul>
      </section>
    </nav>

    <section class="fd-prerequisite">
      <div class="fd-prerequisite__heading">
        <div>
          <p class="fd-eyebrow">前置知识建议</p>
          <strong>{{ prerequisite.title }}</strong>
        </div>
        <span>{{ prerequisite.duration }}</span>
      </div>
      <p>{{ prerequisite.reason }}</p>
      <button class="fd-text-button" type="button" @click="emit('start-prerequisite')">进入补学</button>
    </section>
  </aside>
</template>
