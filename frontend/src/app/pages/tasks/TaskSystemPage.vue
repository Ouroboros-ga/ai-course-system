<script setup>
import TaskListPage from './TaskListPage.vue'
</script>
<template>
  <!-- A course teacher must never need platform-admin permission just to see
       the parse/build work they initiated.  The protected `system` API view
       remains available to platform administration; this workspace tab is a
       teacher-safe projection of the current user's durable tasks. -->
  <TaskListPage view="created" title="课程建设任务" />
</template>
