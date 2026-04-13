"""
智课脚本生成服务
负责将文档内容转换为结构化的教学脚本
"""

from typing import Optional
from pathlib import Path
import json

from app.common.llm_client import llm_client, Message


class ScriptPromptBuilder:
    """脚本生成Prompt构建器"""
    
    @staticmethod
    def build_structured_script_prompt(markdown_content: str, filename: str) -> tuple[str, str]:
        """
        构建结构化智课脚本的Prompt
        
        Returns:
            tuple: (system_prompt, user_prompt)
        """
        system_prompt = """你是一位专业的课程设计师和教学专家。请根据用户提供的文档内容，生成一份**结构化智课脚本**。

## 脚本结构要求

脚本必须包含以下**教学环节**：

### 1. 开场白 (opening)
- 时长：30-60秒
- 内容：
  - 亲切的问候语
  - 课程主题引入（激发学习兴趣）
  - 学习目标概述
  - 与学生的互动提问

### 2. 知识点讲解 (knowledge_point)
- 每个知识点独立为一个节点
- 时长：60-180秒
- **content字段要求：150-300字**
- 内容结构：
  - 概念定义（清晰、简洁）
  - 原理讲解（深入浅出，详细说明）
  - 实例说明（贴近实际，具体案例）
  - 应用场景（实际运用）
  - 过渡语（与下一个知识点的衔接）

### 3. 互动提问 (question)
- 穿插在知识点之间
- 时长：30-60秒
- **content字段要求：150-300字**
- 内容：
  - 提出思考问题
  - 引导思考方向
  - 简要提示答案要点

### 4. 总结语 (summary)
- 每个章节结束时的回顾
- 时长：45-90秒
- **content字段要求：150-300字**
- 内容：
  - 核心要点回顾（详细总结每个要点）
  - 知识框架梳理
  - 学习建议和方法
  - 下节预告

## 输出格式

请以JSON格式返回，结构如下：
{
    "title": "课程标题",
    "summary": "课程整体摘要",
    "keywords": ["关键词1", "关键词2", ...],
    "total_duration": 总时长(秒),
    "sections": [
        {
            "type": "opening",
            "title": "开场白",
            "content": "讲解文本内容（150-300字的详细讲解）",
            "duration": 45,
            "tone": "enthusiastic",
            "transitions": {
                "next": "接下来，让我们进入今天的核心内容..."
            }
        },
        {
            "type": "knowledge_point",
            "id": "kp_001",
            "title": "知识点标题",
            "definition": "概念定义",
            "explanation": "原理解释（详细说明原理、机制）",
            "examples": ["示例1", "示例2"],
            "content": "完整讲解文本（150-300字，包含概念解释、原理说明、实例分析、应用场景等丰富内容）",
            "duration": 120,
            "difficulty": "medium",
            "is_key_point": true,
            "transitions": {
                "prev": "刚才我们了解了...",
                "next": "理解了概念后，我们来看..."
            }
        },
        {
            "type": "question",
            "title": "互动提问",
            "question": "思考问题",
            "hint": "提示信息",
            "content": "提问文本（150-300字，包含问题背景、引导思路、提示方向）",
            "duration": 30
        },
        {
            "type": "summary",
            "title": "章节小结",
            "key_points": ["要点1", "要点2", "要点3"],
            "content": "总结讲解文本（150-300字，详细回顾核心要点、知识框架、学习建议）",
            "duration": 60,
            "next_preview": "下节课我们将学习..."
        }
    ]
}

## 重要提示

1. **讲解文本(content字段)** 必须是完整的口语化文本，适合直接用于语音合成(TTS)
2. **content字段长度要求严格控制在150-300字之间**，确保内容丰富详实
3. **内容要充实**：包含足够的细节、例子和解释，避免过于简略
4. **过渡语** 要自然流畅，避免生硬的"接下来"
5. **时长控制**：总时长控制在10-20分钟为宜
6. **难度分级**：easy/medium/hard，根据内容复杂度标注
7. **语气标注**：enthusiastic/calm/serious，指导语音合成
8. **必须包含**：开场白至少1个，总结语至少1个，知识点3-8个

请确保返回的是有效的JSON格式。"""

        user_prompt = f"""请根据以下文档内容生成结构化智课脚本：

文件名: {filename}

文档内容：
{markdown_content}

请按照教学专家的标准，生成包含开场白、知识点讲解（带过渡语）、互动提问、总结语的完整结构化脚本。

注意：
- content字段必须是适合语音合成的完整讲解文本
- 每个知识点之间要有自然的过渡语
- 开场白要亲切、吸引人
- 总结语要条理清晰"""

        return system_prompt, user_prompt
    
    @staticmethod
    def build_simple_script_prompt(markdown_content: str, filename: str) -> tuple[str, str]:
        """
        构建简单脚本的Prompt（用于快速生成）
        """
        system_prompt = """你是一位专业的课程设计师。请根据用户提供的文档内容，生成一份智课脚本。

以JSON格式返回：
{
    "title": "课程标题",
    "summary": "课程摘要",
    "keywords": ["关键词1", "关键词2"],
    "total_duration": 总时长(秒),
    "nodes": [
        {
            "chapter_id": "chap_001",
            "node_type": "lecture",
            "title": "节点标题",
            "content": "节点内容",
            "duration": 60,
            "is_key_point": false
        }
    ]
}

节点类型：lecture(讲解), question(问题), summary(总结)"""

        user_prompt = f"""文件名: {filename}

文档内容：
{markdown_content}

请生成智课脚本JSON。"""

        return system_prompt, user_prompt


