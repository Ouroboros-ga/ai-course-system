<script setup>
  import navigationBar from "./components/navigationBar.vue"
  import gradientBackground from "./components/gradientBackground.vue"
</script>

<template>
  <navigationBar />
  <gradientBackground v-bind:animated="true" />
</template>

<style scoped></style>
