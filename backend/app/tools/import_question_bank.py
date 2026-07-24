"""Phase B 专用 Excel 导入器

仅读取指定 Excel 文件，不遍历课件目录。
将教学问答数据集导入为 QuestionBankItem 记录，默认 status=unassigned。

Excel 结构（已核验）：
  单表、3123行、11列
  字段：规则分类、标准问题、答案、规则状态、匹配模式、6个相似问法
  无课程、知识点、课件页码或出处字段

使用方法：
  python -m app.tools.import_question_bank "D:\\path\\to\\教学问答数据集.xlsx"
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.models.database import engine
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionStatus,
    QuestionType,
    QuestionDifficulty,
)


# Excel 列名映射（中文 -> 内部字段）
COLUMN_MAP = {
    "规则分类": "category",
    "标准问题": "question_text",
    "答案": "answer",
    "规则状态": "rule_status",
    "匹配模式": "match_mode",
    "相似问法1": "similar_1",
    "相似问法2": "similar_2",
    "相似问法3": "similar_3",
    "相似问法4": "similar_4",
    "相似问法5": "similar_5",
    "相似问法6": "similar_6",
}

# 可能的相似问法列名变体
SIMILAR_COLUMN_VARIANTS = [
    "相似问法1", "相似问法2", "相似问法3", "相似问法4", "相似问法5", "相似问法6",
    "相似问法 1", "相似问法 2", "相似问法 3", "相似问法 4", "相似问法 5", "相似问法 6",
    "相似问题1", "相似问题2", "相似问题3", "相似问题4", "相似问题5", "相似问题6",
]


def _read_excel_rows(file_path: str) -> list[dict[str, Any]]:
    """读取 Excel 文件，返回字典列表。

    使用 openpyxl 读取，不依赖 pandas。
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError("需要 openpyxl: pip install openpyxl")

    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        wb.close()
        return []

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]

    result = []
    for row in rows[1:]:
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        row_dict = {}
        for i, header in enumerate(headers):
            if i < len(row):
                row_dict[header] = row[i]
        result.append(row_dict)

    wb.close()
    return result


def _extract_similar_questions(row: dict[str, Any]) -> list[str]:
    """从行数据中提取所有相似问法"""
    similar = []
    for variant in SIMILAR_COLUMN_VARIANTS:
        value = row.get(variant)
        if value and str(value).strip():
            similar.append(str(value).strip())
    return similar


def _map_row_to_item(row: dict[str, Any], row_index: int, batch_id: str) -> QuestionBankItem:
    """将 Excel 行映射为 QuestionBankItem"""
    question_text = str(row.get("标准问题", "")).strip()
    answer = str(row.get("答案", "")).strip()
    category = str(row.get("规则分类", "")).strip()
    rule_status = str(row.get("规则状态", "")).strip()
    match_mode = str(row.get("匹配模式", "")).strip()
    similar = _extract_similar_questions(row)

    return QuestionBankItem(
        question_text=question_text,
        answer=answer,
        options={},
        similar_questions=similar,
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM,
        category=category,
        match_mode=match_mode,
        rule_status=rule_status,
        course_id=None,  # 未归属
        knowledge_node_ids=[],
        prerequisite_node_ids=[],
        status=QuestionStatus.UNASSIGNED,
        version=1,
        prev_version_id=None,
        is_latest=True,
        import_batch_id=batch_id,
        source_row_index=row_index,
        generated_by="excel_import",
        generation_metadata={},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def import_excel_to_question_bank(
    file_path: str,
    *,
    dry_run: bool = False,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """导入 Excel 文件到题库

    Args:
        file_path: Excel 文件路径
        dry_run: 仅解析不写入数据库
        batch_id: 导入批次ID（不传则自动生成）

    Returns:
        导入统计信息
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Excel 文件不存在: {file_path}")

    if batch_id is None:
        batch_id = f"excel-import-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

    rows = _read_excel_rows(file_path)
    total_rows = len(rows)

    if dry_run:
        return {
            "batch_id": batch_id,
            "total_rows": total_rows,
            "dry_run": True,
            "imported": 0,
        }

    session = Session(engine)
    imported = 0
    skipped = 0
    errors = []

    try:
        for index, row in enumerate(rows, start=2):  # Excel行号从2开始(1是表头)
            question_text = str(row.get("标准问题", "")).strip()
            if not question_text:
                skipped += 1
                continue

            item = _map_row_to_item(row, index, batch_id)
            session.add(item)
            imported += 1

        session.commit()
    except Exception as e:
        session.rollback()
        errors.append(str(e))
        raise
    finally:
        session.close()

    return {
        "batch_id": batch_id,
        "total_rows": total_rows,
        "imported": imported,
        "skipped": skipped,
        "dry_run": False,
        "errors": errors,
    }


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python -m app.tools.import_question_bank <excel路径> [--dry-run]")
        sys.exit(1)

    file_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    print(f"导入文件: {file_path}")
    print(f"模式: {'dry-run' if dry_run else '实际导入'}")

    result = import_excel_to_question_bank(file_path, dry_run=dry_run)
    print(f"结果: {result}")


if __name__ == "__main__":
    main()
