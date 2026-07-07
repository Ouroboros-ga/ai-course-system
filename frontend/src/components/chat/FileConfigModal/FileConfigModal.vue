<script setup>
import { ref } from 'vue'
import { Target, X, MessageCircle, BookOpen, Lightbulb, Backpack, PenLine, Trophy, Ban, Zap, Brain, AlertTriangle, Handshake, Rocket, User, Presentation, CheckCircle, MessagesSquare, GraduationCap, Settings } from 'lucide-vue-next'

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
  interactionMode: 'passive',
  avatar: 'xiaoshuai', // 新增：默认小帅
  prompt: ''
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
        <h3>课件上传配置 <Target :size="20" /></h3>
        <span class="close-btn" @click="handleClose"><X :size="20" /></span>
      </div>

      <div class="modal-body">
        <!-- 1. AI回答风格 -->
        <div class="config-item">
          <label class="config-label"><MessageCircle :size="16" /> AI回答风格</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.answerStyle" value="theory" />
              <span><BookOpen :size="16" /> 理论优先</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.answerStyle" value="example" />
              <span><Lightbulb :size="16" /> 举例优先</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.answerStyle" value="popular" />
              <span><MessagesSquare :size="16" /> 唠嗑式讲解</span>
            </label>
          </div>
        </div>

        <!-- 2. 知识点深度 -->
        <div class="config-item">
          <label class="config-label">知识点深度</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.knowledgeDepth" value="basic" />
              <span><Backpack :size="16" /> 基础入门</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.knowledgeDepth" value="advanced" />
              <span><PenLine :size="16" /> 考研拔高</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.knowledgeDepth" value="competition" />
              <span><Trophy :size="16" /> 竞赛拓展</span>
            </label>
          </div>
        </div>

        <!-- 精简规则 -->
        <div class="config-item">
          <label class="config-label"><Ban :size="16" /> 内容输出规则</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.replyMode" value="direct" />
              <span><Zap :size="16" /> 不废话直答</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.replyMode" value="idea" />
              <span><Brain :size="16" /> 带解题思路</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.replyMode" value="warn" />
              <span><AlertTriangle :size="16" /> 带易错提醒</span>
            </label>
          </div>
        </div>

        <!-- 互动模式 -->
        <div class="config-item">
          <label class="config-label">互动模式</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.interactionMode" value="passive" />
              <span><Handshake :size="16" /> 被动答疑</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.interactionMode" value="active" />
              <span><Rocket :size="16" /> 主动引导提问</span>
            </label>
          </div>
        </div>

        <!-- 新增：数字人形象选择 -->
        <div class="config-item">
          <label class="config-label"><User :size="16" /> 数字人形象</label>
          <div class="option-group">
            <label class="radio-option">
              <input type="radio" v-model="config.avatar" value="xiaoshuai" />
              <span><User :size="16" /> 小帅</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.avatar" value="xiaomei" />
              <span><GraduationCap :size="16" /> 小美</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.avatar" value="laoshi" />
              <span><User :size="16" /> 小王</span>
            </label>
            <label class="radio-option">
              <input type="radio" v-model="config.avatar" value="xiaohong" />
              <span><Settings :size="16" /> 自定义</span>
            </label>
          </div>
        </div>

        <!-- 自定义提示词输入框 -->
        <div class="config-item">
          <label class="config-label"><PenLine :size="16" /> 自定义提示词</label>
          <textarea
            v-model="config.prompt"
            class="prompt-input"
            placeholder="请输入自定义提示词（例如：用小学生能听懂的话讲解，重点突出公式推导）"
            rows="3"
          ></textarea>
        </div>
      </div>

      <div class="modal-footer">
        <button class="cancel-btn" @click="handleClose">取消</button>
        <button class="confirm-btn" @click="handleConfirm"><CheckCircle :size="16" /> 确认并选择文件</button>
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
  z-index: var(--z-modal);
  backdrop-filter: blur(4px);
}

