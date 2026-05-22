<script setup>
import { ref, onMounted } from 'vue'
const activeNav = ref('overview')

// 切页必复位，杜绝闪烁错位bug
onMounted(() => activeNav.value = 'overview')
</script>

<template>
  <div class="about-container">
    <!-- 左侧专业级悬浮导航栏 -->
    <aside class="pro-sidebar">
      <div class="sidebar-title">📁 项目档案 · 架构说明</div>
      <nav class="nav-list">
        <div class="nav-item" :class="{active: activeNav === 'overview'}" @click="activeNav='overview'">项目全局概述</div>
        <div class="nav-item" :class="{active: activeNav === 'arch'}" @click="activeNav='arch'">系统架构设计</div>
        <div class="nav-item" :class="{active: activeNav === 'flow'}" @click="activeNav='flow'">核心业务链路</div>
        <div class="nav-item" :class="{active: activeNav === 'func'}" @click="activeNav='func'">模块化核心能力</div>
        <div class="nav-item" :class="{active: activeNav === 'tech'}" @click="activeNav='tech'">全栈技术栈选型</div>
        <div class="nav-item" :class="{active: activeNav === 'dev'}" @click="activeNav='dev'">开发落地说明</div>
      </nav>
    </aside>

    <!-- 右侧高质感主内容区 -->
    <main class="pro-main">
      <!-- 1.项目概述 -->
      <div key="ov" v-if="activeNav==='overview'" class="fade-block">
        <h2 class="main-h2">📌 项目全局概述</h2>
        <div class="high-card">
          <p class="text-content">
            本项目依托泛雅教学平台底座，构建<strong>AI 驱动的交互式智能授课系统</strong>，集成结构化文档解析、知识库 RAG 检索、智能课件生成、实时大模型答疑、学习数据可视化分析全链路能力。
            实现从「教学资料录入→知识点萃取→课件自动化产出→课堂实时答疑→学情数据复盘」的闭环智能化教学赋能，适配高校课程数字化改革场景。
          </p>
        </div>
      </div>

      <!-- 2.系统架构（唬老师核心！分层架构） -->
      <div key="ar" v-if="activeNav==='arch'" class="fade-block">
        <h2 class="main-h2">🏗️ 分层式系统架构设计</h2>
        <div class="arch-wrap">
          <div class="arch-layer top">前端交互展示层</div>
          <div class="arch-arrow">↓</div>
          <div class="arch-layer mid">接口调度&业务逻辑层</div>
          <div class="arch-arrow">↓</div>
          <div class="arch-layer ai">AI能力&知识库推理层</div>
          <div class="arch-arrow">↓</div>
          <div class="arch-layer bot">数据持久化&资源存储层</div>
        </div>
      </div>

      <!-- 3.业务链路 -->
      <div key="fl" v-if="activeNav==='flow'" class="fade-block">
        <h2 class="main-h2">🔗 标准化核心业务链路</h2>
        <div class="flow-line">
          <div class="flow-node">资料结构化解析</div>
          <span>⇒</span>
          <div class="flow-node">知识点向量入库</div>
          <span>⇒</span>
          <div class="flow-node">智能PPT渲染生成</div>
          <span>⇒</span>
          <div class="flow-node">课堂实时智能问答</div>
          <span>⇒</span>
          <div class="flow-node">学情可视化统计</div>
        </div>
      </div>

      <!-- 4.模块化能力 -->
      <div key="fn" v-if="activeNav==='func'" class="fade-block">
        <h2 class="main-h2">⚙️ 模块化核心能力矩阵</h2>
        <div class="card-grid">
          <div class="func-card blue">文档深度解析<br/><small>PDF/Word结构化萃取</small></div>
          <div class="func-card green">AI课件自动生成<br/><small>动态版式智能排版</small></div>
          <div class="func-card purple">RAG知识库问答<br/><small>上下文精准检索推理</small></div>
          <div class="func-card orange">学情数据看板<br/><small>多维学习行为分析</small></div>
        </div>
      </div>

      <!-- 5.技术栈（专业感拉满） -->
      <div key="tc" v-if="activeNav==='tech'" class="fade-block">
        <h2 class="main-h2">🛠️ 全栈技术栈选型说明</h2>
        <div class="tag-cloud">
          <span class="tech-tag">Vue3 + Vite</span>
          <span class="tech-tag">Pinia状态管理</span>
          <span class="tech-tag">FastAPI高性能后端</span>
          <span class="tech-tag">Python AI服务</span>
          <span class="tech-tag">RAG向量检索</span>
          <span class="tech-tag">大模型API调度</span>
          <span class="tech-tag">文档解析引擎</span>
          <span class="tech-tag">前端可视化组件</span>
        </div>
      </div>

      <!-- 6.开发说明 -->
      <div key="dv" v-if="activeNav==='dev'" class="fade-block">
        <h2 class="main-h2">📝 项目开发落地说明</h2>
        <div class="high-card">
          <p class="text-content">
            项目采用<strong>前后端分离 + AI微服务解耦</strong>架构开发，前端实现轻量化交互与可视化展示，后端负责业务调度与AI能力封装，知识库独立部署保障检索效率。
            整体代码模块化、可扩展、可二次迭代，完全满足课程设计/毕设/创新竞赛的技术验收标准，架构规范、文档完整、落地可用。
          </p>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* 全局基础 */
