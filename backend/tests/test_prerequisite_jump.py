"""
前置知识智能跳转功能 - 完整测试套件

覆盖范围：
1. 数据模型验证（LearningJumpHistory）
2. AI缺陷检测API（analyze-gap）
3. 跳转管理API（jump/return/jump-stack）
4. 学习路径可视化API（learning-path）
5. 多层嵌套跳转场景
6. 边界条件和异常处理
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def test_client():
    """创建测试客户端"""
    client = TestClient(app)
    yield client


@pytest.fixture(scope="module")
def db_session():
    """创建测试数据库会话"""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    engine.dispose()


class TestLearningJumpHistoryModel:
    """测试 LearningJumpHistory 数据模型"""
    
    def test_model_creation(self, db_session):
        """测试跳转记录的创建"""
        from app.models.progress_model import LearningJumpHistory
        
        jump = LearningJumpHistory(
            user_id=1,
            course_id=1,
            session_id="test-session-001",
            from_node_id=15,
            from_node_title="洛必达法则",
            from_node_index=14,
            to_node_id=5,
            to_node_title="函数极限",
            to_node_index=2,
            trigger_type="prerequisite_gap",
            trigger_question="这个公式怎么推导的？",
            prerequisite_ids="5",
            prerequisite_titles="函数极限",
            gap_description="需要掌握极限定义才能理解洛必达法则",
            confidence_score=0.9,
            urgency_level="high",
        )
        
        db_session.add(jump)
        db_session.commit()
        db_session.refresh(jump)
        
        assert jump.id is not None
        assert jump.user_id == 1
        assert jump.course_id == 1
        assert jump.from_node_title == "洛必达法则"
        assert jump.to_node_title == "函数极限"
        assert jump.trigger_type == "prerequisite_gap"
        assert jump.is_returned == False
        assert jump.jump_depth == 1  # 默认深度为1
        
        print("✅ 模型创建测试通过")
    
    def test_nested_jump_support(self, db_session):
        """测试多层嵌套跳转支持"""
        from app.models.progress_model import LearningJumpHistory
        
        # 创建第一层跳转：洛必达法则 -> 函数极限
        jump1 = LearningJumpHistory(
            user_id=1,
            course_id=1,
            session_id="session-nested-001",
            from_node_id=15,
            from_node_title="洛必达法则",
            to_node_id=5,
            to_node_title="函数极限",
            trigger_type="prerequisite_gap",
            confidence_score=0.85,
        )
        
        db_session.add(jump1)
        db_session.commit()
        db_session.refresh(jump1)
        
        # 创建第二层跳转：函数极限 -> 数列极限（从jump1嵌套）
        jump2 = LearningJumpHistory(
            user_id=1,
            course_id=1,
            session_id="session-nested-001",
            from_node_id=5,
            from_node_title="函数极限",
            to_node_id=3,
            to_node_title="数列极限",
            trigger_type="prerequisite_gap",
            parent_jump_id=jump1.id,
            confidence_score=0.8,
        )
        
        db_session.add(jump2)
        db_session.commit()
        db_session.refresh(jump2)
        
        # 验证嵌套关系和深度计算
        assert jump2.parent_jump_id == jump1.id
        assert jump2.jump_depth == 2  # 第二层，深度应为2
        
        print("✅ 多层嵌套跳转测试通过")
    
    def test_return_and_review_tracking(self, db_session):
        """测试返回标记和复习完成追踪"""
        from app.models.progress_model import LearningJumpHistory
        
        jump = LearningJumpHistory(
            user_id=1,
            course_id=1,
            from_node_id=10,
            to_node_id=5,
            trigger_type="prerequisite_gap",
        )
        
        db_session.add(jump)
        db_session.commit()
        db_session.refresh(jump)
        
        # 初始状态
        assert jump.is_returned == False
        assert jump.returned_at is None
        assert jump.review_completed == False
        assert jump.review_duration_seconds == 0
        
        # 标记返回
        jump.is_returned = True
        jump.returned_at = datetime.utcnow()
        jump.review_duration_seconds = 300  # 5分钟复习
        db_session.add(jump)
        db_session.commit()
        
        # 验证更新后的状态
        updated_jump = db_session.get(LearningJumpHistory, jump.id)
        assert updated_jump.is_returned == True
        assert updated_jump.returned_at is not None
        assert updated_jump.review_duration_seconds == 300
        
        # 标记复习完成
        updated_jump.review_completed = True
        db_session.add(updated_jump)
        db_session.commit()
        
        final_jump = db_session.get(LearningJumpHistory, jump.id)
        assert final_jump.review_completed == True
        
        print("✅ 返回和复习追踪测试通过")


class TestPrerequisiteGapAnalysisAPI:
    """测试前置知识缺陷检测API"""
    
    @patch('app.services.prerequisite_service.llm_client.chat')
    def test_analyze_gap_with_clear_deficiency(self, mock_chat, test_client):
        """测试检测到明确的前置知识缺陷"""
        mock_response = Mock()
        mock_response.content = json.dumps({
            "has_gaps": True,
            "overall_confidence": 0.9,
            "weak_prerequisites": [
                {
                    "prerequisite_id": 5,
                    "matched_title": "函数极限",
                    "reason": "学生未掌握极限定义",
                    "confidence": 0.92,
                    "urgency_level": "high"
                }
            ],
            "suggested_action": "jump_to_review",
            "analysis_summary": "强烈建议先复习函数极限概念"
        }, ensure_ascii=False)
        mock_chat.return_value = AsyncMock(return_value=mock_response)()
        
        response = test_client.post("/api/v1/prerequisite/analyze-gap", json={
            "courseId": 1,
            "currentNodeId": 15,
            "question": "洛必达法则中的0/0型不定式是什么意思？",
            "conversationHistory": []
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["code"] == 200
        assert data["data"]["hasGaps"] == True
        assert data["data"]["overallConfidence"] >= 0.85
        assert len(data["data"]["weakPrerequisites"]) > 0
        assert data["data"]["suggestedAction"] == "jump_to_review"
        
        print("✅ 缺陷检测API测试通过（有缺陷场景）")
    
    @patch('app.services.prerequisite_service.llm_client.chat')
    def test_analyze_gap_no_deficiency(self, mock_chat, test_client):
        """测试无前置知识缺陷的场景"""
        mock_response = Mock()
        mock_response.content = json.dumps({
            "has_gaps": False,
            "overall_confidence": 0.3,
            "weak_prerequisites": [],
            "suggested_action": "continue",
            "analysis_summary": "学生理解良好，无需跳转复习"
        }, ensure_ascii=False)
        mock_chat.return_value = AsyncMock(return_value=mock_response)()
        
        response = test_client.post("/api/v1/prerequisite/analyze-gap", json={
            "courseId": 1,
            "currentNodeId": 5,
            "question": "极限的定义是什么？",
            "conversationHistory": []
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["code"] == 200
        assert data["data"]["hasGaps"] == False
        assert len(data["data"]["weakPrerequisites"]) == 0
        assert data["data"]["suggestedAction"] == "continue"
        
        print("✅ 缺陷检测API测试通过（无缺陷场景）")
    
    def test_analyze_gap_missing_parameters(self, test_client):
        """测试缺少必要参数的情况"""
        response = test_client.post("/api/v1/prerequisite/analyze-gap", json={
            "courseId": 1,
            # 缺少 currentNodeId 和 question
        })
        
        assert response.status_code == 422  # Validation Error
        
        print("✅ 参数校验测试通过")


class TestJumpManagementAPI:
    """测试跳转管理API"""
    
    def test_execute_jump_successfully(self, test_client, db_session):
        """测试成功执行跳转"""
        response = test_client.post("/api/v1/prerequisite/jump", json={
            "courseId": 1,
            "fromNodeId": 15,
            "fromNodeTitle": "洛必达法则",
            "fromNodeIndex": 14,
            "toPrerequisiteId": 5,
            "toNodeTitle": "函数极限",
            "toNodeIndex": 2,
            "triggerQuestion": "这个公式怎么推导？",
            "gapDescription": "需要掌握极限基础",
            "confidenceScore": 0.9,
            "urgencyLevel": "high",
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["code"] == 200
        assert data["data"]["success"] == True
        assert data["data"]["jumpId"] is not None
        assert data["data"]["canGoBack"] == True
        assert isinstance(data["data"]["jumpStack"], list)
        
        print("✅ 执行跳转API测试通过")
    
    def test_return_to_original_position(self, test_client, db_session):
        """测试返回原位置"""
        from app.models.progress_model import LearningJumpHistory
        
        # 先创建一条跳转记录
        jump = LearningJumpHistory(
            user_id=1,
            course_id=1,
            from_node_id=15,
            from_node_title="洛必达法则",
            from_node_index=14,
            to_node_id=5,
            to_node_title="函数极限",
            to_node_index=2,
        )
        
        db_session.add(jump)
        db_session.commit()
        db_session.refresh(jump)
        
        # 执行返回操作
        response = test_client.post("/api/v1/prerequisite/return", json={
            "jumpId": jump.id,
            "reviewDurationSeconds": 300,
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["code"] == 200
        assert data["data"]["success"] == True
        assert data["data"]["originalNode"] is not None
        assert data["data"]["originalNode"]["nodeId"] == 15
        assert data["data"]["originalNode"]["nodeTitle"] == "洛必达法则"
        assert data["data"]["reviewSummary"] is not None
        
        print("✅ 返回原位置API测试通过")
    
    def test_get_jump_stack(self, test_client, db_session):
        """测试获取当前跳转栈"""
        response = test_client.get("/api/v1/prerequisite/jump-stack?courseId=1&includeReturned=false")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["code"] == 200
        assert "stack" in data["data"]
        assert "currentDepth" in data["data"]
        assert "canGoBack" in data["data"]
        assert isinstance(data["data"]["stack"], list)
        
        print("✅ 获取跳转栈API测试通过")


class TestNestedJumpScenarios:
    """测试多层嵌套跳转场景"""
    
    def test_three_level_nested_jumps(self, test_client, db_session):
        """测试三层嵌套跳转：A → B → C → D"""
        jumps = []
        
        # 第一层：A(洛必达) → B(函数极限)
        resp1 = test_client.post("/api/v1/prerequisite/jump", json={
            "courseId": 1,
            "fromNodeId": 20,
            "fromNodeTitle": "洛必达法则应用",
            "toPrerequisiteId": 15,
            "toNodeTitle": "洛必达法则基础",
            "triggerQuestion": "不会用这个公式",
            "gapDescription": "需要理解基本原理",
            "confidenceScore": 0.88,
            "urgencyLevel": "high",
        })
        jump1_id = resp1.json()["data"]["jumpId"]
        jumps.append(jump1_id)
        
        # 第二层：B(函数极限) → C(数列极限)
        resp2 = test_client.post("/api/v1/prerequisite/jump", json={
            "courseId": 1,
            "fromNodeId": 15,
            "fromNodeTitle": "洛必达法则基础",
            "toPrerequisiteId": 5,
            "toNodeTitle": "函数极限",
            "parentJumpId": jump1_id,
            "triggerQuestion": "什么是极限？",
            "gapDescription": "需要先学极限概念",
            "confidenceScore": 0.91,
            "urgencyLevel": "high",
        })
        jump2_id = resp2.json()["data"]["jumpId"]
        jumps.append(jump2_id)
        
        # 第三层：C(数列极限) → D(极限定义)
        resp3 = test_client.post("/api/v1/prerequisite/jump", json={
            "courseId": 1,
            "fromNodeId": 5,
            "fromNodeTitle": "函数极限",
            "toPrerequisiteId": 3,
            "toNodeTitle": "数列极限定义",
            "parentJumpId": jump2_id,
            "triggerQuestion": "ε-δ定义看不懂",
            "gapDescription": "需要理解极限的严格定义",
            "confidenceScore": 0.93,
            "urgencyLevel": "high",
        })
        jump3_id = resp3.json()["data"]["jumpId"]
        jumps.append(jump3_id)
        
        # 验证所有跳转都成功创建
        for i, jump_id in enumerate(jumps):
            assert jump_id is not None, f"第{i+1}层跳转失败"
        
        # 验证跳转栈包含3条记录
        stack_resp = test_client.get(f"/api/v1/prerequisite/jump-stack?courseId=1")
        stack_data = stack_resp.json()["data"]
        
        assert stack_data["currentDepth"] >= 3
        assert stack_data["unresolvedCount"] >= 3
        
        print("✅ 三层嵌套跳转场景测试通过")
    
    def test_sequential_return_from_nested_jumps(self, test_client, db_session):
        """测试从多层嵌套中逐级返回：D → C → B → A"""
        # 假设已有3条嵌套跳转记录（ID: 3, 2, 1）
        # 从最内层开始返回
        
        # 第一步：返回第三层 (D → C)
        resp1 = test_client.post("/api/v1/prerequisite/return", json={
            "jumpId": 3,
            "reviewDurationSeconds": 180,
        })
        assert resp1.json()["data"]["originalNode"]["nodeId"] == 5  # 回到C
        
        # 第二步：返回第二层 (C → B)
        resp2 = test_client.post("/api/v1/prerequisite/return", json={
            "jumpId": 2,
            "reviewDurationSeconds": 240,
        })
        assert resp2.json()["data"]["originalNode"]["nodeId"] == 15  # 回到B
        
        # 第三步：返回第一层 (B → A)
        resp3 = test_client.post("/api/v1/prerequisite/return", json={
            "jumpId": 1,
            "reviewDurationSeconds": 300,
        })
        assert resp3.json()["data"]["originalNode"]["nodeId"] == 20  # 回到A
        
        # 最终应该回到起点
        final_stack = test_client.get("/api/v1/prerequisite/jump-stack?courseId=1")
        unresolved_count = final_stack.json()["data"]["unresolvedCount"]
        assert unresolved_count == 0  # 所有跳转都已解决
        
        print("✅ 逐级返回嵌套跳转测试通过")


class TestLearningPathVisualization:
    """测试学习路径可视化功能"""
    
    def test_get_learning_path_data(self, test_client, db_session):
        """测试获取学习路径数据"""
        response = test_client.get("/api/v1/prerequisite/learning-path?courseId=1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["code"] == 200
        path_data = data["data"]
        
        # 验证数据结构
        assert "nodes" in path_data
        assert "edges" in path_data
        assert "currentPath" in path_data
        assert "statistics" in path_data
        
        # 验证统计信息结构
        stats = path_data["statistics"]
        assert "totalJumps" in stats
        assert "completedJumps" in stats
        assert "pendingJumps" in stats
        assert "avgReviewTime" in stats
        
        print("✅ 学习路径数据获取测试通过")
    
    def test_path_includes_jump_edges(self, test_client, db_session):
        """测试路径数据包含跳转边"""
        from app.models.progress_model import LearningJumpHistory
        
        # 创建一条已返回的跳转记录
        jump = LearningJumpHistory(
            user_id=1,
            course_id=1,
            from_node_id=15,
            from_node_title="洛必达法则",
            to_node_id=5,
            to_node_title="函数极限",
            is_returned=True,
            returned_at=datetime.utcnow(),
            review_duration_seconds=300,
        )
        
        db_session.add(jump)
        db_session.commit()
        
        # 获取路径数据
        response = test_client.get("/api/v1/prerequisite/learning-path?courseId=1")
        edges = response.json()["data"]["edges"]
        
        # 应该包含刚才创建的跳转边
        jump_edges = [e for e in edges if e["type"] == "prerequisite_jump"]
        assert len(jump_edges) > 0
        
        # 验证边的属性
        last_jump_edge = jump_edges[-1]
        assert last_jump_edge["from"] == 15
        assert last_jump_edge["to"] == 5
        assert last_jump_edge["isReturned"] == True
        
        print("✅ 学习路径跳转边测试通过")


class TestEdgeCasesAndErrorHandling:
    """边界条件和异常处理测试"""
    
    def test_return_nonexistent_jump(self, test_client):
        """尝试返回不存在的跳转记录"""
        response = test_client.post("/api/v1/prerequisite/return", json={
            "jumpId": 99999,  # 不存在的ID
            "reviewDurationSeconds": 100,
        })
        
        assert response.status_code == 404
        assert "不存在" in response.json()["message"]
        
        print("✅ 不存在跳转记录处理测试通过")
    
    def test_mark_reviewed_nonexistent(self, test_client):
        """标记不存在的跳转为已完成"""
        response = test_client.post("/api/v1/prerequisite/mark-reviewed", json={
            "jumpId": 88888,
        })
        
        assert response.status_code == 404
        
        print("✅ 不存在记录标记处理测试通过")
    
    def test_confidence_score_bounds(self, test_client, db_session):
        """测试置信度分数边界值"""
        # 测试超出范围的置信度（应被后端约束）
        response = test_client.post("/api/v1/prerequisite/jump", json={
            "courseId": 1,
            "fromNodeId": 1,
            "toPrerequisiteId": 2,
            "confidenceScore": 1.5,  # 超出范围 (>1.0)
            "urgencyLevel": "high",
        })
        
        # 应该返回验证错误或自动修正
        assert response.status_code in [200, 422]
        
        print("✅ 置信度边界值处理测试通过")
    
    def test_urgency_level_validation(self, test_client, db_session):
        """测试紧急程度枚举值验证"""
        invalid_levels = ["critical", "normal", "", "HIGH"]  # 无效值
        
        for level in invalid_levels:
            response = test_client.post("/api/v1/prerequisite/jump", json={
                "courseId": 1,
                "fromNodeId": 1,
                "toPrerequisiteId": 2,
                "urgencyLevel": level,
            })
            
            # 应该拒绝无效值或使用默认值
            assert response.status_code in [200, 422]
        
        print("✅ 紧急程度验证测试通过")
    
    def test_empty_conversation_history(self, test_client):
        """测试空对话历史"""
        @patch('app.services.prerequisite_service.llm_client.chat')
        def test_with_empty_history(mock_chat):
            mock_response = Mock()
            mock_response.content = json.dumps({
                "has_gaps": False,
                "overall_confidence": 0.0,
                "weak_prerequisites": [],
                "suggested_action": "continue"
            })
            mock_chat.return_value = AsyncMock(return_value=mock_response)()
            
            response = test_client.post("/api/v1/prerequisite/analyze-gap", json={
                "courseId": 1,
                "currentNodeId": 5,
                "question": "简单问题",
                "conversationHistory": [],  # 显式传空数组
            })
            
            assert response.status_code == 200
            
        test_with_empty_history()
        print("✅ 空对话历史处理测试通过")


class TestPerformanceAndConcurrency:
    """性能和并发测试"""
    
    def test_rapid_multiple_jumps(self, test_client, db_session):
        """快速连续多次跳转"""
        jump_ids = []
        
        for i in range(5):
            response = test_client.post("/api/v1/prerequisite/jump", json={
                "courseId": 1,
                "fromNodeId": 10 + i,
                "fromNodeTitle": f"节点{10+i}",
                "toPrerequisiteId": i,
                "toNodeTitle": f"前置知识点{i}",
                "triggerQuestion": f"问题{i}",
                "gapDescription": f"描述{i}",
                "confidenceScore": 0.7 + (i * 0.05),
                "urgencyLevel": "medium",
            })
            
            assert response.status_code == 200
            jump_ids.append(response.json()["data"]["jumpId"])
        
        # 所有跳转都应成功
        assert len(jump_ids) == 5
        assert all(jid is not None for jid in jump_ids)
        
        print("✅ 快速连续跳转性能测试通过")
    
    def test_concurrent_jump_operations(self, test_client, db_session):
        """并发跳转操作（模拟）"""
        import threading
        results = []
        errors = []
        
        def make_jump(index):
            try:
                response = test_client.post("/api/v1/prerequisite/jump", json={
                    "courseId": 1,
                    "fromNodeId": 100 + index,
                    "toPrerequisiteId": index,
                    "triggerQuestion": f"并发问题{index}",
                })
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        threads = []
        for i in range(3):
            t = threading.Thread(target=make_jump, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=5)
        
        # 所有并发请求都应该成功或合理失败
        assert len(errors) == 0, f"并发错误: {errors}"
        assert all(status in [200, 422] for status in results)
        
        print("✅ 并发操作测试通过")


# ========== 主测试入口 ==========
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
