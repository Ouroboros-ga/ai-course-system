<script setup>
import {ref} from "vue";

const props = defineProps({
  message: {
    type: String,
    required: true
  }
})

let nowTime = ref(
  new Date().toLocaleTimeString(
    'zh-CN',
    { hour: '2-digit', minute: '2-digit' }
  )
)

</script>

<template>
  <!-- 加一个背景容器，用于演示毛玻璃效果，实际使用时可以去掉 -->
  <div class="line">
    <div class="user-bubble">
      {{ props.message }}
    </div>
    <div class="now-time">
      {{ nowTime }}
    </div>
  </div>
</template>

<style scoped>
.line {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: flex-end;
  padding: 0 16px;
  margin-bottom: 12px;
}

.now-time {
  color: #1c1c1e;
  font-size: 12px;
  transform: translateX(12px);
}

.user-bubble {
  /* 1. 核心毛玻璃属性：背景半透明 */
  background: rgba(138, 203, 255, 0.25); /* 白色底，25%不透明度 */

  /* 3. 配色与文字 */
  color: #1c1c1e; /* 深色文字，保证在浅色玻璃上可读 */
  text-shadow: 0 1px 2px rgba(255, 255, 255, 0.4); /* 微弱的文字阴影增加清晰度 */
  font-size: 15px;
  line-height: 1.5;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;

  /* 4. 形状优化 */
  border-radius: 18px 18px 4px 18px; /* 右下角小圆角，模拟气泡尾巴 */

  /* 5. 边框：模拟玻璃边缘的高光，非常重要！ */
  border: 1px solid rgba(255, 255, 255, 0.4);

  /* 6. 布局 */
  padding: 12px 16px;
  max-width: 70%;
  width: fit-content;
  word-wrap: break-word;
  white-space: pre-wrap;
  word-break: break-word;

  /* 7. 阴影：增加悬浮感 */
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08), inset 0 1px 1px rgba(255, 255, 255, 0.4); /* 内阴影增加顶部高光 */

  /* 8. 交互 */
  transition: all 0.2s ease;
}

/* 悬停时加深一点背景，提升交互感 */
.user-bubble:hover {
  background: rgba(255, 255, 255, 0.35);
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
}

.user-bubble p {
  margin: 0;
}

.user-bubble p + p {
  margin-top: 6px;
}
</style>
