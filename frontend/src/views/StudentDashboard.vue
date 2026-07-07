<template>
  <div class="student-dashboard">
    <CourseSelection v-if="!selectedCourse" />
    <div v-else class="learning-interface">
      <CourseStructure />
      <ChatLearningArea />
    </div>
  </div>
</template>

<script setup>
import { provide } from 'vue'
import { useStudentLearning, STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'
import CourseSelection from '@/components/student/CourseSelection.vue'
import CourseStructure from '@/components/student/CourseStructure.vue'
import ChatLearningArea from '@/components/student/ChatLearningArea.vue'

import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.css'

const learning = useStudentLearning()
provide(STUDENT_LEARNING_KEY, learning)

const { selectedCourse } = learning
</script>

<style>
.markdown-body {
  font-size: 15px;
  line-height: 1.8;
  color: var(--color-text);
}

.markdown-body h1, .markdown-body h2, .markdown-body h3,
.markdown-body h4 {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: var(--color-text);
}

.markdown-body h2 {
  font-size: 1.4em;
  border-bottom: 2px solid var(--color-border);
  padding-bottom: 0.3em;
}

.markdown-body p { margin: 0.8em 0; }

.markdown-body code:not(pre code) {
  background: var(--color-surface-2);
  color: var(--color-danger);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.markdown-body pre {
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  overflow-x: auto;
  margin: 1em 0;
}

.markdown-body pre code {
  background: transparent;
  color: var(--color-border);
}

.markdown-body blockquote {
  border-left: 4px solid var(--color-primary);
  background: var(--color-bg);
  padding: var(--space-2) var(--space-4);
  margin: 1em 0;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  color: var(--color-text-secondary);
}

.markdown-body ul, .markdown-body ol {
  padding-left: 1.5em;
  margin: 0.5em 0;
}

.markdown-body li { margin: 0.3em 0; }

.katex-inline { display: inline; padding: 0 2px; }

.katex-block {
  display: block;
  text-align: center;
  margin: 1em 0;
  padding: 1em;
  background: var(--color-bg);
  border-radius: var(--radius-md);
  overflow-x: auto;
}
</style>

<style scoped>
.student-dashboard {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  background: var(--color-bg);
  overflow: hidden;
}

.learning-interface {
  display: flex;
  height: 100%;
  gap: 0;
}

@media (max-width: 1024px) {
  .learning-interface {
    flex-direction: column;
  }
}
</style>
