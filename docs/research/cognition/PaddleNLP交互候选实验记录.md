# PaddleNLP 交互候选实验记录（已退役）

> 状态：RETIRED。该候选实验已从研究可执行路径移除，不安装、不接入
> Paddle/PaddleNLP，也不作为任何正式或 Shadow 算法的依赖。
>
> 退役原因：Python 版本与运行时兼容成本不合理，且本地 `uie-mini` 对
> 教学语义样例没有产生可用召回。以下内容仅保留审计价值，不能作为
> 当前能力或未来接入依据。

## 结论

历史结论曾将 PaddleNLP 定位为离线候选标签器；该结论已退役。它不提供现成的“八维学生认知诊断 + 知识图谱学习路径推荐”产品算法，也不能直接给正式 `mastery` 或推荐排序。

历史上曾新增研究适配器（现已删除）：

```text
research/product1_cognition/experimental_providers/
  paddlenlp_uie_interaction_candidate.py
```

它的输出是 `confusion_risk`、`inquiry_depth`、`hint_dependency`、`explanation_need` 的候选标签、每标签置信度、原文证据片段、模型版本和策略版本。输出仍须经过 KG-MEST 的标签阈值、独立性、冲突与窗口规则。

## 实际运行证据

独立环境：

```text
Python      3.12.13
Paddle      3.0.0
PaddleNLP   3.0.0b4
模型         本地 uie-mini
设备         CPU
```

使用本地模型目录和本地缓存重定向后，`Taskflow('information_extraction', model='uie-mini')` 可离线加载和执行；未下载模型，也未访问生产服务。

对示例“我仍然不明白二分查找，给一点提示”使用当前通用 UIE‑mini 和教学 schema，输出为四类标签全部 `false`、置信度均 `0.0`。因此当前结论是：**运行链路可用，但该零样本模型没有显示出可用的教学语义召回**。

这比把空输出包装成“AI 已理解学生困惑”更有价值：它证明需要评测，不能把展会中的通用信息抽取演示直接接为认知算法。

## 硬门禁

1. 适配器已删除；主应用和研究依赖清单均不安装 Paddle/PaddleNLP。
2. 本地模型目录不存在时适配器明确拒绝，禁止静默下载。
3. 任一标签低于 `0.70` 不进入交互状态；高置信标签不能替低置信标签背书。
4. 所有 UIE 标签都不能改变 `observed_performance_score`。
5. 进入 Shadow 前需要假名化人工金标、类别级 precision/recall、混淆案例、课程隔离和失败降级方案。

## 建议的下一项实验

构建一组人工审核的假名化对话金标，至少分别覆盖：明确困惑、概念追问、提示请求、解释后仍困惑、正常提问与无关文本。比较：规则基线、UIE 零样本、UIE 受监督微调/结构 schema。没有这些数据前，不比较“模型好坏”，更不影响学生状态或推荐。
