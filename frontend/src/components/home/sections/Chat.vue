<template>
  <section class="slide qna-page bg-gray">
    <div class="split-content flex-reverse">
      <div class="text-side">
        <h2 class="section-title text-left">7×24 小时<br />AI 实时答疑</h2>
        <p class="description">基于 RAG 精准检索泛雅平台知识库，回答可靠无幻觉。支持知识点讲解、作业辅导、课堂即时答疑。</p>
      </div>
      <div class="visual-side">
        <div class="mock-chat-window">
          <div class="chat-header">泛雅 AI 助手</div>
          <div class="chat-body">
            <div class="msg user">如何理解这个物理概念？</div>
            <div class="msg ai">根据课件第三章，核心要点在于...</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.slide { width: 100%; height: 100vh; scroll-snap-align: start; display: flex; align-items: center; justify-content: center; padding: 0 10%; }
.bg-gray { background: #f8fafc; }
.split-content { display: flex; align-items: center; gap: 4rem; width: 100%; max-width: 1200px; }
.flex-reverse { flex-direction: row-reverse; }
.text-side { flex: 1; text-align: left; }
.visual-side { flex: 1; display: flex; justify-content: center; }
.section-title { font-size: 2.5rem; color: #0f172a; margin-bottom: 3rem; font-weight: 700; }
.text-left { text-align: left; }
.description { font-size: 1.2rem; color: #64748b; line-height: 1.6; margin-bottom: 2rem; }
.mock-chat-window { width: 340px; background: white; border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.08); border: 1px solid #e2e8f0; overflow: hidden; }
.chat-header { background: #3b82f6; color: white; padding: 14px; font-weight: 600; text-align: center; }
.chat-body { padding: 22px; display: flex; flex-direction: column; gap: 14px; }
.msg { padding: 11px 15px; border-radius: 14px; font-size: 0.95rem; max-width: 82%; }
.msg.user { background: #f1f5f9; align-self: flex-end; }
.msg.ai { background: #eff6ff; align-self: flex-start; color: #1e40af; }
</style>