.modal-content {
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  width: 580px;
  max-width: 90vw;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  animation: modalPop 0.3s cubic-bezier(0.24, 1, 0.32, 1) forwards;
}

@keyframes modalPop {
  from {opacity: 0;transform: scale(0.95) translateY(10px);}
  to {opacity: 1;transform: scale(1) translateY(0);}
}

.modal-header {
  display: flex;align-items: center;justify-content: space-between;
  padding: var(--space-5) var(--space-6);border-bottom: 1px solid var(--color-surface-2);background: var(--color-bg);
}
.modal-header h3 {margin:0;font-size:var(--text-xl);color:var(--color-text);font-weight:600;}
.close-btn {font-size:var(--text-2xl);color:var(--color-text-secondary);cursor:pointer;line-height:1;display:flex;align-items:center;}
.close-btn:hover {color:var(--color-primary);}

.modal-body {
  padding:var(--space-7) var(--space-6);max-height:70vh;overflow-y:auto;
}
.config-item {margin-bottom:var(--space-6);}
.config-label {display:flex;align-items:center;gap:var(--space-1);font-size:var(--text-base);font-weight:500;color:var(--color-text);margin-bottom:var(--space-2);}
.option-group {display:flex;gap:var(--space-3);flex-wrap:wrap;}

.radio-option {
  display:flex;align-items:center;gap:var(--space-1);padding:var(--space-2) var(--space-3);
  border:1px solid var(--color-border);border-radius:var(--radius-lg);cursor:pointer;
  font-size:var(--text-sm);color:var(--color-text-secondary);background:var(--color-surface-2);
}
.radio-option:has(input:checked) {
  border-color:var(--color-primary);background:var(--color-primary-light);color:var(--color-primary);
  font-weight:500;box-shadow:var(--shadow-primary);
}
.radio-option input {margin:0;accent-color:var(--color-primary);transform:scale(1.1);}

.modal-footer {
  display:flex;justify-content:flex-end;gap:var(--space-3);padding:var(--space-5) var(--space-6);
  border-top:1px solid var(--color-surface-2);background:var(--color-bg);
}
.cancel-btn {
  padding:var(--space-2) var(--space-5);border:1px solid var(--color-border);background:var(--color-surface);
  border-radius:var(--radius-lg);cursor:pointer;font-size:var(--text-sm);color:var(--color-text-secondary);font-weight:500;
  transition: border-color var(--duration-normal) var(--ease), color var(--duration-normal) var(--ease);
}
.cancel-btn:hover {border-color:var(--color-border-hover);color:var(--color-text);}
.confirm-btn {
  display:flex;align-items:center;gap:var(--space-1);padding:var(--space-2) var(--space-6);border:none;background:var(--color-primary);color:var(--color-text-inverse);
  border-radius:var(--radius-lg);cursor:pointer;font-size:var(--text-sm);font-weight:500;
  transition: background var(--duration-normal) var(--ease);
}
.confirm-btn:hover {background:var(--color-primary-hover);}

.prompt-input {
  width: 100%;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  font-size: var(--text-sm);
  color: var(--color-text);
  background: var(--color-surface);
  resize: vertical;
  outline: none;
  transition: border-color var(--duration-normal) var(--ease), box-shadow var(--duration-normal) var(--ease);
  font-family: inherit;
  box-sizing: border-box;
}
.prompt-input:focus {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-primary);
}
.prompt-input::placeholder {
  color: var(--color-text-muted);
}

@media (max-width:768px){
  .modal-content{width:95vw;border-radius:var(--radius-xl);}
  .option-group{gap:var(--space-2);}
  .radio-option{padding:var(--space-2) var(--space-2);font-size:var(--text-xs);}
  .modal-body{padding:var(--space-5) var(--space-4);}
  .modal-header h3{font-size:var(--text-lg);}
  .prompt-input {
    font-size: var(--text-xs);
    padding: var(--space-2) var(--space-3);
  }
}
</style>
