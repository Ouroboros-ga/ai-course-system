# NLP自然语言分析系统部署指南

## 📋 概述

本系统实现了基于大语言模型的自然语言分析功能，用于：
1. **理解度分析**：分析学生提问内容，判断对知识点的理解程度
2. **节点定位**：根据提问内容，定位最相关的学习节点
3. **节奏调节**：根据理解程度，动态调整讲授节奏
4. **进度可视化**：提供学习进度的可视化展示

## 🏗️ 系统架构

```
前端 (Vue 3)
    ↓
API接口层 (FastAPI)
    ↓
NLP分析服务 (progress_service.py)
    ↓
大模型API (豆包/通义千问/文心一言)
    ↓
数据库 (SQLite/MySQL)
```

## 📦 核心组件

### 后端组件

#### 1. 理解度分析器 ([UnderstandingAnalyzer](file:///c:/Users/wangz/PycharmProjects/ai-course-system/backend/app/services/progress_service.py#L24-L158))

**功能**：
- 分析学生提问内容
- 判断理解等级（excellent/high/medium/low）
- 提取已掌握和薄弱的关键词
- 生成学习建议

**核心方法**：
```python
async def analyze_question(
    question: str,           # 学生提问
    node_content: str,       # 当前节点内容
    node_title: str,         # 当前节点标题
    conversation_history: List[ChatMessage]  # 历史对话
) -> Dict
```

**返回结果**：
```json
{
    "understanding_level": "medium",
    "understanding_score": 0.65,
    "keywords_mastered": ["概念A", "概念B"],
    "keywords_weak": ["概念C"],
    "analysis_reason": "学生对核心概念有基本理解，但在应用层面存在困惑",
    "suggestions": "建议通过实例演示加深理解",
    "need_review": false
}
```

#### 2. 节点定位器 ([NodeLocator](file:///c:/Users/wangz/PycharmProjects/ai-course-system/backend/app/services/progress_service.py#L160-L248))

**功能**：
- 根据提问内容匹配相关节点
- 计算节点相关性分数
- 判断是否需要跳转

**核心方法**：
```python
async def locate_relevant_nodes(
    question: str,              # 学生提问
    script_nodes: List[ScriptNode],  # 所有节点
    current_node_id: int,       # 当前节点ID
    top_k: int = 3             # 返回前k个最相关节点
) -> List[Tuple[int, float, str]]
```

#### 3. 节奏调节器 ([PaceAdjuster](file:///c:/Users/wangz/PycharmProjects/ai-course-system/backend/app/services/progress_service.py#L251-L341))

**功能**：
- 根据理解程度计算讲授速度
- 生成教学策略建议
- 判断是否需要补充示例

**核心方法**：
```python
def calculate_pace_adjustment(
    understanding_level: UnderstandingLevel,
    understanding_score: float,
    question_count: int,
    time_spent: int
) -> Dict
```

**返回结果**：
```json
{
    "speed_factor": 0.85,
    "need_slow_down": true,
    "need_extra_examples": true,
    "next_node_strategy": "deepen",
    "recommended_actions": [
        "适当降低讲授速度至85%",
        "补充实例说明",
        "重点讲解薄弱环节"
    ]
}
```

### 前端组件

#### 进度仪表盘 ([ProgressDashboard.vue](file:///c:/Users/wangz/PycharmProjects/ai-course-system/frontend/src/components/chat/progress/ProgressDashboard.vue))

**功能**：
- 显示总体学习进度
- 展示各节点掌握情况
- 显示理解度分析结果
- 展示节奏调节建议

## 🚀 部署步骤

### 1. 后端部署

#### 1.1 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

#### 1.2 配置环境变量

创建 `.env` 文件：

```env
# 大模型配置（必填，至少配置一个）
DOUBAO_API_KEY=your_doubao_api_key
DOUBAO_ENDPOINT_ID=your_endpoint_id

# 或者使用其他大模型
QWEN_API_KEY=your_qwen_api_key
WENXIN_API_KEY=your_wenxin_api_key
WENXIN_SECRET_KEY=your_wenxin_secret_key

# 选择大模型提供商
LLM_PROVIDER=doubao  # 可选: doubao, qwen, wenxin, openai

# 数据库配置
DATABASE_URL=sqlite:///./ai_course.db  # 开发环境
# DATABASE_URL=mysql+pymysql://user:password@localhost/ai_course  # 生产环境
```

