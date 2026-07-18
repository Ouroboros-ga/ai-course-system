<template>
  <main class="production-workspace">
    <header class="workspace-header">
      <div class="course-identity">
        <button class="back-button" type="button" aria-label="返回课程编辑" @click="goLegacy"><ArrowLeft :size="18" /></button>
        <div><p class="breadcrumb">教师空间 / 课程生产</p><h1>课程生产工作台 <span>课程 #{{ courseId }}</span></h1></div>
      </div>
      <div class="header-actions">
        <span class="save-state"><Cloud :size="16" />{{ saveState }}</span>
        <button type="button" class="secondary" @click="goMapping"><Waypoints :size="16" />知识映射</button>
        <button type="button" class="primary" @click="goLegacy"><ExternalLink :size="16" />打开原编辑器</button>
      </div>
    </header>

    <div class="workbench-grid">
      <nav class="pipeline" aria-label="课程生产步骤">
        <p class="pipeline-label">生产流程</p>
        <button v-for="step in steps" :key="step.id" type="button" :class="['pipeline-step', { active: activeStep === step.id }]" @click="activeStep = step.id">
          <component :is="step.icon" :size="17" /><span>{{ step.label }}</span><small :class="`state-${step.state}`">{{ step.stateLabel }}</small>
        </button>
      </nav>

      <section class="main-stage" aria-live="polite">
        <div class="stage-heading">
          <div><p class="eyebrow">当前步骤</p><h2>{{ currentStep.label }}</h2><p>{{ currentStep.description }}</p></div>
          <span class="status-chip" :class="`state-${currentStep.state}`">{{ currentStep.stateLabel }}</span>
        </div>

        <section v-if="activeStep === 'materials'" class="stage-panel">
          <FileUp :size="28" /><h3>沿用已验证的资料上传与解析流程</h3>
          <p>资料上传、Docling 解析和知识结构提取仍由现有课程编辑器负责。本工作台负责组织进度与质量检查，避免复制另一套上传协议。</p>
          <button type="button" class="primary" @click="goLegacy"><Upload :size="16" />去上传教学资料</button>
        </section>

        <section v-else-if="activeStep === 'script'" class="stage-panel wide-panel">
          <div class="split-heading"><div><h3>脚本版本</h3><p>保存快照后可在已有接口允许的范围内回滚。</p></div><button type="button" class="secondary" :disabled="snapshotLoading" @click="createSnapshot"><Save :size="16" />{{ snapshotLoading ? '保存中…' : '创建快照' }}</button></div>
          <div v-if="versionsLoading" class="empty-state"><LoaderCircle class="spin" :size="20" />正在读取脚本版本…</div>
          <div v-else-if="versionsError" class="error-state"><AlertTriangle :size="18" /><span>{{ versionsError }}</span><button type="button" @click="loadVersions">重试</button></div>
          <ol v-else-if="versions.length" class="version-list"><li v-for="version in versions" :key="version.id || version.script_id"><span><strong>{{ version.version_name || version.name || '未命名快照' }}</strong><small>{{ version.created_at || '时间未知' }}</small></span><span v-if="version.is_active" class="status-chip state-complete">当前使用</span></li></ol>
          <div v-else class="empty-state">尚无脚本快照。创建快照后可在原编辑器中查看和回滚。</div>
        </section>

        <section v-else-if="activeStep === 'mapping'" class="stage-panel wide-panel">
          <Waypoints :size="28" /><h3>知识点—PPT 映射治理</h3><p>使用已存在的 Mapping API 管理知识点与 PPT 页码范围。Evidence 与知识图谱审核尚未接入，因此不会用静态数据伪装为可用功能。</p>
          <button type="button" class="primary" @click="goMapping"><ArrowRight :size="16" />进入映射工作区</button>
        </section>

        <section v-else-if="activeStep === 'ppt'" class="stage-panel wide-panel">
          <Presentation :size="28" /><h3>生成课程 PPT</h3><p>复用现有 PPT 生成对话框。生成完成后回到本工作台进行映射检查。</p>
          <button type="button" class="primary" @click="showPptDialog = true"><Sparkles :size="16" />生成 PPT</button>
          <p class="integration-note"><Info :size="16" />现有异步 PPT 创建接口只返回课程 ID，未返回可轮询的任务 ID；因此本页不会要求教师手动填入 sid。同步生成完成后会直接提示进入下一步。</p>
        </section>

        <section v-else-if="activeStep === 'audio'" class="stage-panel wide-panel">
          <Volume2 :size="28" /><h3>课程音频状态</h3><p>工作台会持续读取课程级 TTS 状态。当前后端没有独立的课程级 TTS 重试接口，失败后可返回原编辑器重新发起。</p>
          <button type="button" class="secondary" @click="goLegacy">在原编辑器生成音频 <ExternalLink :size="16" /></button>
        </section>

        <section v-else-if="activeStep === 'avatar'" class="stage-panel wide-panel">
          <Video :size="28" /><h3>课程数字人视频</h3><p>在右侧任务面板提交或恢复数字人视频任务。任务提交后可以离开本页，重新进入会从课程任务列表读取状态。</p>
        </section>

        <section v-else class="stage-panel">
          <component :is="currentStep.icon" :size="28" /><h3>{{ currentStep.legacyTitle }}</h3><p>{{ currentStep.legacyDescription }}</p><button type="button" class="secondary" @click="goLegacy">在原编辑器中处理 <ExternalLink :size="16" /></button>
        </section>
      </section>

      <aside class="quality-panel" aria-label="质量检查与任务状态">
        <div class="quality-title"><ShieldCheck :size="18" /><h2>发布检查</h2></div>
        <ul class="checklist"><li v-for="item in checks" :key="item.label"><component :is="item.ok ? CheckCircle2 : CircleDashed" :size="17" :class="item.ok ? 'ok' : 'pending'" /><span>{{ item.label }}</span><small>{{ item.note }}</small></li></ul>
        <div class="notice"><Info :size="17" /><p>“已生成”不等于“已确认”。教师需要在对应步骤检查后再发布。</p></div>
        <CourseTaskPanel :course-id="courseId" :show-video-generation="activeStep === 'avatar'" @open-legacy="goLegacy" @summary="handleTaskSummary" />
      </aside>
    </div>
    <PPTGenerationDialog v-model:visible="showPptDialog" :course-id="courseId" @generated="onPptGenerated" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, CircleDashed, Cloud, ExternalLink, FileCheck2, FileText, FileUp, Info, LoaderCircle, Presentation, Save, ShieldCheck, Sparkles, Upload, Waypoints, Volume2, Video } from 'lucide-vue-next'
