#!/usr/bin/env python3
"""
使用 Docling 解析 PPT 文件
支持智能去除标题页和目录页，并生成AI友好的结构化内容
"""
import os
import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Any

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

from docling.document_converter import DocumentConverter

AI_SYSTEM_PROMPT = """你是一个专业的课件内容解析助手。请按照以下规则处理输入的课件内容：

## 输出格式要求
每个知识点单元必须严格遵循以下格式：
```
【标题】<具体标题文本>

<解析内容正文>
```

## 重要规则
1. 标题必须用【标题】标记开头，单独一行
2. 解析内容紧接在标题下方，不要添加任何额外说明语
3. 不要输出"以下是内容"、"根据课件分析"等引导语
4. 不要在结尾添加总结性语句
5. 保持原文的专业术语和公式表达
6. 如遇图片位置标记[图片]，可简要描述图片内容或跳过

## 内容处理规则
1. 标题页内容（如"第X章 XXX"单独出现）应合并到下一节
2. 目录页内容（如"5.1 XXX 5.2 XXX"连续列表）应作为章节概览处理
3. 保留所有公式编号如(5.1)、(5.2)等
4. 保留图表编号如图5-1、表5-2等
"""

AI_USER_PROMPT_TEMPLATE = """请解析以下课件内容，按照【标题】+ 解析内容的格式输出，不要添加任何额外语句：

{content}
"""

def clean_markdown(md_text: str) -> str:
    """清理 Markdown 内容，移除图片标记等"""
    md_text = re.sub(r'<!--\s*image\s*-->', '[图片]', md_text)
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    return md_text.strip()

def is_title_page(text: str) -> bool:
    """检测是否为标题页"""
    text = text.strip()
    
    title_patterns = [
        r'^第[一二三四五六七八九十\d]+[章节部]\s*[：:\s]*\s*.+$',
        r'^Chapter\s*\d+',
        r'^[一二三四五六七八九十]+[、.]\s*.+$',
    ]
    
    for pattern in title_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            if len(text) < 50:
                return True
    
    if len(text) < 30 and re.search(r'[章节部]$', text):
        return True
        
    return False

def is_toc_page(text: str) -> bool:
    """检测是否为目录页"""
    lines = text.strip().split('\n')
    
    toc_pattern = r'^\s*\d+\.?\d*\s+[^\d]+\s*$'
    toc_matches = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(toc_pattern, line):
            toc_matches += 1
    
    if toc_matches >= 3 and toc_matches / max(len([l for l in lines if l.strip()]), 1) > 0.5:
        return True
    
    section_list = re.findall(r'\d+\.\d+\s+[^\d]+', text)
    if len(section_list) >= 4:
        return True
    
    return False

def extract_title(text: str) -> str:
    """从文本中提取标题"""
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if re.match(r'^第[一二三四五六七八九十\d]+[章节部]', line):
            return line
        if re.match(r'^\d+\.\d+\s+', line):
            return line
        if re.match(r'^[一二三四五六七八九十]+[、.]\s*', line):
            return line
        if line.startswith('#'):
            return line.lstrip('#').strip()
        
        if len(line) < 50:
            return line
    
    return "知识点"

def format_section_for_ai(section: Dict[str, Any]) -> Dict[str, Any]:
    """格式化单个段落为AI友好的格式"""
    text = section.get('text', '')
    title = extract_title(text)
    
    content_lines = text.strip().split('\n')
    content_without_title = []
    title_found = False
    
    for line in content_lines:
        line = line.strip()
        if not line:
            continue
        if not title_found and (line == title or line.startswith(title[:20])):
            title_found = True
            continue
        content_without_title.append(line)
    
    content = '\n'.join(content_without_title).strip()
    
    return {
        "title": title,
        "content": content,
        "raw_text": text,
        "label": section.get('label', 'text'),
        "slide": section.get('slide', 0)
    }

