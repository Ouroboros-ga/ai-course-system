#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试结构化脚本生成功能"""

import sys
sys.path.insert(0, 'e:\\smartcarb\\ai-course-system\\backend')

from pathlib import Path


def _create_default_structured_script(filename: str, content: str) -> dict:
    """
    创建默认结构化脚本（当AI调用失败时）
    包含开场白、知识点、过渡语、总结语
    """
    lines = [l.strip() for l in content.split("\n") if l.strip() and len(l.strip()) > 10]
    
    sections = []
    
    # 1. 开场白
    sections.append({
        "type": "opening",
        "id": "sec_000",
        "title": "课程开场",
        "content": f"同学们好！欢迎学习《{Path(filename).stem}》。在今天的课程中，我们将一起探索这个有趣的主题。希望通过今天的学习，大家能够掌握核心概念，并能够灵活运用到实际问题中。",
        "duration": 45,
        "tone": "enthusiastic",
        "transitions": {
            "next": "接下来，让我们进入今天的第一个知识点。"
        }
    })
    
    # 2. 知识点讲解（最多6个）
    for idx, line in enumerate(lines[:6]):
        section_type = "knowledge_point"
        is_key_point = idx % 2 == 0
        
        prev_transition = ""
        next_transition = ""
        
        if idx == 0:
            prev_transition = "首先，"
        elif idx == len(lines[:6]) - 1:
            prev_transition = "最后，"
            next_transition = "学完了这些知识点，让我们来总结一下。"
        else:
            prev_transition = "接下来，"
            next_transition = "理解了这个概念后，我们继续往下看。"
        
        sections.append({
            "type": section_type,
            "id": f"sec_{idx+1:03d}",
            "title": line[:40] + ("..." if len(line) > 40 else ""),
            "definition": line,
            "explanation": f"这是关于{line[:20]}的详细解释。",
            "examples": [f"示例{idx+1}：相关应用场景"],
            "content": f"{prev_transition}我们来学习{line[:40]}。{line}这个概念非常重要，{'' if is_key_point else '大家要认真理解。'}" + 
                      (f"\n{next_transition}" if next_transition else ""),
            "duration": 90 if is_key_point else 60,
            "difficulty": "medium",
            "is_key_point": is_key_point,
            "tone": "calm",
            "transitions": {
                "prev": prev_transition,
                "next": next_transition
            } if next_transition else {"prev": prev_transition}
        })
    
    # 3. 互动提问（穿插在中间）
    if len(sections) > 2:
        sections.insert(3, {
            "type": "question",
            "id": "sec_q001",
            "title": "思考互动",
            "question": "在学习了前面的内容后，大家思考一下：这些知识点之间有什么联系？",
            "hint": "可以从概念的定义和应用场景来思考。",
            "content": "学习了前面的内容，我想请大家思考一个问题：这些知识点之间有什么内在联系？试着用自己的话总结一下。",
            "duration": 30
        })
    
    # 4. 总结语
    key_points = [s["title"] for s in sections if s.get("type") == "knowledge_point"][:3]
    sections.append({
        "type": "summary",
        "id": "sec_sum",
        "title": "课程总结",
        "key_points": key_points if key_points else ["核心概念", "重要原理", "实际应用"],
        "content": f"好的，今天的课程就到这里。我们来回顾一下今天学习的重点：{', '.join(key_points) if key_points else '核心概念和原理'}。希望大家课后能够复习巩固，下节课我们将继续深入学习。",
        "duration": 60,
        "next_preview": "下节课我们将学习更深入的内容。"
    })
    
    total_duration = sum(s["duration"] for s in sections)
    
    return {
        "title": Path(filename).stem,
        "summary": f"本课程《{Path(filename).stem}》共包含 {len(sections)} 个教学环节，总时长约 {total_duration // 60} 分钟。",
        "keywords": ["知识点", "课程", Path(filename).stem],
        "total_duration": total_duration,
        "sections": sections
    }


if __name__ == "__main__":
    # 测试用例
    test_content = """机器学习基础概念
监督学习与无监督学习的区别
线性回归算法原理
决策树算法介绍
神经网络入门
深度学习应用场景"""

    result = _create_default_structured_script("机器学习导论.pdf", test_content)
    
    import json
    print("=" * 60)
    print("结构化智课脚本生成测试")
    print("=" * 60)
    print(f"\n课程标题: {result['title']}")
    print(f"课程摘要: {result['summary']}")
    print(f"关键词: {', '.join(result['keywords'])}")
    print(f"总时长: {result['total_duration']} 秒")
    print(f"\n教学环节 ({len(result['sections'])} 个):")
    print("-" * 60)
    
    for idx, section in enumerate(result['sections'], 1):
        print(f"\n[{idx}] {section['type'].upper()}: {section['title']}")
        print(f"    时长: {section['duration']}秒")
        print(f"    内容预览: {section['content'][:80]}...")
        if section.get('transitions'):
            print(f"    过渡语: {section.get('transitions', {})}")
    
    print("\n" + "=" * 60)
    print("完整JSON输出:")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))
