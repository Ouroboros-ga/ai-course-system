"""NX-CT1 R3：代码伴学线程标题前缀回归（纯函数，无外部依赖）。

伴学线程必须在 Nexus 侧边栏一眼可辨：标题只在线程首次插入时落库，
前缀一次、永久有效；非伴学会话原样不动；重复调用不叠加前缀。
"""

from nexus.main import _CODE_TUTOR_TITLE_PREFIX, _thread_title


def test_general_session_title_unchanged():
    assert _thread_title("default", "帮我看看这段代码") == "帮我看看这段代码"
    assert _thread_title("research-1", "调研一下") == "调研一下"


def test_code_tutor_session_gets_prefix():
    title = _thread_title("code-tutor", "为什么这个用例过不了？")
    assert title.startswith(_CODE_TUTOR_TITLE_PREFIX)
    assert "为什么这个用例过不了？" in title


def test_prefix_never_duplicates():
    once = _thread_title("code-tutor", "第一问")
    twice = _thread_title("code-tutor", once)
    assert twice == once
    assert twice.count("代码伴学") == 1


def test_empty_message_falls_back_to_plain_label():
    assert _thread_title("code-tutor", "") == "代码伴学"
    assert _thread_title("code-tutor", "   ") == "代码伴学"


def test_session_id_normalized_before_compare():
    assert _thread_title("code-tutor ", "hi").startswith(_CODE_TUTOR_TITLE_PREFIX)
    assert _thread_title("code-tutor-2", "hi") == "hi"
