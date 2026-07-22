from __future__ import annotations

import copy
import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(RESEARCH_ROOT))
sys.path.insert(0, str(TESTS_ROOT))

from src.canonical import canonical_json_bytes
from tools.human_selection_review import finalize_selection_review, prepare_selection_review
from tools.human_selection_workbook import (
    HumanSelectionWorkbookError,
    import_selection_review_workbook,
    review_workbook_tables,
)
from test_human_selection_review import complete_review, make_source, test_directory


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xml_bytes(root: ElementTree.Element) -> bytes:
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def write_review_xlsx(path: Path, tables: dict[str, list[list[object]]],
    *, formula_cell: tuple[str, int, int] | None = None) -> None:
    ElementTree.register_namespace("", MAIN_NS)
    ElementTree.register_namespace("r", REL_NS)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        content = ElementTree.Element(f"{{{CONTENT_NS}}}Types")
        ElementTree.SubElement(content, f"{{{CONTENT_NS}}}Default", Extension="rels",
            ContentType="application/vnd.openxmlformats-package.relationships+xml")
        ElementTree.SubElement(content, f"{{{CONTENT_NS}}}Default", Extension="xml", ContentType="application/xml")
        ElementTree.SubElement(content, f"{{{CONTENT_NS}}}Override", PartName="/xl/workbook.xml",
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
        for index in range(1, len(tables) + 1):
            ElementTree.SubElement(content, f"{{{CONTENT_NS}}}Override",
                PartName=f"/xl/worksheets/sheet{index}.xml",
                ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
        archive.writestr("[Content_Types].xml", _xml_bytes(content))

        package_rels = ElementTree.Element(f"{{{PACKAGE_REL_NS}}}Relationships")
        ElementTree.SubElement(package_rels, f"{{{PACKAGE_REL_NS}}}Relationship", Id="rId1",
            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            Target="xl/workbook.xml")
        archive.writestr("_rels/.rels", _xml_bytes(package_rels))

        workbook = ElementTree.Element(f"{{{MAIN_NS}}}workbook")
        sheets = ElementTree.SubElement(workbook, f"{{{MAIN_NS}}}sheets")
        workbook_rels = ElementTree.Element(f"{{{PACKAGE_REL_NS}}}Relationships")
        for index, name in enumerate(tables, start=1):
            ElementTree.SubElement(sheets, f"{{{MAIN_NS}}}sheet", name=name, sheetId=str(index),
                **{f"{{{REL_NS}}}id": f"rId{index}"})
            ElementTree.SubElement(workbook_rels, f"{{{PACKAGE_REL_NS}}}Relationship", Id=f"rId{index}",
                Type=DOCUMENT_REL_NS, Target=f"worksheets/sheet{index}.xml")
        archive.writestr("xl/workbook.xml", _xml_bytes(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", _xml_bytes(workbook_rels))

        for sheet_index, (name, rows) in enumerate(tables.items(), start=1):
            worksheet = ElementTree.Element(f"{{{MAIN_NS}}}worksheet")
            sheet_data = ElementTree.SubElement(worksheet, f"{{{MAIN_NS}}}sheetData")
            for row_index, values in enumerate(rows, start=1):
                row = ElementTree.SubElement(sheet_data, f"{{{MAIN_NS}}}row", r=str(row_index))
                for column_index, value in enumerate(values, start=1):
                    is_formula = formula_cell == (name, row_index, column_index)
                    if not is_formula and (value is None or value == ""):
                        continue
                    reference = f"{_column_name(column_index)}{row_index}"
                    cell = ElementTree.SubElement(row, f"{{{MAIN_NS}}}c", r=reference)
                    if is_formula:
                        ElementTree.SubElement(cell, f"{{{MAIN_NS}}}f").text = "1+1"
                        ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = "2"
                    elif isinstance(value, bool):
                        cell.set("t", "b")
                        ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = "1" if value else "0"
                    elif isinstance(value, (int, float)):
                        ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = str(value)
                    else:
                        cell.set("t", "inlineStr")
                        inline = ElementTree.SubElement(cell, f"{{{MAIN_NS}}}is")
                        text = ElementTree.SubElement(inline, f"{{{MAIN_NS}}}t")
                        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        text.text = str(value)
            archive.writestr(f"xl/worksheets/sheet{sheet_index}.xml", _xml_bytes(worksheet))


class HumanSelectionWorkbookTests(unittest.TestCase):
    def test_blank_workbook_roundtrips_pending_packet(self) -> None:
        with test_directory() as root:
            make_source(root)
            packet = prepare_selection_review(root, query_target=64)
            workbook = root / "review.xlsx"
            write_review_xlsx(workbook, review_workbook_tables(packet))
            imported = import_selection_review_workbook(packet, workbook)
            self.assertEqual(canonical_json_bytes(imported), canonical_json_bytes(packet))

    def test_completed_workbook_roundtrips_and_can_finalize(self) -> None:
        with test_directory() as root:
            make_source(root)
            pending = prepare_selection_review(root, query_target=64)
            completed = complete_review(pending)
            workbook = root / "review.xlsx"
            write_review_xlsx(workbook, review_workbook_tables(pending, completed))
            imported = import_selection_review_workbook(pending, workbook)
            self.assertEqual(canonical_json_bytes(imported), canonical_json_bytes(completed))
            result = finalize_selection_review(imported, root, root / "authorized_source_manifest.json",
                root / "selection.json")
            self.assertEqual(result["status"], "human_selection_ready_for_candidate_build")

    def test_protected_source_or_suggestion_cell_change_is_rejected(self) -> None:
        with test_directory() as root:
            make_source(root)
            packet = prepare_selection_review(root, query_target=64)
            tables = copy.deepcopy(review_workbook_tables(packet))
            tables["查询复核"][1][6] = "tampered query text"
            workbook = root / "tampered.xlsx"
            write_review_xlsx(workbook, tables)
            with self.assertRaises(HumanSelectionWorkbookError) as raised:
                import_selection_review_workbook(packet, workbook)
            self.assertIn("protected_cell_changed:查询复核", str(raised.exception))

    def test_formula_in_review_cell_is_rejected(self) -> None:
        with test_directory() as root:
            make_source(root)
            packet = prepare_selection_review(root, query_target=64)
            workbook = root / "formula.xlsx"
            write_review_xlsx(workbook, review_workbook_tables(packet), formula_cell=("查询复核", 2, 12))
            with self.assertRaises(HumanSelectionWorkbookError) as raised:
                import_selection_review_workbook(packet, workbook)
            self.assertIn("review_cells_must_not_contain_formulas", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
