<script setup>
  import NavigationBar from "./components/NavigationBar.vue"
  import GradientBackground from "./components/GradientBackground.vue"
</script>

<template>
  <NavigationBar />
  <GradientBackground v-bind:animated="true" />
</template>

<style scoped></style>
