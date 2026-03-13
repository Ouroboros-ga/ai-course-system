<script setup>
import { ref, defineAsyncComponent } from 'vue'
// 假设你已经在别的地方引入了 store
import { useCounterStore } from '@/stores/counter'
const counter = useCounterStore()

// 1. 提前定义好异步组件（只定义一次，性能高）
const UserBubble = defineAsyncComponent(() => import('./bubble/UserBubble.vue'))
const AiBubble = defineAsyncComponent(() => import('./bubble/AiBubble.vue'))

// 2. 建立映射关系：key 是类型，value 是组件
const bubbleMap = {
  user: UserBubble,
  ai: AiBubble
}

// 3. 定义一个函数，根据类型返回对应的组件
// 这个函数会在模板里被调用，返回的是上面定义好的组件变量
const getComponent = (type) => {
  return bubbleMap[type] || null // 如果类型匹配不上，返回 null
}
</script>

<template>
  <div class="chat-box">
    <h1>测试数据</h1>
    <p>
      嘎脚噻😜哦达🥵牙八得🥸前期的火舞一
      定要打出气势🤫 姜子牙我抢线抢不过你😮‍💨 难道还打
      不过你吗 🙄（开始撤退）好吧确实打不过你 😨那么接下来我的目
      标就很明确了🥴 一定要针对一下这么姜子牙😤 算了也不是非要针
      对😝 既然姜子牙打不过🫢 残血的司空震可就逃不过我的手掌心了😏
      没有逃过他队友的手掌心🤗 火舞打安琪拉其实很好打😄 只需要躲过她的
      二技能就可以了😝 主播是反例🙁 很多粉丝宝宝好奇🧐 我是怎么躲过安琪
      拉的一闪😏 并且完成帅气反杀的😎 其实只要运气好就可以了🤣（You hav
      e slain an enemy）安琪拉蹲到了我的队友😤 却没想到我也
      在后面更没有想到还能带走一个火舞🤩 关注我教我玩火舞😏
    </p>
    <component
      v-for="item in counter.messages"
      :key="item.id"
      :is="getComponent(item.class)"
      :message="item.message"
    />
  </div>
</template>

<style scoped>
.chat-box {
  width: 100%;
  height: 100%;               /* 由父容器 flex 控制高度 */
  padding: 20px;
  overflow-y: auto;
  background: transparent;
  display: flex;
  flex-direction: column;
  gap: 16px;
  /* ✨ 添加上下边框 */
  border-top: 1px solid rgba(0, 0, 0, 0.2);
  border-bottom: 2px solid rgba(0, 0, 0, 0.1);

  /* 滚动条美化 */
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
}

/* Webkit 浏览器滚动条 */
.chat-box::-webkit-scrollbar {
  width: 6px;
}

.chat-box::-webkit-scrollbar-track {
  background: transparent;
}

.chat-box::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 3px;
}

.chat-box::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.3);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .chat-box {
    padding: 12px;
    gap: 12px;
  }
}
</style>
