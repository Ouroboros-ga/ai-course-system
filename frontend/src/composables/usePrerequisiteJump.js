import { ref, computed } from 'vue'
import request from '@/utils/request.js'

export function usePrerequisiteJump() {
  const isAnalyzing = ref(false)
  const showJumpDialog = ref(false)
  const jumpAnalysisResult = ref(null)
  const currentJumpStack = ref([])
  const isJumping = ref(false)
  const currentJumpId = ref(null)
  const originalPosition = ref(null)

  const hasActiveJumps = computed(() => currentJumpStack.value.length > 0)
  const currentDepth = computed(() => {
    if (currentJumpStack.value.length === 0) return 0
    return Math.max(...currentJumpStack.value.map(j => j.depth))
  })

  async function analyzePrerequisiteGaps(params) {
    isAnalyzing.value = true
    try {
      const data = await request({
        url: '/prerequisite/analyze-gap',
        method: 'post',
        data: {
          courseId: params.courseId,
          currentNodeId: params.currentNodeId,
          question: params.question,
          conversationHistory: params.conversationHistory || [],
        },
      })
      
      if (data.hasGaps && data.weakPrerequisites?.length > 0) {
        jumpAnalysisResult.value = data
        showJumpDialog.value = true
        return { shouldShowDialog: true, analysis: data }
      }
      
      return { shouldShowDialog: false, analysis: data }
    } catch (error) {
      console.error('[前置知识分析失败]', error)
      return { shouldShowDialog: false, error }
    } finally {
      isAnalyzing.value = false
    }
  }

  async function executeJumpToPrerequisite(params) {
    isJumping.value = true
    try {
      const data = await request({
        url: '/prerequisite/jump',
        method: 'post',
        data: {
          courseId: params.courseId,
          fromNodeId: params.fromNodeId,
          fromNodeTitle: params.fromNodeTitle,
          fromNodeIndex: params.fromNodeIndex,
          toPrerequisiteId: params.toPrerequisiteId,
          toNodeTitle: params.toNodeTitle,
          toNodeIndex: params.toNodeIndex,
          triggerQuestion: params.triggerQuestion || '',
          analysisResult: params.analysisResult || null,
          gapDescription: params.gapDescription || '',
          confidenceScore: params.confidenceScore || 0.8,
          urgencyLevel: params.urgencyLevel || 'medium',
          parentJumpId: params.parentJumpId || null,
        },
      })
      
      if (data.success) {
        currentJumpId.value = data.jumpId
        originalPosition.value = {
          nodeId: params.fromNodeId,
          nodeIndex: params.fromNodeIndex,
          nodeTitle: params.fromNodeTitle,
        }
        
        await loadCurrentJumpStack(params.courseId)
        
        return {
          success: true,
          jumpId: data.jumpId,
          targetNodeIndex: params.toNodeIndex,
          targetNodeId: params.toPrerequisiteId,
          sessionId: data.sessionId,
          depth: data.jumpDepth,
        }
      }
      
      return { success: false }
    } catch (error) {
      console.error('[执行跳转失败]', error)
      return { success: false, error }
    } finally {
      isJumping.value = false
      showJumpDialog.value = false
    }
  }

  async function returnToOriginalPosition(jumpId, reviewDurationSeconds = 0) {
    try {
      const data = await request({
        url: '/prerequisite/return',
        method: 'post',
        data: {
          jumpId,
          reviewDurationSeconds,
        },
      })
      
      if (data.success && data.originalNode) {
        currentJumpId.value = null
        
        if (currentJumpStack.value.length > 0) {
          currentJumpStack.value = currentJumpStack.value.filter(j => j.id !== jumpId)
        }
        
        return {
          success: true,
          originalNode: data.originalNode,
          reviewSummary: data.reviewSummary,
        }
      }
      
      return { success: false }
    } catch (error) {
      console.error('[返回原位置失败]', error)
      return { success: false, error }
    }
  }

  async function loadCurrentJumpStack(courseId) {
    try {
      const data = await request({
        url: '/prerequisite/jump-stack',
        method: 'get',
        params: {
          courseId,
          includeReturned: false,
        },
      })
      
      currentJumpStack.value = data.stack || []
      return data
    } catch (error) {
      console.error('[加载跳转栈失败]', error)
      return { stack: [] }
    }
  }

  async function markReviewCompleted(jumpId) {
    try {
      const data = await request({
        url: '/prerequisite/mark-reviewed',
        method: 'post',
        data: { jumpId },
      })
      
      return data
    } catch (error) {
      console.error('[标记复习完成失败]', error)
      return { success: false }
    }
  }

  async function getLearningPathData(courseId) {
    try {
      const data = await request({
        url: '/prerequisite/learning-path',
        method: 'get',
        params: { courseId },
      })
      
      return data
    } catch (error) {
      console.error('[获取学习路径数据失败]', error)
      return { nodes: [], edges: [], currentPath: [] }
    }
  }

  function dismissDialog() {
    showJumpDialog.value = false
    jumpAnalysisResult.value = null
  }

  function resetState() {
    showJumpDialog.value = false
    jumpAnalysisResult.value = null
    currentJumpStack.value = []
    currentJumpId.value = null
    originalPosition.value = null
    isJumping.value = false
    isAnalyzing.value = false
  }

  return {
    state: {
      isAnalyzing,
      showJumpDialog,
      jumpAnalysisResult,
      currentJumpStack,
      isJumping,
      currentJumpId,
      originalPosition,
    },
    computed: {
      hasActiveJumps,
      currentDepth,
    },
    actions: {
      analyzePrerequisiteGaps,
      executeJumpToPrerequisite,
      returnToOriginalPosition,
      loadCurrentJumpStack,
      markReviewCompleted,
      getLearningPathData,
      dismissDialog,
      resetState,
    },
  }
}