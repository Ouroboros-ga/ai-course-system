<template>
  <div class="analyzing-container">
    <div class="loader"></div>
    <h3>AI 正在研读课件...</h3>
    <p>正在提取知识点 & 生成讲解脚本</p>
    <div class="progress-bar"><div class="progress-fill"></div></div>
  </div>
</template>
<style scoped>
.analyzing-container { text-align: center; padding-top: 100px; }
.loader { width: 40px; height: 40px; border: 4px solid #e2e8f0; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
@keyframes spin { to { transform: rotate(360deg); } }
.progress-bar { width: 200px; height: 6px; background: #e2e8f0; border-radius: 99px; margin: 20px auto 0; overflow: hidden; }
.progress-fill { height: 100%; background: #3b82f6; animation: loading 2s infinite ease-in-out; }
@keyframes loading { 0% { width: 10%; } 50% { width: 80%; } 100% { width: 10%; } }
</style>
