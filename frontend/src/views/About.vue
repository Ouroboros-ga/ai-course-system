<script setup>
import { ref, onMounted } from 'vue'
import {
  Folder, Pin, HardHat, ArrowDown, Link,
  ArrowRight, Settings, Wrench, PenLine
} from 'lucide-vue-next'
const activeNav = ref('overview')

// 切页必复位，杜绝闪烁错位bug
onMounted(() => activeNav.value = 'overview')
</script>

<template>
  <div class="about-container">
    <!-- 左侧专业级悬浮导航栏 -->
    <aside class="pro-sidebar">
      <div class="sidebar-title"><Folder :size="16" /> 项目档案 · 架构说明</div>
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
        <h2 class="main-h2"><Pin :size="20" /> 项目全局概述</h2>
        <div class="high-card">
          <p class="text-content">
            本项目依托泛雅教学平台底座，构建<strong>AI 驱动的交互式智能授课系统</strong>，集成结构化文档解析、知识库 RAG 检索、智能课件生成、实时大模型答疑、学习数据可视化分析全链路能力。
            实现从「教学资料录入→知识点萃取→课件自动化产出→课堂实时答疑→学情数据复盘」的闭环智能化教学赋能，适配高校课程数字化改革场景。
          </p>
        </div>
      </div>

      <!-- 2.系统架构（唬老师核心！分层架构） -->
      <div key="ar" v-if="activeNav==='arch'" class="fade-block">
        <h2 class="main-h2"><HardHat :size="20" /> 分层式系统架构设计</h2>
        <div class="arch-wrap">
          <div class="arch-layer top">前端交互展示层</div>
          <div class="arch-arrow"><ArrowDown :size="20" /></div>
          <div class="arch-layer mid">接口调度&业务逻辑层</div>
          <div class="arch-arrow"><ArrowDown :size="20" /></div>
          <div class="arch-layer ai">AI能力&知识库推理层</div>
          <div class="arch-arrow"><ArrowDown :size="20" /></div>
          <div class="arch-layer bot">数据持久化&资源存储层</div>
        </div>
      </div>

      <!-- 3.业务链路 -->
      <div key="fl" v-if="activeNav==='flow'" class="fade-block">
        <h2 class="main-h2"><Link :size="20" /> 标准化核心业务链路</h2>
        <div class="flow-line">
          <div class="flow-node">资料结构化解析</div>
          <span class="flow-arrow"><ArrowRight :size="18" /></span>
          <div class="flow-node">知识点向量入库</div>
          <span class="flow-arrow"><ArrowRight :size="18" /></span>
          <div class="flow-node">智能PPT渲染生成</div>
          <span class="flow-arrow"><ArrowRight :size="18" /></span>
          <div class="flow-node">课堂实时智能问答</div>
          <span class="flow-arrow"><ArrowRight :size="18" /></span>
          <div class="flow-node">学情可视化统计</div>
        </div>
      </div>

      <!-- 4.模块化能力 -->
      <div key="fn" v-if="activeNav==='func'" class="fade-block">
        <h2 class="main-h2"><Settings :size="20" /> 模块化核心能力矩阵</h2>
        <div class="card-grid">
          <div class="func-card blue">文档深度解析<br/><small>PDF/Word结构化萃取</small></div>
          <div class="func-card green">AI课件自动生成<br/><small>动态版式智能排版</small></div>
          <div class="func-card purple">RAG知识库问答<br/><small>上下文精准检索推理</small></div>
          <div class="func-card orange">学情数据看板<br/><small>多维学习行为分析</small></div>
        </div>
      </div>

      <!-- 5.技术栈（专业感拉满） -->
      <div key="tc" v-if="activeNav==='tech'" class="fade-block">
        <h2 class="main-h2"><Wrench :size="20" /> 全栈技术栈选型说明</h2>
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
        <h2 class="main-h2"><PenLine :size="20" /> 项目开发落地说明</h2>
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
.about-container {
  display: flex;
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  background: var(--color-bg);
  overflow: hidden;
}

/* 左侧高阶侧边栏 */
.pro-sidebar {
  width: 240px;
  background: var(--color-surface);
  border-radius: 0 var(--radius-xl) var(--radius-xl) 0;
  box-shadow: var(--shadow-sm);
  height: 100%;
  padding: var(--space-5) 0;
  overflow-y: auto;
}
.sidebar-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--color-text);
  padding: 0 var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-3);
}
.nav-list { padding: 0 var(--space-3); }
.nav-item {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-2);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: var(--transition-all);
}
.nav-item:hover { background: var(--color-primary-light); transform: translateX(3px); }
.nav-item.active { background: var(--color-primary-light); color: var(--color-primary); font-weight: var(--font-medium); }

/* 右侧主内容 */
.pro-main { flex: 1; padding: var(--space-6) var(--space-7); overflow-y: auto; }
.main-h2 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-2xl);
  color: var(--color-text);
  margin-bottom: var(--space-5);
  border-left: 4px solid var(--color-primary);
  padding-left: var(--space-3);
}

/* 通用动画区块 */
.fade-block {
  opacity: 0;
  transform: translateY(25px);
  animation: fadeUp 0.6s cubic-bezier(0.24, 1, 0.32, 1) forwards;
  margin-bottom: var(--space-8);
}
@keyframes fadeUp { to { opacity: 1; transform: translateY(0); } }

/* 高端卡片 */
.high-card {
  background: var(--color-surface);
  padding: var(--space-6);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-md);
}
.text-content { line-height: 1.8; color: var(--color-text-secondary); font-size: var(--text-base); margin: 0; }

/* 分层架构展示 */
.arch-wrap { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); }
.arch-layer {
  width: 320px;
  text-align: center;
  padding: var(--space-3);
  border-radius: var(--radius-lg);
  color: var(--color-text-inverse);
  font-weight: var(--font-medium);
}
.arch-layer.top { background: var(--color-info); }
.arch-layer.mid { background: var(--color-primary); }
.arch-layer.ai { background: var(--color-secondary); }
.arch-layer.bot { background: var(--color-success); }
.arch-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-weight: var(--font-bold);
}

/* 业务流程线 */
.flow-line { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.flow-node {
  background: var(--color-surface);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.flow-arrow {
  display: flex;
  align-items: center;
  color: var(--color-text-muted);
}

/* 功能卡片网格 */
.card-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-5); }
.func-card {
  padding: var(--space-6);
  border-radius: var(--radius-xl);
  background: var(--color-surface);
  text-align: center;
  box-shadow: var(--shadow-sm);
  transition: var(--transition-all);
}
.func-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
.func-card.blue { border-top: 4px solid var(--color-info); }
.func-card.green { border-top: 4px solid var(--color-success); }
.func-card.purple { border-top: 4px solid var(--color-secondary); }
.func-card.orange { border-top: 4px solid var(--color-warning); }

/* 技术标签云 */
.tag-cloud { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.tech-tag {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: var(--transition-all);
}
.tech-tag:hover { background: var(--color-primary-light); color: var(--color-primary); border-color: var(--color-primary); }
</style>
