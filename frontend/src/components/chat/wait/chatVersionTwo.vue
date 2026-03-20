<template>
  <div class="chat-page-container">

    <!-- ================= 左侧：课件展示区 (动态内容) ================= -->
    <div class="ppt-section">
      <!-- 顶部信息 (始终显示) -->
      <div class="section-header">
        <div class="header-info">
          <h2 v-if="currentFile">{{ currentFile.name }}</h2>
          <h2 v-else>未选择课程文件</h2>
          <p v-if="currentFile">当前进度：12 / {{ totalPages }} 页</p>
          <p v-else>请上传 PPT 或 PDF 开始生成智课</p>
        </div>
        <button v-if="currentFile" class="btn-knowledge">
          <span>📄</span> 知识图谱
        </button>
      </div>

      <!-- 核心区域：根据状态显示不同内容 -->
      <div class="ppt-display-area">

        <!-- 状态 1: 未上传文件 (显示上传框) -->
        <div v-if="!currentFile" class="upload-container">
          <div class="upload-box" @dragover.prevent @drop="handleDrop">
            <div class="upload-icon">📁</div>
            <h3>点击或拖拽上传课件</h3>
            <p>支持 .ppt, .pptx, .pdf 格式</p>
            <button class="btn-upload-primary" @click="triggerUpload">选择文件</button>
            <input type="file" ref="fileInput" @change="handleFileChange" class="hidden-input" accept=".ppt,.pptx,.pdf">
          </div>
          <div class="features-hint">
            <span>✨ AI 自动解析知识点</span>
            <span>✨ 生成结构化讲义</span>
            <span>✨ 实时语音互动</span>
          </div>
        </div>

        <!-- 状态 2: 解析中 (显示 Loading) -->
        <div v-else-if="isAnalyzing" class="analyzing-container">
          <div class="loader"></div>
          <h3>AI 正在研读课件...</h3>
          <p>正在提取知识点 & 生成讲解脚本</p>
          <div class="progress-bar"><div class="progress-fill" style="width: 60%"></div></div>
        </div>

        <!-- 状态 3: 正常上课 (显示 PPT) -->
        <div v-else class="ppt-content-wrapper">
          <div class="ppt-placeholder">
            <div style="font-size: 48px; color: #fee2e2; margin-bottom: 16px;">📊</div>
            <p>PPT 第 12 页预览区域</p>
            <span style="font-size: 12px; color: #9ca3af;">(此处接入 PDF/PPT 渲染组件)</span>
          </div>

          <!-- 底部控制条 -->
          <div class="ai-control-bar">
            <div class="control-left">
              <button class="btn-play" @click="togglePlay">
                <span v-if="isPlaying">⏸</span>
                <span v-else>▶</span>
              </button>
              <div class="progress-info">
                <span class="status-text">{{ isPlaying ? 'AI 讲师正在讲解...' : '已暂停' }}</span>
                <div class="progress-track"><div class="progress-fill" style="width: 45%"></div></div>
              </div>
            </div>
            <div class="control-right">
              <button title="回退">↺</button>
              <span class="speed-tag">1.0x</span>
              <button title="音量">🔊</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ================= 右侧：聊天交互区 ================= -->
    <div class="chat-section">
      <!-- 聊天头部 -->
      <div class="chat-header">
        <div class="assistant-status">
          <div class="status-dot"></div>
          <span>AI 助教</span>
        </div>
        <button class="btn-more">⋮</button>
      </div>

      <!-- 消息列表 -->
      <div class="message-list">
        <!-- 如果没文件，显示欢迎语 -->
        <div v-if="!currentFile" class="welcome-message">
          <div class="avatar avatar-ai">AI</div>
          <div class="bubble-container">
            <div class="message-bubble bubble-ai">
              <p>👋 你好！我是你的 AI 助教。</p>
              <p>请在左侧上传课程 PPT 或 PDF，我将为你生成互动智课，并随时解答你的疑问。</p>
            </div>
          </div>
        </div>

        <!-- 如果有文件，显示正常对话 -->
        <template v-else>
          <div class="time-stamp">14:30</div>
          <div v-for="(msg, index) in messages" :key="index"
               :class="['message-row', msg.role === 'user' ? 'row-user' : '']">
            <!-- (保持原有的消息循环代码...) -->
            <div class="avatar" :class="msg.role === 'ai' ? 'avatar-ai' : 'avatar-user'">
              <img v-if="msg.role === 'user'" src="https://api.dicebear.com/7.x/avataaars/svg?seed=Felix" alt="User">
              <span v-else>AI</span>
            </div>
            <div class="bubble-container">
              <div class="message-bubble" :class="msg.role === 'user' ? 'bubble-user' : 'bubble-ai'">
                <div v-html="msg.content"></div>
                <div v-if="msg.showResumeBtn" class="resume-action">
                  <button class="btn-resume"> 回到刚才的讲解进度</button>
                </div>
              </div>
              <div v-if="msg.tags" class="tags-row">
                <span v-for="tag in msg.tags" :key="tag" class="tag-item">{{ tag }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 输入区 (没文件时禁用) -->
      <div class="input-area" :style="{ opacity: currentFile ? 1 : 0.5, pointerEvents: currentFile ? 'auto' : 'none' }">
        <div class="quick-tips">
          <button v-for="tip in quickTips" :key="tip" class="tip-chip">{{ tip }}</button>
        </div>
        <div class="input-box-wrapper">
          <input type="text" v-model="inputContent" @keyup.enter="sendMessage" placeholder="输入问题...">
          <button class="btn-mic">🎤</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue';

// 状态控制
const currentFile = ref(null);
const isAnalyzing = ref(false);
const isPlaying = ref(false);
const totalPages = ref(45);

// 模拟消息
const messages = reactive([
  { role: 'ai', content: '同学们好，我们现在讲到<strong>"Cache 映射方式”</strong>...', tags: ['知识点：直接映射'] },
  { role: 'user', content: '等一下，这里如果发生冲突了怎么办？' },
  { role: 'ai', content: '好问题！...', showResumeBtn: true }
]);

const inputContent = ref('');
const quickTips = ['没听懂，再讲一遍', '这页 PPT 重点是什么？', '快进 5 分钟'];
const fileInput = ref(null);

// 触发文件选择
const triggerUpload = () => fileInput.value.click();

// 处理文件变化
const handleFileChange = (event) => {
  const file = event.target.files[0];
  if (file) startAnalysis(file);
};

// 处理拖拽
const handleDrop = (event) => {
  const file = event.dataTransfer.files[0];
  if (file) startAnalysis(file);
};

// 模拟解析过程
const startAnalysis = (file) => {
  currentFile.value = file;
  isAnalyzing.value = true;

  // 模拟 3 秒后解析完成
  setTimeout(() => {
    isAnalyzing.value = false;
    isPlaying.value = true; // 解析完自动开始讲
  }, 3000);
};

const togglePlay = () => isPlaying.value = !isPlaying.value;
const sendMessage = () => { /* ... */ };
</script>

<style scoped>
/* ... (保留之前的 CSS，只增加下面这几个新样式) ... */

/* 上传区域样式 */
.upload-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 20px;
}

