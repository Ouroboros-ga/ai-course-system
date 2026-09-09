# nexus-document-renderer：独立文档渲染配置（F6）

> 状态：配置与版本锁定已交付，**未构建、未部署**。TeX/ Pandoc 不进入主应用
> 环境（Nexus Runtime / Backend venv 零新增依赖）；实际渲染任务在隔离环境
> 执行，见下。

## 固定版本（构建时按摘要锁定）

- pandoc 3.x（`--from markdown --to docx|latex --standalone`，禁 filter/宏）
- TeX Live 2024（`latexmk` 编排多轮＋引用解析，回退单遍 xelatex；禁 shell-escape）
- 字体：Noto Serif CJK SC / Noto Sans CJK SC（中英混排）
- 模板：内置 `reference.docx`（minimal/1）与 `ctexart-xelatex/1`（见
  `templates/`）；任意期刊模板不在本批范围

## 隔离要求（任务执行面）

- 无外网、无生产密钥、无宿主业务挂载；只读本次授权资源＋可信模板
- Pandoc/TeX 参数由平台控制；`--filter`、自定义 lua filter、`\write18`、
  任意宏包一律拒绝；输入路径限定任务工作区（`..` 拒绝）
- 资源限制：CPU/内存上限＋单作业超时（默认渲染 60s、编译 180s）

## 回退

渲染器不可用时 Runtime 回退标准库实现并如实记录 `engine=stdlib/1`
（数学为可编辑文本 run，非 OMML）；页面只展示实际交付状态。
