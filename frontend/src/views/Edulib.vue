<script setup>
import { ref, computed } from 'vue'
import {
  BookOpen, User, Presentation, Clock, FileText, Plus,
  Ruler, Code, GraduationCap, FolderOpen, Brain
} from 'lucide-vue-next'
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
          <BookOpen class="side-icon" :size="16" /> 全部课程
        </div>
        <div class="side-item" :class="{ active: activePage === 'myCourse' }" @click="switchPage('myCourse')">
          <User class="side-icon" :size="16" /> 我的选课
        </div>

        <div class="side-item" :class="{ active: activePage === 'tea1' }" @click="switchPage('tea1')" v-if="isStudent">
          <Presentation class="side-icon" :size="16" /> 高数课程
        </div>
        <div class="side-item" :class="{ active: activePage === 'tea2' }" @click="switchPage('tea2')" v-if="isStudent">
          <Presentation class="side-icon" :size="16" /> 计算机课程
        </div>
        <div class="side-item" :class="{ active: activePage === 'tea3' }" @click="switchPage('tea3')" v-if="isStudent">
          <Presentation class="side-icon" :size="16" /> 英语课程
        </div>

        <div class="side-item" :class="{ active: activePage === 'recent' }" @click="switchPage('recent')">
          <Clock class="side-icon" :size="16" /> 最近学习
        </div>

        <template v-if="isTeacher">
          <div class="side-item" :class="{ active: activePage === 'doc' }" @click="switchPage('doc')">
            <FileText class="side-icon" :size="16" /> 已解析文档
          </div>
          <button class="create-btn">
            <Plus class="btn-icon" :size="16" /> 新建课件
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
            <div class="role-tag" v-if="isTeacher"><Presentation :size="12" /> 教师</div>
            <div class="role-tag student" v-else><GraduationCap :size="12" /> 学生</div>
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
                  <BookOpen class="card-icon" :size="36" />
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
                  <div class="list-col"><BookOpen :size="16" /> 公共基础课 {{ i }}</div>
                  <div class="list-col">多位教师</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 我的选课 -->
            <div v-if="activePage === 'myCourse'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 3">
                  <BookOpen class="card-icon" :size="36" />
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
                  <div class="list-col"><BookOpen :size="16" /> 我已选课程 {{ i }}</div>
                  <div class="list-col">已选</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 张老师-高数 -->
            <div v-if="activePage === 'tea1'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 2">
                  <Ruler class="card-icon" :size="36" />
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
                  <div class="list-col"><Ruler :size="16" /> 高数课件 {{ i }}</div>
                  <div class="list-col">张建国</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 李老师-计算机 -->
            <div v-if="activePage === 'tea2'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 2">
                  <Code class="card-icon" :size="36" />
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
                  <div class="list-col"><Code :size="16" /> 编程课件 {{ i }}</div>
                  <div class="list-col">李美玲</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 王老师-英语 -->
            <div v-if="activePage === 'tea3'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 2">
                  <BookOpen class="card-icon" :size="36" />
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
                  <div class="list-col"><BookOpen :size="16" /> 英语课件 {{ i }}</div>
                  <div class="list-col">王浩</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <!-- 最近学习 -->
            <div v-if="activePage === 'recent'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 3">
                  <Clock class="card-icon" :size="36" />
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
                  <div class="list-col"><Clock :size="16" /> 最近学习课件 {{ i }}</div>
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
                  <FileText class="card-icon" :size="36" />
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
                  <div class="list-col"><FileText :size="16" /> 通用课件 {{ i }}</div>
                  <div class="list-col">AI生成课件</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <div v-if="activePage === 'myCourse'">
              <div v-if="viewMode === 'grid'" class="grid-view">
                <div class="grid-card" v-for="i in 4">
                  <BookOpen class="card-icon" :size="36" />
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
                  <div class="list-col"><BookOpen :size="16" /> 我的授课课件 {{ i }}</div>
                  <div class="list-col">主讲课程</div>
                  <div class="list-col">2026-04-0{{ i }}</div>
                </div>
              </div>
            </div>

            <div v-if="activePage === 'doc'">
              <div class="empty-box">
                <FolderOpen class="empty-icon" :size="40" />
                <div class="empty-text">暂无上传文档</div>
              </div>
            </div>
            <div v-if="activePage === 'kb'">
              <div class="empty-box">
                <Brain class="empty-icon" :size="40" />
                <div class="empty-text">知识库内容制作中</div>
              </div>
            </div>
            <div v-if="activePage === 'recent'">
              <div class="empty-box">
                <Clock class="empty-icon" :size="40" />
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
  background: var(--color-bg);
  padding: var(--space-5);
  box-sizing: border-box;
  overflow: hidden;
}
.fade-normal { animation: fadeNormal var(--duration-slow) var(--ease); }
@keyframes fadeNormal { from { opacity: 0.8; } to { opacity: 1; } }
.main-layout { display: flex; gap: var(--space-5); height: 100%; }
.left-sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-4);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.side-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: background var(--duration-normal) var(--ease);
}
.side-item:hover { background: var(--color-surface-2); }
.side-item.active { background: var(--color-primary-light); color: var(--color-primary); font-weight: var(--font-medium); }
.side-icon { flex-shrink: 0; }
.create-btn {
  margin-top: var(--space-3);
  background: var(--color-primary);
  color: var(--color-text-inverse);
  border: none;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  transition: background var(--duration-normal) var(--ease);
}
.create-btn:hover { background: var(--color-primary-hover); }
.right-content {
  flex: 1;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  box-shadow: var(--shadow-sm);
  overflow-y: auto;
  min-height: 0;
}
.tool-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-5);
  flex-wrap: wrap;
  gap: var(--space-3);
}
.breadcrumb { font-size: var(--text-sm); color: var(--color-text-secondary); }
.tools-right { display: flex; gap: var(--space-2); align-items: center; }