#### 1.3 初始化数据库

```bash
python -c "from app.models.database import create_tables; create_tables()"
```

#### 1.4 启动后端服务

```bash
python run.py
```

访问 `http://localhost:8000/docs` 查看API文档

### 2. 前端部署

#### 2.1 安装依赖

```bash
cd frontend
npm install
```

#### 2.2 配置环境变量

创建 `.env` 文件：

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

#### 2.3 启动开发服务器

```bash
npm run dev
```

访问 `http://localhost:5173` 使用系统

## 📡 API接口说明

### 1. 理解度分析接口

**接口**：`POST /api/v1/progress/analyze`

**请求参数**：
```json
{
    "courseId": 1,
    "nodeId": 1,
    "question": "这个概念我不太理解，能再解释一下吗？",
    "chatId": 123
}
```

**响应示例**：
```json
{
    "code": 200,
    "message": "理解度分析完成",
    "data": {
        "understanding": {
            "level": "medium",
            "score": 0.65,
            "keywords_mastered": ["基本概念"],
            "keywords_weak": ["应用场景"],
            "reason": "学生对基本概念有理解，但在应用层面存在困惑",
            "suggestions": "建议通过实例演示加深理解"
        },
        "pace_adjustment": {
            "speed_factor": 0.85,
            "need_slow_down": true,
            "next_node_strategy": "deepen",
            "recommended_actions": ["适当降低讲授速度", "补充实例说明"]
        },
        "node_recommendation": {
            "current_node": {"id": 1, "title": "基本概念"},
            "relevant_nodes": [
                {"node_id": 1, "relevance": 0.95, "reason": "直接相关", "need_jump": false}
            ]
        }
    }
}
```

### 2. 进度可视化接口

**接口**：`GET /api/v1/progress/visualization/{course_id}`

**响应示例**：
```json
{
    "code": 200,
    "message": "获取进度成功",
    "data": {
        "overall_progress": {
            "completion_rate": 0.45,
            "status": "in_progress",
            "total_learning_time": 3600,
            "session_count": 5
        },
        "nodes_progress": [
            {
                "id": 1,
                "index": 0,
                "title": "课程导入",
                "is_completed": true,
                "understanding_level": "high",
                "understanding_score": 0.85,
                "question_count": 2
            }
        ]
    }
}
```

### 3. 进度同步接口

**接口**：`POST /api/v1/progress/sync`

**请求参数**：
```json
{
    "courseId": 1,
    "nodeId": 1,
    "timestamp": 45.5,
    "isCompleted": false,
    "timeSpent": 30
}
```

### 4. 断点续接接口

**接口**：`GET /api/v1/progress/resume/{course_id}`

**响应示例**：
```json
{
    "code": 200,
    "message": "获取断点成功",
    "data": {
        "hasProgress": true,
        "resumeNode": {
            "nodeId": 3,
            "nodeIndex": 2,
            "nodeTitle": "核心概念讲解",
            "timestamp": 120.5
        },
        "progress": {
            "completion_rate": 0.35,
            "status": "in_progress",
            "total_learning_time": 1800
        }
    }
}
```

## 🔧 集成到现有系统

### 1. 在问答接口中启用理解度分析

修改前端 `ChatPanel.vue`：

```javascript
const handleSend = async (text) => {
  if (!text || !canChat.value) return;

  messageListRef.value?.addMessage({
    role: 'user',
    content: text
  });

  try {
    const res = await api.chat.askQuestion({
      question: text,
      chatId: currentChatId.value,
      courseId: props.currentData?.courseId,
      currentNodeId: props.currentData?.currentNodeId  // 添加当前节点ID
    });

    // 处理理解度分析结果
    if (res.understandingAnalysis) {
      const analysis = res.understandingAnalysis;
      console.log('理解度:', analysis.level, '分数:', analysis.score);
      
      // 显示学习建议
      if (analysis.suggestions) {
        showToast(analysis.suggestions, 'info');
      }
      
      // 更新进度仪表盘
      progressDashboardRef.value?.updatePaceAdjustment(analysis.paceAdjustment);
    }

    messageListRef.value?.addMessage({
      role: 'ai',
      content: res.answer,
      showResumeBtn: true
    });
  } catch (err) {
    console.error('问答失败', err);
  }
};
```

### 2. 在播放器中同步进度

修改 `PptPlayer.vue`：

