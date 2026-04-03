<script setup>
import { ref } from 'vue'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})
const emit = defineEmits(['close', 'confirm'])

const config = ref({
  answerStyle: 'theory',
  knowledgeDepth: 'basic',
  chatTone: 'teacher',
  replyMode: 'direct',
  outputFormat: 'qa',
  interactionMode: 'passive'
})

const handleConfirm = () => {
  emit('confirm', config.value)
  emit('close')
}
const handleClose = () => {
  emit('close')
}
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click="handleClose">
    <div class="modal-content" @click.stop>
      <div class="modal-header">
        <h3>课件上传配置 🎯</h3>
        <span class="close-btn" @click="handleClose">✕</span>
      </div>

      <div class="modal-body">
        <!-- 1. AI回答风格 -->
        <div class="config-item">
          <label class="config-label">💬AI回答风格</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.answerStyle" value="theory" />
              <span>📚 理论优先</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.answerStyle" value="example" />
              <span>💡 举例优先</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.answerStyle" value="popular" />
              <span>🤣 唠嗑式讲解</span>
            </label>
          </div>
        </div>

        <!-- 2. 知识点深度 -->
        <div class="config-item">
          <label class="config-label">知识点深度</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.knowledgeDepth" value="basic" />
              <span>🎒 基础入门</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.knowledgeDepth" value="advanced" />
              <span>📝 考研拔高</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.knowledgeDepth" value="competition" />
              <span>🏆 竞赛拓展</span>
            </label>
          </div>
        </div>

        <!-- 精简规则 -->
        <div class="config-item">
          <label class="config-label">🚫 内容输出规则</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.replyMode" value="direct" />
              <span>⚡ 不废话直答</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.replyMode" value="idea" />
              <span>🧠 带解题思路</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.replyMode" value="warn" />
              <span>⚠️ 带易错提醒</span>
            </label>
          </div>
        </div>

        <!-- 互动模式 -->
        <div class="config-item">
          <label class="config-label">互动模式</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.interactionMode" value="passive" />
              <span>🤝 被动答疑</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.interactionMode" value="active" />
              <span>🚀 主动引导提问</span>
            </label>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="cancel-btn" @click="handleClose">取消</button>
        <button class="confirm-btn" @click="handleConfirm">确认并选择文件 ✅</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.modal-content {
  background: #fff;
  border-radius: 20px;
  width: 580px;
  max-width: 90vw;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
  overflow: hidden;
  animation: modalPop 0.3s cubic-bezier(0.24, 1, 0.32, 1) forwards;
}

@keyframes modalPop {
  from {opacity: 0;transform: scale(0.95) translateY(10px);}
  to {opacity: 1;transform: scale(1) translateY(0);}
}

.modal-header {
  display: flex;align-items: center;justify-content: space-between;
  padding: 20px 24px;border-bottom: 1px solid #f1f5f9;background: #f8fafc;
}
.modal-header h3 {margin:0;font-size:20px;color:#1e293b;font-weight:600;}
.close-btn {font-size:24px;color:#64748b;cursor:pointer;line-height:1;}
.close-btn:hover {color:#2563eb;}

.modal-body {
  padding:28px 24px;max-height:70vh;overflow-y:auto;
}
.config-item {margin-bottom:24px;}
.config-label {display:block;font-size:15px;font-weight:500;color:#334155;margin-bottom:10px;}
.option-group {display:flex;gap:12px;flex-wrap:wrap;}

.radio-option {
  display:flex;align-items:center;gap:6px;padding:10px 14px;
  border:1px solid #e2e8f0;border-radius:12px;cursor:pointer;
  font-size:14px;color:#475569;background:#fafafa;
}
.radio-option:has(input:checked) {
  border-color:#2563eb;background:#eff6ff;color:#2563eb;
  font-weight:500;transform:translateY(-1px);box-shadow:0 4px 12px rgba(37,99,235,0.1);
}
.radio-option input {margin:0;accent-color:#2563eb;transform:scale(1.1);}

.modal-footer {
  display:flex;justify-content:flex-end;gap:12px;padding:20px 24px;
  border-top:1px solid #f1f5f9;background:#f8fafc;
}
.cancel-btn {
  padding:10px 20px;border:1px solid #e2e8f0;background:#fff;
  border-radius:12px;cursor:pointer;font-size:14px;color:#64748b;font-weight:500;
}
.confirm-btn {
  padding:10px 24px;border:none;background:#2563eb;color:#fff;
  border-radius:12px;cursor:pointer;font-size:14px;font-weight:500;
}

/* 移动端强适配 */
@media (max-width:768px){
  .modal-content{width:95vw;border-radius:16px;}
  .option-group{gap:8px;}
  .radio-option{padding:8px 10px;font-size:12px;}
  .modal-body{padding:20px 16px;}
  .modal-header h3{font-size:17px;}
}
</style>
