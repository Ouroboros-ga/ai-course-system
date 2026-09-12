// 知识图谱节点类型的中文词表。
// 画布聚类标题、学生端节点列表与节点详情共用同一份映射，
// 避免后端英文枚举（concept / knowledge_point / …）直接外露给学生。
export const NODE_TYPE_LABELS = {
  concept: '概念',
  knowledge_point: '知识点',
  skill: '技能',
  topic: '主题',
  chapter: '章节',
  section: '小节',
  method: '方法',
  principle: '原理',
  formula: '公式',
  example: '示例',
  definition: '定义',
  theorem: '定理',
  algorithm: '算法',
  procedure: '流程',
  assessment: '考核',
  default: '节点',
}

export function nodeTypeLabel(type) {
  return NODE_TYPE_LABELS[String(type || '').toLowerCase()] || NODE_TYPE_LABELS.default
}
