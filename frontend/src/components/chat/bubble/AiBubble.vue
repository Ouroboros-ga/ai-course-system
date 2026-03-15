<script setup>
const props = defineProps({
  message: {
    type: String,
    required: true
  }
})
</script>

<template>
  <div class="ai-bubble">
    {{ props.message }}
  </div>
</template>

<style scoped>

</style>
