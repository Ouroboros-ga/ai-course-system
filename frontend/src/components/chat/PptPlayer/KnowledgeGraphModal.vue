<template>
  <div
    v-if="show"
    class="modal-overlay"
    @click.self="close"
  >
    <div class="modal-container">
      <div class="modal-header">
        <h3>🧠 知识图谱</h3>
        <button class="close-btn" @click="close">✕</button>
      </div>

      <div class="modal-body">
        <div class="tip" v-if="fileName">
          当前文件：{{ fileName }}
        </div>
        <div class="graph-box">
          <div class="empty-text">
            知识图谱已生成<br />
            <span>可在此处接入 ECharts 关系图谱可视化</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  show: Boolean,
  fileName: String
})

const emit = defineEmits(['update:show'])

const close = () => {
  emit('update:show', false)
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.modal-container {
  width: 90%;
  max-width: 700px;
  background: #fff;
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  color: #1f2937;
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #6b7280;
  cursor: pointer;
}

.modal-body {
  padding: 24px;
}

.tip {
  text-align: center;
  font-size: 13px;
  color: #4f46e5;
  margin-bottom: 16px;
}

.graph-box {
  height: 320px;
  background: #f8fafc;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-text {
  text-align: center;
  color: #6b7280;
  font-size: 14px;
  line-height: 1.6;
}
.empty-text span {
  font-size: 12px;
  color: #9ca3af;
}
</style>