import PPTGenerationDialog from '@/components/profile/LoginIn/courses/PPTGenerationDialog.vue'
import { createScriptSnapshot, getScriptVersions } from '@/api/script_editor.js'
import CourseTaskPanel from '@/features/teacher-workspace/components/CourseTaskPanel.vue'
import { showToast } from '@/utils/toast.js'

const route = useRoute(); const router = useRouter(); const courseId = computed(() => route.params.courseId)
const activeStep = ref('materials'); const showPptDialog = ref(false); const versions = ref([]); const versionsLoading = ref(false); const versionsError = ref(''); const snapshotLoading = ref(false); const taskSummary = ref({ total: 0, running: 0, blocking: 0, review: 0 }); const saveState = ref('工作区已就绪')
const steps = [
  { id:'materials', label:'教学资料', icon:FileUp, state:'complete', stateLabel:'已接入', description:'上传并解析资料，建立课程原始输入。', legacyTitle:'教学资料', legacyDescription:'已有上传和解析模块保持不变。' },
  { id:'structure', label:'课程结构', icon:FileText, state:'review', stateLabel:'待检查', description:'检查解析后的章节与知识点结构。', legacyTitle:'课程结构检查', legacyDescription:'请在原编辑器中选择和编辑知识节点。' },
  { id:'script', label:'教学脚本', icon:FileCheck2, state:'review', stateLabel:'待检查', description:'以版本快照保护教师修改。', legacyTitle:'教学脚本', legacyDescription:'当前可查询、创建快照；脚本正文仍由现有编辑器管理。' },
  { id:'ppt', label:'PPT 课件', icon:Presentation, state:'ready', stateLabel:'可生成', description:'生成并检查课程 PPT。', legacyTitle:'PPT 课件', legacyDescription:'请通过原编辑器访问更多模板设置。' },
  { id:'mapping', label:'知识映射', icon:Waypoints, state:'ready', stateLabel:'可治理', description:'审核知识点与 PPT 页面范围。', legacyTitle:'知识映射', legacyDescription:'映射治理已迁移到独立工作区。' },
  { id:'audio', label:'音频生成', icon:Volume2, state:'pending', stateLabel:'查看状态', description:'在脚本确认后生成音频。', legacyTitle:'音频生成', legacyDescription:'批量 TTS 任务仍由现有编辑器发起。' },
  { id:'avatar', label:'数字人生成', icon:Video, state:'pending', stateLabel:'查看状态', description:'在音频与映射确认后生成数字人内容。', legacyTitle:'数字人生成', legacyDescription:'数字人生成与资产配置仍在原编辑器。' },
]
const currentStep = computed(() => steps.find(step => step.id === activeStep.value) || steps[0])
const checks = computed(() => [{label:'教学资料已解析',note:'现有流程',ok:true},{label:'脚本版本已保存',note:versions.value.length ? `${versions.value.length} 个版本` : '待确认',ok:versions.value.length>0},{label:'知识点与 PPT 映射已检查',note:'教师确认后可发布',ok:false},{label:'生成任务无阻断项',note:taskSummary.value.blocking ? `${taskSummary.value.blocking} 个任务需要恢复` : taskSummary.value.running ? `${taskSummary.value.running} 个任务仍在执行` : '按需生成',ok:taskSummary.value.blocking===0 && taskSummary.value.running===0}])
function goLegacy(){ router.push(`/teacher/course/${courseId.value}`) } function goMapping(){ router.push(`/teacher/course/${courseId.value}/mapping`) }
async function loadVersions(){versionsLoading.value=true;versionsError.value='';try{const result=await getScriptVersions(courseId.value);versions.value=Array.isArray(result)?result:(result?.versions||result?.items||[])}catch{versionsError.value='脚本版本暂时无法读取，请检查网络或在原编辑器中重试。'}finally{versionsLoading.value=false}}
async function createSnapshot(){snapshotLoading.value=true;try{await createScriptSnapshot(courseId.value);showToast('脚本快照已创建','success');await loadVersions()}catch{showToast('创建脚本快照失败，请稍后重试','error')}finally{snapshotLoading.value=false}}
function handleTaskSummary(summary){taskSummary.value=summary;saveState.value=summary.running ? `有 ${summary.running} 个后台任务正在执行` : summary.blocking ? `${summary.blocking} 个后台任务需要恢复` : '课程任务已同步'} function onPptGenerated(){showPptDialog.value=false;saveState.value='PPT 已生成，建议进入映射检查'}
onMounted(loadVersions)
</script>

