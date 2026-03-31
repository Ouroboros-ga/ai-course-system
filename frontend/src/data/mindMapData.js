// src/data/mindMapData.js
export const mindMapData = {
  // 根节点（中心）
  id: 'root',
  label: '知识图谱',
  color: '#4f46e5',          // 根节点颜色（深靛蓝）
  children: [
    // —— 一级子节点 —— //
    {
      id: 'tech-frontend',
      label: '前端技术',
      color: '#10b981',      // 一级节点颜色（翠绿）
      children: [
        { id: 'fe-vue',   label: 'Vue 3',   color: '#3b82f6' },
        { id: 'fe-react', label: 'React',   color: '#3b82f6' },
        { id: 'fe-svelte',label: 'Svelte',  color: '#3b82f6' }
      ]
    },
    {
      id: 'tech-backend',
      label: '后端技术',
      color: '#f59e0b',      // 一级节点颜色（琥珀）
      children: [
        { id: 'be-node', label: 'Node.js', color: '#ef4444' },
        { id: 'be-py',   label: 'Python',  color: '#ef4444' },
        { id: 'be-go',   label: 'Go',      color: '#ef4444' }
      ]
    },
    {
      id: 'tech-db',
      label: '数据库',
      color: '#ec4899',      // 一级节点颜色（玫瑰粉）
      children: [
        { id: 'db-mysql', label: 'MySQL', color: '#8b5cf6' },
        { id: 'db-mongo', label: 'MongoDB',color: '#8b5cf6' },
        { id: 'db-redis', label: 'Redis',  color: '#8b5cf6' }
      ]
    }
  ]
};
