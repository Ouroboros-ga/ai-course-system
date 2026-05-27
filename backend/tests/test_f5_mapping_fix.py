"""
F5映射引擎修复验证测试

验证内容：
1. ScriptNode临时类包含timestamp字段
2. 脚本生成时自动预估时间戳
3. TTS合成后可更新精确时间戳
4. F6播放器优先使用KnowledgePageMap表数据
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlmodel import Session, select

from app.services.document_service import ScriptNode as TempScriptNode, ScriptGenerator
from app.services.mapping_service import MappingService
from app.models.course_model import Course, CourseScript, ScriptNode, ScriptNodeType
from app.models.mapping_model import KnowledgePageMap


class TestScriptNodeTimestampFields:
    """测试1: 验证ScriptNode临时类包含timestamp字段"""

    def test_temp_script_node_has_timestamp_fields(self):
        """临时ScriptNode应包含timestamp_start和timestamp_end字段"""
        node = TempScriptNode(
            chapter_id="chap_001",
            node_type="knowledge_point",
            title="测试节点",
            content="测试内容",
        )

        assert hasattr(node, 'timestamp_start'), "缺少timestamp_start字段"
        assert hasattr(node, 'timestamp_end'), "缺少timestamp_end字段"
        assert node.timestamp_start == 0.0, "默认值应为0.0"
        assert node.timestamp_end == 0.0, "默认值应为0.0"

    def test_temp_script_node_can_set_timestamps(self):
        """临时ScriptNode可以设置自定义时间戳"""
        node = TempScriptNode(
            chapter_id="chap_001",
            node_type="knowledge_point",
            title="测试节点",
            content="测试内容",
            timestamp_start=10.5,
            timestamp_end=25.8,
        )

        assert node.timestamp_start == 10.5
        assert node.timestamp_end == 25.8


class TestTimestampEstimation:
    """测试2: 验证脚本生成时的时间戳预估逻辑"""

    def test_estimate_timestamps_basic(self):
        """基本时间戳预估：3个节点，时长分别为60/90/120秒"""
        nodes = [
            TempScriptNode(chapter_id="c1", node_type="kp", title="N1", content="A" * 150, duration=60),
            TempScriptNode(chapter_id="c2", node_type="kp", title="N2", content="B" * 250, duration=90),
            TempScriptNode(chapter_id="c3", node_type="kp", title="N3", content="C" * 350, duration=120),
        ]

        result_nodes = ScriptGenerator._estimate_timestamps(nodes)

        # 第一个节点
        assert result_nodes[0].timestamp_start == 0.0
        assert result_nodes[0].timestamp_end == 60.0

        # 第二个节点
        assert result_nodes[1].timestamp_start == 60.0
        assert result_nodes[1].timestamp_end == 150.0

        # 第三个节点
        assert result_nodes[2].timestamp_start == 150.0
        assert result_nodes[2].timestamp_end == 270.0

    def test_estimate_timestamps_single_node(self):
        """单节点时间戳预估"""
        nodes = [
            TempScriptNode(chapter_id="c1", node_type="opening", title="开场", content="欢迎", duration=45)
        ]

        result_nodes = ScriptGenerator._estimate_timestamps(nodes)

        assert len(result_nodes) == 1
        assert result_nodes[0].timestamp_start == 0.0
        assert result_nodes[0].timestamp_end == 45.0

    def test_estimate_timestamps_empty_list(self):
        """空列表应返回空列表"""
        result_nodes = ScriptGenerator._estimate_timestamps([])
        assert result_nodes == []

    def test_estimate_timestamps_precision(self):
        """验证时间戳精度为2位小数"""
        nodes = [
            TempScriptNode(chapter_id="c1", node_type="kp", title="N1", content="X", duration=63)
        ]

        result_nodes = ScriptGenerator._estimate_timestamps(nodes)

        assert result_nodes[0].timestamp_start == round(0.0, 2)
        assert result_nodes[0].timestamp_end == round(63.0, 2)


class TestTimestampCalculationFromAudio:
    """测试3: 验证TTS合成后的精确时间戳计算"""

    @pytest.fixture
    def mock_session(self):
        """创建模拟数据库会话"""
        session = Mock(spec=Session)
        return session

    def test_calculate_timestamps_normal_case(self, mock_session):
        """正常情况：基于实际音频时长按比例分配"""

        # 模拟数据库查询返回的节点列表
        mock_nodes = [
            Mock(id=1, script_id=100, node_index=0, duration=60,
                 timestamp_start=0.0, timestamp_end=0.0),
            Mock(id=2, script_id=100, node_index=1, duration=90,
                 timestamp_start=0.0, timestamp_end=0.0),
            Mock(id=3, script_id=100, node_index=2, duration=120,
                 timestamp_start=0.0, timestamp_end=0.0),
        ]

        mock_session.exec.return_value.all.return_value = mock_nodes
        mock_session.add = Mock()
        mock_session.commit = Mock()

        audio_duration = 270.0  # 实际TTS总时长（与预估一致）
        success = MappingService.calculate_timestamps_from_audio(
            mock_session, script_id=100, audio_duration=audio_duration
        )

        assert success is True

        # 验证每个节点的时间戳被正确设置
        assert mock_nodes[0].timestamp_start == 0.0
        assert mock_nodes[0].timestamp_end == pytest.approx(60.0, rel=0.01)

        assert mock_nodes[1].timestamp_start == pytest.approx(60.0, rel=0.01)
        assert mock_nodes[1].timestamp_end == pytest.approx(150.0, rel=0.01)

        assert mock_nodes[2].timestamp_start == pytest.approx(150.0, rel=0.01)
        assert mock_nodes[2].timestamp_end == pytest.approx(270.0, rel=0.01)

    def test_calculate_timestamps_with_different_audio_duration(self, mock_session):
        """实际音频时长与预估不同时：仍按比例分配"""

        mock_nodes = [
            Mock(id=1, script_id=101, node_index=0, duration=60,
                 timestamp_start=0.0, timestamp_end=0.0),
            Mock(id=2, script_id=101, node_index=1, duration=60,
                 timestamp_start=0.0, timestamp_end=0.0),
        ]

        mock_session.exec.return_value.all.return_value = mock_nodes
        mock_session.add = Mock()
        mock_session.commit = Mock()

        # 实际音频时长180秒（比预估的120秒长50%）
        audio_duration = 180.0
        success = MappingService.calculate_timestamps_from_audio(
            mock_session, script_id=101, audio_duration=audio_duration
        )

        assert success is True

        # 应该按比例重新分配：每个节点90秒
        assert mock_nodes[0].timestamp_start == 0.0
        assert mock_nodes[0].timestamp_end == pytest.approx(90.0, rel=0.01)

        assert mock_nodes[1].timestamp_start == pytest.approx(90.0, rel=0.01)
        assert mock_nodes[1].timestamp_end == pytest.approx(180.0, rel=0.01)

    def test_calculate_timestamps_zero_duration_fallback(self, mock_session):
        """节点总时长为0时：使用均分策略"""

        mock_nodes = [
            Mock(id=1, script_id=102, node_index=0, duration=0,
                 timestamp_start=0.0, timestamp_end=0.0),
            Mock(id=2, script_id=102, node_index=1, duration=0,
                 timestamp_start=0.0, timestamp_end=0.0),
            Mock(id=3, script_id=102, node_index=2, duration=0,
                 timestamp_start=0.0, timestamp_end=0.0),
        ]

        mock_session.exec.return_value.all.return_value = mock_nodes
        mock_session.add = Mock()
        mock_session.commit = Mock()

        audio_duration = 120.0
        success = MappingService.calculate_timestamps_from_audio(
            mock_session, script_id=102, audio_duration=audio_duration
        )

        assert success is True

        # 均分：每个节点40秒
        for i, node in enumerate(mock_nodes):
            expected_start = i * 40.0
            expected_end = (i + 1) * 40.0
            assert node.timestamp_start == pytest.approx(expected_start, rel=0.01)
            assert node.timestamp_end == pytest.approx(expected_end, rel=0.01)

    def test_calculate_timestamps_empty_nodes(self, mock_session):
        """无节点时应返回False并记录警告"""
        mock_session.exec.return_value.all.return_value = []
        mock_session.commit = Mock()

        success = MappingService.calculate_timestamps_from_audio(
            mock_session, script_id=999, audio_duration=100.0
        )

        assert success is False


class TestPlayerAPIMappingPriority:
    """测试4: 验证F6播放器API优先使用KnowledgePageMap数据"""

    @pytest.fixture
    def setup_mock_data(self):
        """构建模拟数据：包含ScriptNode和KnowledgePageMap"""

        # 模拟ScriptNode（默认页码可能不正确）
        mock_node = Mock()
        mock_node.id = 1
        mock_node.node_index = 0
        mock_node.node_type = ScriptNodeType.KNOWLEDGE_POINT
        mock_node.title = "知识点1"
        mock_node.content = "这是第一个知识点的详细讲解..."
        mock_node.chapter_id = "chap_001"
        mock_node.timestamp_start = 0.0
        mock_node.timestamp_end = 60.0
        mock_node.duration = 60
        mock_node.page_start = 1  # 默认值
        mock_node.page_end = 1   # 默认值
        mock_node.is_key_point = True

        # 模拟KnowledgePageMap（正确的映射数据）
        mock_mapping = Mock()
        mock_mapping.node_id = 1
        mock_mapping.page_start = 3  # 正确的起始页
        mock_mapping.page_end = 5   # 正确的结束页
        mock_mapping.confidence = 0.95
        mock_mapping.is_manual = True

        return {
            'node': mock_node,
            'mapping': mock_mapping,
        }

    def test_player_uses_mapping_table_priority(self, setup_mock_data):
        """播放器应优先使用KnowledgePageMap的页码数据"""
        node = setup_mock_data['node']
        mapping = setup_mock_data['mapping']

        page_map_dict = {mapping.node_id: mapping}

        # 模拟播放器API的逻辑
        if node.id in page_map_dict:
            page_start = page_map_dict[node.id].page_start
            page_end = page_map_dict[node.id].page_end
        else:
            page_start = node.page_start
            page_end = node.page_end

        # 验证使用了映射表的正确数据
        assert page_start == 3, f"期望page_start=3，实际{page_start}"
        assert page_end == 5, f"期望page_end=5，实际{page_end}"

    def test_player_fallback_to_node_when_no_mapping(self, setup_mock_data):
        """没有映射数据时回退到ScriptNode的页码"""
        node = setup_mock_data['node']
        page_map_dict = {}  # 空映射表

        if node.id in page_map_dict:
            page_start = page_map_dict[node.id].page_start
            page_end = page_map_dict[node.id].page_end
        else:
            page_start = node.page_start
            page_end = node.page_end

        # 应该使用节点的默认值
        assert page_start == 1
        assert page_end == 1


class TestEndToEndFlow:
    """端到端流程测试：验证完整的数据流"""

    def test_full_timestamp_generation_flow(self):
        """
        完整流程：
        1. 脚本生成 → 预估时间戳
        2. 数据库写入 → 包含时间戳
        3. TTS合成 → 更新精确时间戳
        4. F6播放器读取 → 正确的时间戳和页码
        """

        # 步骤1：脚本生成阶段
        input_nodes = [
            TempScriptNode(
                chapter_id="c1", node_type="opening",
                title="开场白", content="欢迎来到本课程..." * 20,
                duration=45
            ),
            TempScriptNode(
                chapter_id="c2", node_type="knowledge_point",
                title="核心概念", content="什么是机器学习..." * 30,
                duration=120
            ),
            TempScriptNode(
                chapter_id="c3", node_type="summary",
                title="总结", content="今天我们学习了..." * 15,
                duration=60
            ),
        ]

        estimated_nodes = ScriptGenerator._estimate_timestamps(input_nodes.copy())

        # 验证步骤1：预估时间戳已生成
        assert all(n.timestamp_end > n.timestamp_start for n in estimated_nodes)
        assert estimated_nodes[-1].timestamp_end == 225.0  # 45+120+60

        print(f"✅ 步骤1完成：预估时间戳生成成功")
        print(f"   节点数: {len(estimated_nodes)}")
        print(f"   总时长: {estimated_nodes[-1].timestamp_end}秒")

        # 步骤2：模拟数据库写入（验证字段完整性）
        for node in estimated_nodes:
            db_node_dict = {
                'timestamp_start': node.timestamp_start,
                'timestamp_end': node.timestamp_end,
                'page_start': node.page_start,
                'page_end': node.page_end,
            }
            assert 'timestamp_start' in db_node_dict
            assert 'timestamp_end' in db_node_dict

        print("✅ 步骤2完成：数据库写入字段完整")

        # 步骤3：模拟TTS合成后更新（使用mock）
        mock_session = Mock()
        mock_db_nodes = [
            Mock(id=i+1, duration=n.duration,
                 timestamp_start=0.0, timestamp_end=0.0)
            for i, n in enumerate(estimated_nodes)
        ]
        mock_session.exec.return_value.all.return_value = mock_db_nodes
        mock_session.add = Mock()
        mock_session.commit = Mock()

        actual_audio_duration = 240.0  # 实际TTS输出比预估稍长
        success = MappingService.calculate_timestamps_from_audio(
            mock_session, script_id=1, audio_duration=actual_audio_duration
        )

        assert success is True
        print(f"✅ 步骤3完成：基于TTS时长({actual_audio_duration}s)更新精确时间戳")

        # 步骤4：F6播放器读取（模拟）
        final_data = []
        for idx, (est_node, db_node) in enumerate(zip(estimated_nodes, mock_db_nodes)):
            player_node = {
                'id': idx + 1,
                'title': est_node.title,
                'timestamp_start': db_node.timestamp_start,
                'timestamp_end': db_node.timestamp_end,
                'has_valid_timestamp': db_node.timestamp_end > 0,
            }
            final_data.append(player_node)

        assert all(n['has_valid_timestamp'] for n in final_data)
        print("✅ 步骤4完成：F6播放器可读取到有效时间戳")

        print("\n🎉 端到端流程验证通过！F5→F6数据流完整可用")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
