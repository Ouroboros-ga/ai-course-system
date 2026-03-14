<template>
  <div class="content">
    <h1>文档中心</h1>

    <section>
      <h2>核心功能</h2>
      <ul>
        <li>智能对话：上下文关联多轮问答</li>
        <li>数据解析：自动提取测试数据关键信息</li>
        <li>API 调用：RESTful 接口接入</li>
      </ul>
    </section>

    <section>
      <h2>快速开始</h2>
      <pre><code>npm install
npm run dev</code></pre>
    </section>

    <section>
      <h2>常见问题</h2>
      <p><strong>Q：如何切换模型？</strong></p>
      <p>A：在 config.json 中修改 model_name 字段。</p>
    </section>
  </div>
</template>

<style scoped>
.content {
  max-width: 800px;
  margin: 2rem auto;
  padding: 0 2rem;
  color: #333;
}
h1 {
  font-size: 2rem;
  margin-bottom: 1.5rem;
}
h2 {
  font-size: 1.5rem;
  margin: 1.2rem 0 0.8rem;
}
pre {
  background: #f5f5f5;
  padding: 1rem;
  border-radius: 4px;
  overflow-x: auto;
}
</style>