.upload-box {
  width: 80%;
  max-width: 500px;
  border: 2px dashed #cbd5e1;
  border-radius: 16px;
  padding: 40px;
  text-align: center;
  background: #f8fafc;
  transition: all 0.3s;
  cursor: pointer;
}

.upload-box:hover {
  border-color: #3b82f6;
  background: #eff6ff;
}

.upload-icon { font-size: 48px; margin-bottom: 16px; }
.upload-box h3 { margin: 0 0 8px 0; color: #334155; }
.upload-box p { margin: 0 0 24px 0; color: #64748b; font-size: 14px; }

.btn-upload-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
}

.features-hint {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #64748b;
}

/* 解析中样式 */
.analyzing-container {
  text-align: center;
  padding-top: 100px;
}
.loader {
  width: 40px; height: 40px;
  border: 4px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.progress-bar {
  width: 200px; height: 6px;
  background: #e2e8f0;
  border-radius: 99px;
  margin: 20px auto 0;
  overflow: hidden;
}
.progress-bar .progress-fill {
  height: 100%; background: #3b82f6;
  animation: loading 2s infinite ease-in-out;
}
@keyframes loading { 0% { width: 10%; } 50% { width: 80%; } 100% { width: 10%; } }

/* 欢迎消息样式 */
.welcome-message {
  display: flex;
  gap: 12px;
  padding: 20px;
  background: #f0f9ff;
  border-radius: 12px;
  margin-top: 20px;
}
.welcome-message .avatar { width: 40px; height: 40px; font-size: 16px; }
.welcome-message .message-bubble { background: white; border: none; box-shadow: none; padding: 0; }
.welcome-message p { margin: 0 0 8px 0; color: #334155; }

/* 隐藏 input */
.hidden-input { display: none; }

/* 保持之前的其他 CSS 不变... */
.chat-page-container { display: flex; gap: 16px; padding: 16px; height: 100%; width: 100%; box-sizing: border-box; font-family: sans-serif; }
.ppt-section { flex: 7; display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.section-header { display: flex; justify-content: space-between; align-items: center; padding: 0 4px; }
.section-header h2 { font-size: 18px; color: #1f2937; margin: 0 0 4px 0; }
.section-header p { font-size: 12px; color: #6b7280; margin: 0; }
.btn-knowledge { background: #eff6ff; color: #2563eb; border: none; padding: 6px 12px; border-radius: 99px; font-size: 13px; cursor: pointer; display: flex; align-items: center; gap: 6px; }
.ppt-display-area { flex: 1; background: white; border-radius: 16px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1); border: 1px solid #f3f4f6; position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; }
.ppt-content-wrapper { width: 100%; height: 100%; display: flex; flex-direction: column; }
.ppt-placeholder { flex: 1; display: flex; align-items: center; justify-content: center; text-align: center; color: #9ca3af; }
.ai-control-bar { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); width: 90%; background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(8px); border-radius: 16px; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.2); border: 1px solid rgba(255,255,255,0.5); }
.control-left { display: flex; align-items: center; gap: 16px; }
.btn-play { width: 40px; height: 40px; border-radius: 50%; background: #2563eb; color: white; border: none; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.progress-info { display: flex; flex-direction: column; gap: 4px; width: 128px; }
.status-text { font-size: 12px; color: #6b7280; font-weight: 500; }
.progress-track { height: 6px; background: #f3f4f6; border-radius: 99px; overflow: hidden; }
.progress-fill { width: 66%; height: 100%; background: #3b82f6; border-radius: 99px; }
.control-right { display: flex; gap: 16px; color: #6b7280; align-items: center; }
.control-right button { background: none; border: none; cursor: pointer; font-size: 16px; color: inherit; }
.speed-tag { font-size: 12px; font-family: monospace; background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }
.chat-section { flex: 3; background: white; border-radius: 16px; border: 1px solid #f3f4f6; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
.chat-header { padding: 16px; border-bottom: 1px solid #f9fafb; background: #f9fafb; display: flex; justify-content: space-between; align-items: center; }
.assistant-status { display: flex; align-items: center; gap: 8px; font-weight: 600; color: #374151; }
.status-dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; animation: pulse 2s infinite; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
.btn-more { background: none; border: none; font-size: 18px; color: #9ca3af; cursor: pointer; }
.message-list { flex: 1; overflow-y: auto; padding: 16px; background: #fafafa; display: flex; flex-direction: column; gap: 16px; }
.time-stamp { text-align: center; font-size: 12px; color: #9ca3af; margin: 4px 0; }
.message-row { display: flex; gap: 12px; }
.row-user { flex-direction: row-reverse; }
.avatar { width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0; overflow: hidden; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; }
.avatar-ai { background: #dbeafe; color: #2563eb; }
.avatar-user { background: #e5e7eb; }
.avatar-user img { width: 100%; height: 100%; }
.bubble-container { display: flex; flex-direction: column; gap: 4px; max-width: 85%; }
.row-user .bubble-container { align-items: flex-end; }
.message-bubble { padding: 12px; border-radius: 16px; font-size: 14px; line-height: 1.5; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05); border: 1px solid transparent; }
.bubble-ai { background: white; color: #374151; border-top-left-radius: 4px; border-color: #f3f4f6; }
.bubble-user { background: #2563eb; color: white; border-top-right-radius: 4px; }
.resume-action { margin-top: 12px; padding-top: 12px; border-top: 1px solid #eff6ff; }
.btn-resume { width: 100%; background: #eff6ff; color: #2563eb; border: none; padding: 8px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; }
.tags-row { display: flex; gap: 6px; }
.tag-item { font-size: 10px; background: #eff6ff; color: #2563eb; padding: 2px 6px; border-radius: 4px; border: 1px solid #dbeafe; }
.input-area { padding: 16px; background: white; border-top: 1px solid #f3f4f6; }
.quick-tips { display: flex; gap: 8px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px; }
.tip-chip { white-space: nowrap; background: #f9fafb; border: 1px solid #e5e7eb; padding: 6px 12px; border-radius: 99px; font-size: 12px; color: #4b5563; cursor: pointer; transition: all 0.2s; }
.tip-chip:hover { border-color: #93c5fd; color: #2563eb; background: #eff6ff; }
.input-box-wrapper { position: relative; }
.input-box-wrapper input { width: 100%; padding: 12px 48px 12px 16px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 12px; font-size: 14px; box-sizing: border-box; outline: none; }
.input-box-wrapper input:focus { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1); }
.btn-mic { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: none; border: none; font-size: 18px; color: #9ca3af; cursor: pointer; }
</style>