/* 身份标签 */
.role-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  background: var(--color-info-light);
  color: var(--color-info);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}
.role-tag.student {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.search {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  transition: border var(--duration-normal) var(--ease);
}
.search:focus { outline: none; border-color: var(--color-primary); }
.view-btn {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: pointer;
  transition: var(--transition-all);
}
.view-btn.active { background: var(--color-primary-light); border-color: var(--color-primary); color: var(--color-primary); }

/* 网格 */
.grid-view { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-4); }
.grid-card {
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-align: center;
  cursor: pointer;
  transition: var(--transition-all);
  background: var(--color-surface);
}
.grid-card:hover {
  border-color: var(--color-primary);
  background: var(--color-surface-2);
  transform: translateY(-2px);
}
.card-icon { margin-bottom: var(--space-2); color: var(--color-primary); }
.card-title { font-size: var(--text-sm); font-weight: var(--font-medium); color: var(--color-text); }
.card-tea { font-size: var(--text-xs); color: var(--color-text-secondary); margin-top: var(--space-1); }

/* 列表 */
.list-view {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.list-header,
.list-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  padding: var(--space-3) var(--space-5);
  font-size: var(--text-sm);
}
.list-header {
  background: var(--color-bg);
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}
.list-row {
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
}
.list-row:last-child { border-bottom: none; }
.list-row:hover {
  background: var(--color-surface-2);
}
.list-col {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* 空状态美化 */
.empty-box {
  text-align: center;
  padding: var(--space-8) 0;
  color: var(--color-text-secondary);
}
.empty-icon {
  margin-bottom: var(--space-3);
}
.empty-text {
  font-size: var(--text-sm);
}

@media (max-width: 768px) {
  .warehouse-page { padding: var(--space-3); }
  .main-layout { flex-direction: column; gap: var(--space-3); }
  .left-sidebar { width: 100%; flex-direction: row; overflow-x: auto; }
  .grid-view { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .grid-view { grid-template-columns: 1fr; }
}
</style>