```javascript
import api from '@/api/index.js'

// 定期同步进度（每30秒）
const syncProgress = async () => {
  if (!currentData.value?.courseId || !currentData.value?.currentNodeId) return;
  
  try {
    await api.progress.syncProgress({
      courseId: currentData.value.courseId,
      nodeId: currentData.value.currentNodeId,
      timestamp: currentTime.value,
      timeSpent: 30
    });
  } catch (err) {
    console.error('同步进度失败:', err);
  }
};

// 设置定时器
onMounted(() => {
  progressSyncTimer = setInterval(syncProgress, 30000);
});

onUnmounted(() => {
  if (progressSyncTimer) {
    clearInterval(progressSyncTimer);
  }
});
```

### 3. 实现断点续接

修改 `PptPlayer.vue`：

```javascript
const loadResumePoint = async () => {
  if (!currentData.value?.courseId) return;
  
  try {
    const res = await api.progress.getResumePoint(currentData.value.courseId);
    
    if (res.hasProgress && res.resumeNode) {
      // 显示续接提示
      showToast(`检测到上次学习进度：${res.resumeNode.nodeTitle}`, 'info');
      
      // 询问是否继续
      if (confirm('是否从上次位置继续学习？')) {
        // 跳转到对应节点和时间点
        jumpToNode(res.resumeNode.nodeId, res.resumeNode.timestamp);
      }
    }
  } catch (err) {
    console.error('加载断点失败:', err);
  }
};

onMounted(() => {
  loadResumePoint();
});
```

## 📊 性能优化建议

### 1. 缓存策略

```python
# 在 progress_service.py 中添加缓存
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_node_content(node_id: int) -> str:
    """缓存节点内容，减少数据库查询"""
    pass
```

### 2. 异步处理

```python
# 对于耗时的分析任务，使用后台任务
from fastapi import BackgroundTasks

@router.post("/analyze")
async def analyze_understanding(
    background_tasks: BackgroundTasks,
    ...
):
    # 将分析任务放入后台
    background_tasks.add_task(
        progress_service.handle_student_question,
        ...
    )
    return {"status": "analyzing"}
```

### 3. 批量处理

```python
# 批量更新进度，减少数据库写入
async def batch_sync_progress(progress_list: List[Dict]):
    """批量同步进度"""
    async with get_session() as session:
        for progress in progress_list:
            # 批量更新
            pass
        await session.commit()
```

## 🧪 测试

### 单元测试

```bash
cd backend
pytest tests/test_progress_service.py -v
```

### API测试

访问 `http://localhost:8000/docs`，使用Swagger UI测试接口

### 前端测试

```bash
cd frontend
npm run test
```

## 📝 注意事项

1. **大模型API配额**：确保大模型API有足够的调用配额
2. **数据库性能**：生产环境建议使用MySQL，并添加索引
3. **并发处理**：高并发场景建议使用Redis缓存
4. **错误处理**：所有API调用都应有try-catch包裹
5. **日志记录**：重要操作应记录日志，便于排查问题

## 🐛 常见问题

### Q1: 理解度分析返回默认值

**原因**：大模型API调用失败或返回格式不正确

**解决**：
1. 检查API Key是否正确
2. 检查网络连接
3. 查看后端日志，确认错误信息

### Q2: 进度不同步

**原因**：前端定时器未启动或网络请求失败

**解决**：
1. 检查组件是否正确挂载
2. 检查网络请求是否成功
3. 添加错误重试机制

### Q3: 节点定位不准确

**原因**：大模型对节点内容的理解不够准确

**解决**：
1. 优化节点内容的描述
2. 调整prompt，增加示例
3. 使用更强大的大模型

## 📚 扩展阅读

- [FastAPI官方文档](https://fastapi.tiangolo.com/)
- [Vue 3官方文档](https://vuejs.org/)
- [SQLModel官方文档](https://sqlmodel.tiangolo.com/)
- [豆包API文档](https://www.volcengine.com/docs/82379)

## 🎯 后续优化方向

1. **多模态分析**：支持语音、图像等多种输入的分析
2. **个性化推荐**：基于学习历史，推荐个性化学习路径
3. **知识图谱**：构建知识点关联图谱，提供更精准的节点定位
4. **实时反馈**：WebSocket实现实时进度同步和反馈
5. **学习报告**：生成详细的学习报告和分析图表