class SmartCourseService:
    """智课脚本生成服务"""
    
    def __init__(self):
        self.prompt_builder = ScriptPromptBuilder()
    
    async def generate_structured_script(
        self, 
        markdown_content: str, 
        filename: str,
        max_content_length: int = 8000
    ) -> dict:
        """
        生成结构化智课脚本
        
        Args:
            markdown_content: 文档Markdown内容
            filename: 文件名
            max_content_length: 最大内容长度
            
        Returns:
            dict: 包含 script_content, summary_text, keywords 的字典
        """
        print(f"  [SmartCourseService] 开始生成结构化智课脚本...")
        
        if len(markdown_content) > max_content_length:
            truncated_content = markdown_content[:max_content_length]
            truncated_content += f"\n\n[内容已截断，原长度: {len(markdown_content)} 字符]"
        else:
            truncated_content = markdown_content
        
        system_prompt, user_prompt = self.prompt_builder.build_structured_script_prompt(
            truncated_content, filename
        )
        
        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
            
            print(f"  [SmartCourseService] 发送请求，内容长度: {len(user_prompt)} 字符")
            response = await llm_client.chat(messages)
            print(f"  [SmartCourseService] 收到响应，长度: {len(response.content)} 字符")
            
            import re
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                script_content = json.loads(json_match.group())
            else:
                script_content = self._create_default_structured_script(filename, markdown_content)
            
        except Exception as e:
            print(f"  [SmartCourseService] 调用失败: {e}，使用默认脚本")
            script_content = self._create_default_structured_script(filename, markdown_content)
        
        summary_text = script_content.get(
            "summary", 
            f"本课程《{Path(filename).stem}》包含 {len(script_content.get('sections', []))} 个教学环节。"
        )
        keywords = script_content.get("keywords", ["知识点", "课程", Path(filename).stem])
        
        section_count = len(script_content.get('sections', []))
        print(f"  [SmartCourseService] 生成完成: {section_count} 个教学环节")
        
        return {
            "script_content": script_content,
            "summary_text": summary_text,
            "keywords": keywords,
        }
    
    def _create_default_structured_script(self, filename: str, content: str) -> dict:
        """
        创建默认结构化脚本（当AI调用失败时）
        """
        lines = [l.strip() for l in content.split("\n") if l.strip() and len(l.strip()) > 10]
        
        sections = []
        
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
                "content": f"{prev_transition}我们来学习{line[:40]}。{line}这个概念非常重要。",
                "duration": 90 if is_key_point else 60,
                "difficulty": "medium",
                "is_key_point": is_key_point,
                "tone": "calm",
                "transitions": {
                    "prev": prev_transition,
                    "next": next_transition
                } if next_transition else {"prev": prev_transition}
            })
        
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


smart_course_service = SmartCourseService()