def parse_pptx(file_path: str, output_dir: str = None) -> Dict[str, Any]:
    """
    解析 PPT 文件并返回结构化内容
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    if output_dir is None:
        output_dir = file_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"正在解析: {file_path.name}")
    print(f"文件大小: {file_path.stat().st_size / 1024 / 1024:.2f} MB")
    print("-" * 60)
    
    converter = DocumentConverter()
    result = converter.convert(str(file_path))
    
    markdown_content = result.document.export_to_markdown()
    markdown_content = clean_markdown(markdown_content)
    
    md_output_path = output_dir / f"{file_path.stem}_docling.md"
    md_output_path.write_text(markdown_content, encoding="utf-8")
    print(f"Markdown 已保存: {md_output_path}")
    
    sections = []
    slide_index = 0
    
    try:
        for item in result.document.iterate_items():
            item_label = type(item).__name__
            item_text = ""
            
            if hasattr(item, 'text') and item.text:
                item_text = item.text.strip()
            elif hasattr(item, 'export_to_markdown'):
                try:
                    item_text = item.export_to_markdown().strip()
                except:
                    pass
            
            if hasattr(item, 'label'):
                item_label = item.label.value if hasattr(item.label, 'value') else str(item.label)
            
            if item_text:
                item_text = clean_markdown(item_text)
                sections.append({
                    "slide": slide_index,
                    "label": item_label,
                    "text": item_text
                })
            
            if item_label.lower() in ['slide', 'page', 'section'] or (hasattr(item, 'is_slide') and item.is_slide):
                slide_index += 1
                
    except Exception as e:
        print(f"提取详细结构时出错: {e}")
    
    if not sections:
        print("使用备用方法提取内容...")
        lines = markdown_content.split('\n')
        current_section = {"slide": 0, "label": "text", "text": ""}
        section_count = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith('#'):
                if current_section["text"]:
                    sections.append(current_section)
                    section_count += 1
                current_section = {
                    "slide": section_count,
                    "label": "heading",
                    "text": line
                }
            elif re.match(r'^\d+\.\d+', line) or re.match(r'^第[一二三四五六七八九十]+', line):
                if current_section["text"]:
                    sections.append(current_section)
                    section_count += 1
                current_section = {
                    "slide": section_count,
                    "label": "section_title",
                    "text": line
                }
            else:
                if current_section["text"]:
                    current_section["text"] += "\n" + line
                else:
                    current_section["text"] = line
        
        if current_section["text"]:
            sections.append(current_section)
    
    print(f"原始提取 {len(sections)} 个段落")
    
    filtered_sections = []
    removed_count = 0
    
    for i, section in enumerate(sections):
        text = section.get('text', '')
        
        if is_title_page(text):
            print(f"  检测到标题页，已标记: {text[:30]}...")
            section['label'] = 'title_page'
            removed_count += 1
        
        elif is_toc_page(text):
            print(f"  检测到目录页，已标记: {text[:30]}...")
            section['label'] = 'toc_page'
            removed_count += 1
        
        filtered_sections.append(section)
    
    ai_formatted_sections = [format_section_for_ai(s) for s in filtered_sections]
    
    content_sections = [s for s in filtered_sections if s['label'] not in ['title_page', 'toc_page']]
    
    doc_dict = {
        "filename": file_path.name,
        "title": file_path.stem,
        "total_sections": len(sections),
        "content_sections": len(content_sections),
        "removed_pages": {
            "title_pages": len([s for s in filtered_sections if s['label'] == 'title_page']),
            "toc_pages": len([s for s in filtered_sections if s['label'] == 'toc_page'])
        },
        "ai_prompts": {
            "system": AI_SYSTEM_PROMPT,
            "user_template": AI_USER_PROMPT_TEMPLATE,
            "usage_note": "调用AI API时，将system字段作为system消息，将user_template中的{content}替换为具体段落内容后作为user消息"
        },
        "markdown": markdown_content,
        "sections": filtered_sections,
        "ai_formatted": ai_formatted_sections
    }
    
    json_output_path = output_dir / f"{file_path.stem}_docling.json"
    json_output_path.write_text(json.dumps(doc_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 已保存: {json_output_path}")
    print(f"共提取 {len(sections)} 个段落，其中 {len(content_sections)} 个内容段落")
    print(f"已标记 {removed_count} 个标题页/目录页")
    
    return doc_dict


if __name__ == "__main__":
    pptx_path = r"C:\Users\wangz\Desktop\新建文件夹\10-a12基于泛雅平台的AI互动智课生成与实时问答\a12基于泛雅平台的AI互动智课生成与实时问答\课件下载-3月3日\自动控制原理-课件20260303\5. 频域响应法.pptx"
    
    output_dir = r"C:\Users\wangz\PycharmProjects\ai-course-system\backend\app\common\test\assets"
    
    result = parse_pptx(pptx_path, output_dir)
    
    print("\n" + "=" * 60)
    print("解析完成！AI格式化内容示例:")
    print("=" * 60)
    
    for i, sec in enumerate(result["ai_formatted"][:3]):
        if sec['label'] in ['title_page', 'toc_page']:
            print(f"\n[{i+1}] [{sec['label']}] 已标记待移除")
            continue
        print(f"\n[{i+1}] 【标题】{sec['title']}")
        content_preview = sec['content'][:150] + "..." if len(sec['content']) > 150 else sec['content']
        print(f"    {content_preview}")
    
    print("\n" + "=" * 60)
    print("AI提示词示例 (调用API时使用):")
    print("=" * 60)
    print("\n[System消息]:")
    print(result["ai_prompts"]["system"][:300] + "...")
    print("\n[User消息模板]:")
    print(result["ai_prompts"]["user_template"][:200] + "...")
