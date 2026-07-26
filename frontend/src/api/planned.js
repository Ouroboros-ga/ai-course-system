/**
 * Planned API 契约注册表（API 契约 §1.1：planned = 冻结的未来契约，当前未实现）。
 *
 * 纪律（§4 前端实施纪律）：
 * - planned 接口目前不存在，前端不得把它当作可用服务——本模块只登记契约元
 *   信息，绝不发起真实请求；
 * - 页面据此渲染「契约已冻结、待后端实现」的可解释空状态，不伪造数据；
 * - 一个 planned endpoint 实现并通过契约测试后，从这里移除并改为真实 API 模块。
 */
export const PLANNED_CONTRACTS = Object.freeze({
  'facade-home': {
    domain: '首页聚合',
    endpoints: ['GET /facade/home', 'GET /facade/home?mode=student|teacher'],
    summary: '聚合继续学习、我建设的课程、待处理审核、系统任务与最近活动，避免首页并发拼接十余个领域接口。',
  },
  'facade-courses': {
    domain: '课程列表门面',
    endpoints: ['GET /facade/courses?view=learning|building|hall'],
    summary: '统一「我学习的 / 我建设的 / 课程大厅」读模型；当前由 /document/** 历史接口适配。',
  },
  'course-build': {
    domain: '课程建设',
    endpoints: [
      'GET /facade/course/{id}/build',
      'GET/POST /course-build/{id}/materials',
      'GET/PUT /course-build/{id}/structure',
      'GET/PUT /course-build/{id}/scripts',
      'POST /course-build/{id}/validate',
      'GET/POST /course-build/{id}/releases',
    ],
    summary: '建设页七步读模型与受控写命令：资料、结构、讲稿、映射、媒体、校验、发布。',
  },
  'course-ingestion': {
    domain: '资料解析任务',
    endpoints: ['POST /graph/course/{id}/ingestions', 'POST /course-build/{id}/materials/{mid}/parse'],
    summary: '对课程材料创建 OCR / DocumentIR / Evidence / 候选图谱解析任务，返回 202 task_id。',
  },
  experiments: {
    domain: '课程实验',
    endpoints: [
      'GET/POST /experiments/course/{id}/definitions',
      'POST /experiments/{eid}/attempts',
      'POST /experiments/attempts/{aid}/runs',
      'POST /experiments/attempts/{aid}/finalize',
    ],
    summary: '实验定义、版本、尝试、分层运行结果与正式评分 Evidence；当前仅有沙箱运行能力。',
  },
  'join-requests': {
    domain: '加入申请',
    endpoints: [
      'POST /course-access/courses/{id}/join-requests',
      'GET /course-access/courses/{id}/join-requests',
      'POST /course-access/courses/{id}/join-requests/{rid}/approve|reject',
    ],
    summary: '无邀请码时的申请审核状态机；当前仅支持邀请码直接加入。',
  },
  'course-groups': {
    domain: '课程分组',
    endpoints: ['GET/POST/PUT/DELETE /course-groups/course/{id}/groups'],
    summary: '班级/小组/实验分组；分组不改变课程角色，删除分组不删除成员。',
  },
  'course-settings': {
    domain: '课程设置写模型',
    endpoints: [
      'GET /facade/course/{id}/settings',
      'PUT /course-settings/course/{id}/profile',
      'PUT /course-settings/course/{id}/agent-policy',
    ],
    summary: '基础信息、智能体策略的聚合读写；当前仅安全/沙箱策略有真实端点。',
  },
  resources: {
    domain: '资源库',
    endpoints: [
      'GET /resources/files?scope=mine|course|recent|trash',
      'POST /resources/files',
      'PATCH /resources/files/{rid}',
      'POST /resources/files/{rid}/references',
      'DELETE /resources/files/{rid}',
    ],
    summary: '通用文件资源库：上传、标签、引用到课程、软删除与回收站；删除返回下游影响。',
  },
  tasks: {
    domain: '任务中心',
    endpoints: [
      'GET /tasks?view=todo|created|system|completed',
      'GET /tasks/{task_id}',
      'POST /tasks/{task_id}/cancel|retry|acknowledge',
    ],
    summary: '统一承载 OCR、导入、图谱构建、媒体生成、实验运行、外部同步等长任务。',
  },
  lab: {
    domain: '平台实验室',
    endpoints: ['GET /lab/catalog', 'GET /lab/course-tasks', 'GET /lab/my-experiments', 'GET /lab/records'],
    summary: '自主实验目录、课程任务聚合、我的实验与学习记录；当前仅有课程内沙箱运行能力。',
  },
  'fanya-sync': {
    domain: '泛雅同步',
    endpoints: ['POST /integrations/fanya/course/{id}/sync'],
    summary: '显式异步同步，禁止静默覆盖本地成员关系；同步前必须预览变化。',
  },
})

/** 取某个 planned 域的契约说明（不存在时返回通用说明）。 */
export function getPlannedContract(key) {
  return PLANNED_CONTRACTS[key] ?? {
    domain: key,
    endpoints: [],
    summary: '该能力的接口契约已冻结，等待后端实现后接入。',
  }
}
