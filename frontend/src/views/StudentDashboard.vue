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
  color: #374151;
}

.markdown-body h1, .markdown-body h2, .markdown-body h3,
.markdown-body h4 {
  margin-top: 1em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: #111827;
}

.markdown-body h2 {
  font-size: 1.4em;
  border-bottom: 2px solid #e5e7eb;
  padding-bottom: 0.3em;
}

.markdown-body p { margin: 0.8em 0; }

.markdown-body code:not(pre code) {
  background: #f1f5f9;
  color: #dc2626;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.markdown-body pre {
  background: #1e293b;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 1em 0;
}

.markdown-body pre code {
  background: transparent;
  color: #e2e8f0;
}

.markdown-body blockquote {
  border-left: 4px solid #6366f1;
  background: #f8fafc;
  padding: 8px 16px;
  margin: 1em 0;
  border-radius: 0 8px 8px 0;
  color: #4b5563;
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
  background: #f8fafc;
  border-radius: 8px;
  overflow-x: auto;
}
</style>

<style scoped>
.student-dashboard {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  background: #f5f7fa;
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