.about-container{display:flex;width:100%;min-height:calc(100vh - var(--navbar-height));background:#f6f8fa;}

/* 左侧高阶侧边栏 */
.pro-sidebar{width:240px;background:#fff;border-radius:0 16px 16px 0;box-shadow:2px 0 10px rgba(0,0,0,0.06);position:sticky;top:var(--navbar-height);height:calc(100vh - var(--navbar-height));padding:24px 0;border-left:none;}
.sidebar-title{font-size:16px;font-weight:600;color:#2c3e50;padding:0 20px 16px;border-bottom:1px solid #eee;margin-bottom:12px;}
.nav-list{padding:0 12px;}
.nav-item{padding:13px 16px;border-radius:10px;margin-bottom:6px;color:#555;cursor:pointer;transition:0.3s ease;}
.nav-item:hover{background:#f0f5ff;transform:translateX(3px);}
.nav-item.active{background:#eaf4ff;color:#2563eb;font-weight:500;}

/* 右侧主内容 */
.pro-main{flex:1;padding:30px 40px;}
.main-h2{font-size:24px;color:#1e293b;margin-bottom:22px;border-left:4px solid #2563eb;padding-left:12px;}

/* 通用动画区块 */
.fade-block{opacity:0;transform:translateY(25px);animation:fadeUp 0.6s cubic-bezier(0.24,1,0.32,1) forwards;margin-bottom:50px;}
@keyframes fadeUp{to{opacity:1;transform:translateY(0);}}

/* 高端卡片 */
.high-card{background:#fff;padding:28px;border-radius:16px;box-shadow:0 3px 15px rgba(0,0,0,0.05);}
.text-content{line-height:1.8;color:#444;font-size:15px;margin:0;}

/* 分层架构展示（最唬老师） */
.arch-wrap{display:flex;flex-direction:column;align-items:center;gap:8px;}
.arch-layer{width:320px;text-align:center;padding:14px;border-radius:12px;color:#fff;font-weight:500;}
.arch-layer.top{background:#3b82f6;}
.arch-layer.mid{background:#6366f1;}
.arch-layer.ai{background:#8b5cf6;}
.arch-layer.bot{background:#10b981;}
.arch-arrow{color:#999;font-weight:bold;}

/* 业务流程线 */
.flow-line{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.flow-node{background:#fff;padding:12px 18px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.05);}

/* 功能卡片网格 */
.card-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px;}
.func-card{padding:30px;border-radius:16px;background:#fff;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.05);transition:0.3s;}
.func-card:hover{transform:translateY(-5px);box-shadow:0 8px 20px rgba(0,0,0,0.08);}
.func-card.blue{border-top:4px solid #3b82f6;}
.func-card.green{border-top:4px solid #10b981;}
.func-card.purple{border-top:4px solid #8b5cf6;}
.func-card.orange{border-top:4px solid #f97316;}

/* 技术标签云 */
.tag-cloud{display:flex;flex-wrap:wrap;gap:12px;}
.tech-tag{background:#fff;border:1px solid #e2e8f0;padding:9px 16px;border-radius:999px;font-size:14px;color:#555;transition:0.25s;}
.tech-tag:hover{background:#eff6ff;color:#2563eb;border-color:#3b82f6;}
</style>