<style scoped>
.production-workspace{min-height:100dvh;background:#f5f7fa;color:#1e293b}.workspace-header{min-height:64px;padding:0 24px;background:#fff;border-bottom:1px solid #d9e1ea;display:flex;align-items:center;justify-content:space-between;gap:18px}.course-identity,.header-actions{display:flex;align-items:center;gap:12px}.back-button{width:40px;height:40px;border:1px solid #d9e1ea;border-radius:9px;background:#fff;color:#334155;display:grid;place-items:center;cursor:pointer}.breadcrumb,.eyebrow{margin:0;color:#64748b;font-size:12px}.workspace-header h1{font-size:18px;margin:3px 0 0}.workspace-header h1 span{font-weight:400;color:#64748b;font-size:13px}.save-state{color:#475569;font-size:13px;display:inline-flex;gap:6px;align-items:center}.primary,.secondary{min-height:38px;border-radius:8px;padding:0 12px;display:inline-flex;align-items:center;justify-content:center;gap:7px;cursor:pointer;font-size:13px;font-weight:600}.primary{background:#1769aa;border:1px solid #1769aa;color:#fff}.secondary{background:#fff;border:1px solid #cbd5e1;color:#334155}.workbench-grid{display:grid;grid-template-columns:220px minmax(0,1fr) 310px;gap:16px;padding:16px;max-width:1710px;margin:0 auto}.pipeline,.main-stage,.quality-panel{background:#fff;border:1px solid #d9e1ea;border-radius:12px}.pipeline{padding:12px;height:max-content}.pipeline-label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:5px 9px 9px}.pipeline-step{width:100%;border:0;background:transparent;border-radius:8px;padding:10px 9px;display:grid;grid-template-columns:20px 1fr auto;gap:8px;align-items:center;text-align:left;color:#334155;cursor:pointer;font-size:13px}.pipeline-step:hover{background:#f1f5f9}.pipeline-step.active{background:#e8f1f8;color:#0b5f97;font-weight:700}.pipeline-step small{font-size:11px}.state-complete{color:#15803d}.state-review{color:#a16207}.state-ready{color:#1769aa}.state-pending{color:#64748b}.main-stage{padding:24px;min-height:520px}.stage-heading,.split-heading{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-bottom:1px solid #e2e8f0;padding-bottom:18px}.stage-heading h2{margin:5px 0;font-size:22px}.stage-heading p{margin:0;color:#64748b;font-size:14px;line-height:1.55}.status-chip{padding:4px 8px;border-radius:999px;background:#f1f5f9;font-size:12px;font-weight:600;white-space:nowrap}.stage-panel{margin-top:28px;max-width:620px;min-height:270px;border:1px dashed #cbd5e1;border-radius:10px;padding:28px;display:flex;align-items:flex-start;justify-content:center;flex-direction:column;gap:12px;color:#475569}.stage-panel>svg{color:#1769aa}.stage-panel h3{color:#1e293b;margin:0;font-size:17px}.stage-panel p{margin:0;line-height:1.65;font-size:14px}.wide-panel{max-width:none;justify-content:flex-start}.integration-note{width:100%;box-sizing:border-box;margin:6px 0 0;padding:10px 12px;display:flex;gap:7px;align-items:flex-start;background:#f8fafc;border-left:3px solid #94a3b8;border-radius:6px;font-size:13px;line-height:1.55;color:#475569}.version-list{width:100%;list-style:none;padding:0;margin:4px 0 0;border-top:1px solid #e2e8f0}.version-list li{display:flex;justify-content:space-between;align-items:center;padding:13px 0;border-bottom:1px solid #e2e8f0}.version-list strong,.version-list small{display:block}.version-list small{font-size:12px;color:#64748b;margin-top:4px}.empty-state,.error-state{display:flex;align-items:center;justify-content:center;gap:8px;min-height:130px;color:#64748b;font-size:14px}.error-state{color:#b91c1c;justify-content:flex-start}.error-state button{border:0;background:none;color:#1769aa;text-decoration:underline;cursor:pointer}.spin{animation:spin 1s linear infinite}.quality-panel{padding:18px;height:max-content}.quality-title{display:flex;align-items:center;gap:8px;color:#1e3a5f}.quality-title h2{font-size:16px;margin:0}.checklist{list-style:none;padding:6px 0 0;margin:0}.checklist li{display:grid;grid-template-columns:18px 1fr;gap:8px;padding:13px 0;border-bottom:1px solid #edf2f7;font-size:13px}.checklist small{grid-column:2;color:#64748b;font-size:12px}.ok{color:#16a34a}.pending{color:#94a3b8}.notice{margin-top:16px;padding:12px;background:#eff6ff;border-radius:8px;color:#1e3a5f;display:flex;gap:8px;font-size:13px;line-height:1.5}.notice p{margin:0}@keyframes spin{to{transform:rotate(360deg)}}button:focus-visible{outline:3px solid #93c5fd;outline-offset:2px}@media(prefers-reduced-motion:reduce){.spin{animation:none}}@media(max-width:1180px){.workbench-grid{grid-template-columns:200px minmax(0,1fr)}.quality-panel{grid-column:2}.header-actions .save-state{display:none}}@media(max-width:860px){.workspace-header{padding:10px 14px;align-items:flex-start;flex-direction:column}.header-actions{width:100%;justify-content:flex-end}.workbench-grid{grid-template-columns:1fr;padding:10px}.pipeline{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px}.pipeline-label{grid-column:1/-1}.quality-panel{grid-column:auto}.main-stage{padding:18px}.stage-heading{flex-direction:column}.stage-panel{padding:20px}}@media(max-width:480px){.header-actions{justify-content:stretch;min-width:0}.header-actions button{flex:1;min-width:0;white-space:normal;line-height:1.25}.secondary{font-size:12px;padding:0 8px}.pipeline{grid-template-columns:1fr}.integration-note{font-size:12px}.stage-panel{min-height:230px}.course-identity{align-items:flex-start}.workspace-header h1{font-size:16px}}
</style>
