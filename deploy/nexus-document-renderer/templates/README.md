# 可信模板清单（F6 首批三模板；版本见代码 DOCUMENT_TEMPLATES）

- `reference.docx`（builtin-minimal/1）：标题/正文/列表/表格/代码样式；
  实际文件在渲染器构建时生成并锁定哈希，本目录只保留版本声明。
- `ctexart-xelatex/1`：`\documentclass[UTF8]{ctexart}` ＋
  listings/xcolor/hyperref/longtable（见 document_output.py 模板头）；
  编译器固定 xelatex，禁 shell-escape。
- bibliography/图片：受控清单制（冻结快照 inventory 引用），任意外部
  URL 不得进入编译输入。
