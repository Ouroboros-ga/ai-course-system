<template>
  <div class="scroll-arrow" @click="$emit('go-next')">
    <div class="mouse"><div class="wheel"></div></div>
  </div>
</template>
<style scoped>
.scroll-arrow { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); cursor: pointer; opacity: 0.6; }
.mouse { width: 24px; height: 38px; border: 2px solid #64748b; border-radius: 12px; display: flex; justify-content: center; padding-top: 6px; }
.wheel { width: 4px; height: 8px; background: #3b82f6; border-radius: 2px; animation: scroll-v 2s infinite; }
@keyframes scroll-v { 0% { opacity: 1; transform: translateY(0); } 100% { opacity: 0; transform: translateY(15px); } }
</style>
