<script setup>
import { ref, computed } from 'vue'
const viewMode = ref('grid')
const userRole = ref('student')

const activePage = ref('all')
const isTeacher = computed(() => userRole.value === 'teacher')
const isStudent = computed(() => userRole.value === 'student')

const switchPage = (page) => {
  activePage.value = page
}
</script>

<template>
  <div class="warehouse-page">
    <div class="main-layout">
      <div class="left-sidebar">
        <div class="side-item" :class="{ active: activePage === 'all' }" @click="switchPage('all')">
          <span class="side-icon">📚</span> 全部课程
        </div>
        <div class="side-item" :class="{ active: activePage === 'myCourse' }" @click="switchPage('myCourse')">
          <span class="side-icon">👤</span> 我的选课
        </div>

        <div class="side-item" :class="{ active: activePage === 'tea1' }" @click="switchPage('tea1')" v-if="isStudent">
          <span class="side-icon">👨‍🏫</span> 高数课程
        </div>
        <div class="side-item" :class="{ active: activePage === 'tea2' }" @click="switchPage('tea2')" v-if="isStudent">
          <span class="side-icon">👩‍🏫</span> 计算机课程
        </div>
        <div class="side-item" :class="{ active: activePage === 'tea3' }" @click="switchPage('tea3')" v-if="isStudent">
          <span class="side-icon">👨‍🏫</span> 英语课程
        </div>

        <div class="side-item" :class="{ active: activePage === 'recent' }" @click="switchPage('recent')">
          <span class="side-icon">⏱️</span> 最近学习
        </div>

        <template v-if="isTeacher">
          <div class="side-item" :class="{ active: activePage === 'doc' }" @click="switchPage('doc')">
            <span class="side-icon">📄</span> 已解析文档
          </div>
          <button class="create-btn">
            <span class="btn-icon">➕</span> 新建课件
          </button>
        </template>
      </div>

      <div class="right-content">
        <div class="tool-bar">
          <div class="breadcrumb">
            Edulib /
            <span v-if="activePage==='all'">全部课程</span>
            <span v-if="activePage==='myCourse'">我的选课</span>
            <span v-if="activePage==='tea1'">高数课程</span>
            <span v-if="activePage==='tea2'">计算机课程</span>
            <span v-if="activePage==='tea3'">英语课程</span>
            <span v-if="activePage==='doc'">已解析文档</span>
            <span v-if="activePage==='recent'">最近学习</span>
          </div>
          <div class="tools-right">
            <div class="role-tag" v-if="isTeacher">👨‍🏫 教师</div>
            <div class="role-tag student" v-else>👨‍🎓 学生</div>
            <input type="text" placeholder="搜索课程/课件..." class="search" />
            <button @click="viewMode = 'grid'" class="view-btn" :class="{active: viewMode === 'grid'}">网格</button>
            <button @click="viewMode = 'list'" class="view-btn" :class="{active: viewMode === 'list'}">列表</button>
          </div>
        </div>

        <div class="file-list fade-normal">
          <div v-if="isStudent">
            <!-- 全部课程 -->
            <div v-if="activePage === 'all'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 4">
                  <div class="card-icon">📖</div>
                  <div class="card-title">公共基础课 {{ i }}</div>
                  <div class="card-tea">多位任课老师</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课程名称</div>
                  <div class="list-col">授课老师</div>
                  <div class="list-col">更新时间</div>
                </div>
                <div class="list-row" v-for="i in 4">
                  <div class="list-col">📖 公共基础课 {{ i }}</div>
                  <div class="list-col">多位教师</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 我的选课 -->
            <div v-if="activePage === 'myCourse'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 3">
                  <div class="card-icon">📗</div>
                  <div class="card-title">我已选课程 {{ i }}</div>
                  <div class="card-tea">个人专属选课</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课程名称</div>
                  <div class="list-col">选课状态</div>
                  <div class="list-col">更新时间</div>
                </div>
                <div class="list-row" v-for="i in 3">
                  <div class="list-col">📗 我已选课程 {{ i }}</div>
                  <div class="list-col">已选</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 张老师-高数 -->
            <div v-if="activePage === 'tea1'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 2">
                  <div class="card-icon">📐</div>
                  <div class="card-title">高数课件 {{ i }}</div>
                  <div class="card-tea">张建国 老师</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课件名称</div>
                  <div class="list-col">授课老师</div>
                  <div class="list-col">更新时间</div>
                </div>
                <div class="list-row" v-for="i in 2">
                  <div class="list-col">📐 高数课件 {{ i }}</div>
                  <div class="list-col">张建国</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 李老师-计算机 -->
            <div v-if="activePage === 'tea2'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 2">
                  <div class="card-icon">💻</div>
                  <div class="card-title">编程课件 {{ i }}</div>
                  <div class="card-tea">李美玲 老师</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课件名称</div>
                  <div class="list-col">授课老师</div>
                  <div class="list-col">更新时间</div>
                </div>
                <div class="list-row" v-for="i in 2">
                  <div class="list-col">💻 编程课件 {{ i }}</div>
                  <div class="list-col">李美玲</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 王老师-英语 -->
            <div v-if="activePage === 'tea3'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 2">
                  <div class="card-icon">📖</div>
                  <div class="card-title">英语课件 {{ i }}</div>
                  <div class="card-tea">王浩 老师</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课件名称</div>
                  <div class="list-col">授课老师</div>
                  <div class="list-col">更新时间</div>
                </div>
                <div class="list-row" v-for="i in 2">
                  <div class="list-col">📖 英语课件 {{ i }}</div>
                  <div class="list-col">王浩</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 最近学习 -->
            <div v-if="activePage === 'recent'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 3">
                  <div class="card-icon">⏰</div>
                  <div class="card-title">最近学习课件 {{ i }}</div>
                  <div class="card-tea">历史浏览记录</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课件名称</div>
                  <div class="list-col">学习状态</div>
                  <div class="list-col">最后学习</div>
                </div>
                <div class="list-row" v-for="i in 3">
                  <div class="list-col">⏰ 最近学习课件 {{ i }}</div>
                  <div class="list-col">学习中</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="isTeacher">
            <div v-if="activePage === 'all'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 8">
                  <div class="card-icon">📄</div>
                  <div class="card-title">通用课件 {{ i }}</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">名称</div>
                  <div class="list-col">类型</div>
                  <div class="list-col">修改时间</div>
                </div>
                <div class="list-row" v-for="i in 8">
                  <div class="list-col">📄 通用课件 {{ i }}</div>
                  <div class="list-col">AI生成课件</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <div v-if="activePage === 'myCourse'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 4">
                  <div class="card-icon">📚</div>
                  <div class="card-title">我的授课课件 {{ i }}</div>
                </div>
              </div>
              <div v-else class="list-view">
                <div class="list-header">
                  <div class="list-col">课件名称</div>
                  <div class="list-col">课程类型</div>
                  <div class="list-col">更新时间</div>
                </div>
                <div class="list-row" v-for="i in 4">
                  <div class="list-col">📚 我的授课课件 {{ i }}</div>
                  <div class="list-col">主讲课程</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <div v-if="activePage === 'doc'">
              <div class="empty-box">
                <div class="empty-icon">📂</div>
                <div class="empty-text">暂无上传文档</div>
              </div>
            </div>
            <div v-if="activePage === 'kb'">
              <div class="empty-box">
                <div class="empty-icon">🧠</div>
                <div class="empty-text">知识库内容制作中</div>
              </div>
            </div>
            <div v-if="activePage === 'recent'">
              <div class="empty-box">
                <div class="empty-icon">🕒</div>
                <div class="empty-text">暂无最近编辑记录</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.warehouse-page {
  width: 100%;
  height: calc(100vh - var(--navbar-height));
  background: #f8fafc;
  padding: 24px;
  box-sizing: border-box;
  overflow: hidden;
}
.fade-normal { animation: fadeNormal 0.3s ease; }
@keyframes fadeNormal { from { opacity: 0.8; } to { opacity: 1; } }
.main-layout { display: flex; gap: 20px; height: 100%; }
.left-sidebar {
  width: 200px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.side-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #475569;
  transition: background 0.2s ease;
}
.side-item:hover { background: #f1f5f9; }
.side-item.active { background: #eff6ff; color: #2563eb; font-weight: 500; }
.side-icon { font-size: 16px; }
.create-btn {
  margin-top: 12px;
  background: #2563eb;
  color: #fff;
  border: none;
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: background 0.2s ease;
}
.create-btn:hover { background: #1d4ed8; }
.right-content {
  flex: 1;
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  overflow-y: auto;
  min-height: 0;
}
.tool-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}
.breadcrumb { font-size: 14px; color: #64748b; }
.tools-right { display: flex; gap: 8px; align-items: center; }

/* 新加：身份标签 */
.role-tag {
  padding: 4px 10px;
  background: #e0f2fe;
  color: #0369a1;
  border-radius: 6px;
  font-size: 12px;
}
.role-tag.student {
  background: #f0f9ff;
  color: #2563eb;
}

.search {
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  transition: border 0.2s;
}
.search:focus { outline: none; border-color: #2563eb; }
.view-btn {
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;
}
.view-btn.active { background: #eff6ff; border-color: #2563eb; color: #2563eb; }

/* 网格 */
.grid-view { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.grid-card {
  padding: 20px;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  background: #fff;
}
.grid-card:hover {
  border-color: #2563eb;
  background: #f9fafb;
  transform: translateY(-2px);
}
.card-icon { font-size: 36px; margin-bottom: 8px; color: #2563eb; }
.card-title { font-size: 14px; font-weight: 500; color: #1e293b; }
.card-tea { font-size: 12px; color: #64748b; margin-top: 4px; }

/* 列表 */
.list-view {
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  overflow: hidden;
}
.list-header,
.list-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  padding: 14px 20px;
  font-size: 14px;
}
.list-header {
  background: #f8fafc;
  font-weight: 600;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
}
.list-row {
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
}
.list-row:hover {
  background: #f9fafb;
}
.list-col {
  display: flex;
  align-items: center;
}

/* 空状态美化 */
.empty-box {
  text-align: center;
  padding: 60px 0;
  color: #64748b;
}
.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}
.empty-text {
  font-size: 14px;
}

@media (max-width: 768px) {
  .warehouse-page { padding: 12px; }
  .main-layout { flex-direction: column; gap: 12px; }
  .left-sidebar { width: 100%; flex-direction: row; overflow-x: auto; }
  .grid-view { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 480px) {
  .grid-view { grid-template-columns: 1fr; }
}
</style>
