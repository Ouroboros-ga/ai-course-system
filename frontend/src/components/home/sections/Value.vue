<template>
  <section class="slide bg-white">
    <div class="container-narrow">
      <h2 class="section-title">赋能智慧教育・升级课堂体验</h2>
      <div class="value-grid">
        <div class="v-item"><span class="v-num">01</span><h4>高校教学</h4><p>定制化适配课程，辅助老师打造高水平课堂。</p></div>
        <div class="v-item"><span class="v-num">02</span><h4>线上学习</h4><p>打破时空限制，学生随时随地获得指导。</p></div>
        <div class="v-item"><span class="v-num">03</span><h4>教师备课</h4><p>解放生产力，让老师更聚焦于教学设计。</p></div>
        <div class="v-item"><span class="v-num">04</span><h4>效率提升</h4><p>无广告无水印，轻量化交互体验。</p></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.slide { width: 100%; height: 100vh; scroll-snap-align: start; display: flex; align-items: center; justify-content: center; padding: 0 10%; }
.bg-white { background: #fff; }
.container-narrow { max-width: 1000px; width: 100%; text-align: center; }
.section-title { font-size: 2.5rem; color: #0f172a; margin-bottom: 3rem; font-weight: 700; }
.value-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }
.v-item { display: flex; flex-direction: column; align-items: flex-start; text-align: left; padding: 2rem; border-bottom: 1px solid #e2e8f0; }
.v-num { font-size: 0.9rem; font-weight: 800; color: #3b82f6; margin-bottom: 0.5rem; }
</style>
