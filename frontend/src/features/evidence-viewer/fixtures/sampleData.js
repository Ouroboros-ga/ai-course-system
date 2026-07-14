/**
 * P1-04 — Sample fixture data for isolated development and testing.
 *
 * These fixtures provide realistic test data exercising:
 * - Normal active evidence with coordinates
 * - Stale evidence (version mismatch)
 * - Suspended evidence
 * - Multi-region highlights (multiple polygons per citation)
 * - Approximate coordinates (non-normalized space)
 * - Missing coordinate evidence
 * - Citations with different validation statuses
 *
 * RISK-02: Each fixture explicitly tests one or more edge cases for
 * coordinate/evidence mapping loss.
 *
 * All coordinates are in "normalized" space (0..1) unless otherwise noted.
 */

/**
 * A sample document with 5 pages of rendered slide images.
 */
export const SAMPLE_DOCUMENT = {
  documentId: 'doc_binary_tree_001',
  artifactId: 'art_binary_tree_pptx_001',
  title: '二叉树基础概念',
  totalPages: 5,
}

/**
 * Sample page image URLs (placeholder data URIs / colored squares for dev).
 * In production these would be served from the artifact store.
 */
export function createSamplePageUrls(totalPages = 5) {
  return Array.from({ length: totalPages }, (_, i) => {
    // Use a data URI with a simple colored rectangle for dev/demo
    const hue = (i * 47) % 360
    return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='600'%3E%3Crect width='800' height='600' fill='hsl(${hue}, 20%25, 95%25)'/%3E%3Ctext x='400' y='300' text-anchor='middle' font-size='24' fill='%23666'%3EPage ${i + 1}%3C/text%3E%3C/svg%3E`
  })
}

/**
 * Sample citations with various validation states.
 */
export const SAMPLE_CITATIONS = [
  {
    key: 'cit_a1b2c3d4e5f6',
    statement: '二叉树的每个节点最多有两个子节点，分别称为左子节点和右子节点。',
    evidenceRef: 'ev_span_001',
    pageOrSlide: 1,
    confidence: 0.95,
    metadata: {
      bboxes: [
        { x0: 0.08, y0: 0.23, x1: 0.86, y1: 0.35, coordinate_space: 'normalized' },
      ],
    },
  },
  {
    key: 'cit_b2c3d4e5f6a7',
    statement: '满二叉树：所有叶子节点都在同一层，且每个非叶子节点都有两个子节点。',
    evidenceRef: 'ev_span_002',
    pageOrSlide: 2,
    confidence: 0.88,
    metadata: {
      bboxes: [
        { x0: 0.05, y0: 0.15, x1: 0.90, y1: 0.28, coordinate_space: 'normalized' },
        { x0: 0.05, y0: 0.35, x1: 0.70, y1: 0.45, coordinate_space: 'normalized' },
      ],
    },
  },
  {
    key: 'cit_c3d4e5f6a7b8',
    statement: '完全二叉树：除最后一层外，每一层都被填满，且最后一层的节点都靠左对齐。',
    evidenceRef: 'ev_span_003',
    pageOrSlide: 2,
    confidence: 0.82,
    metadata: {
      bboxes: [
        { x0: 0.05, y0: 0.55, x1: 0.88, y1: 0.70, coordinate_space: 'normalized' },
      ],
    },
  },
  {
    key: 'cit_d4e5f6a7b8c9',
    statement: '二叉搜索树的性质：左子树所有节点的值均小于根节点，右子树所有节点的值均大于根节点。',
    evidenceRef: 'ev_span_004',
    pageOrSlide: 3,
    confidence: 0.91,
    metadata: {
      bboxes: [
        { x0: 0.10, y0: 0.10, x1: 0.85, y1: 0.22, coordinate_space: 'normalized' },
        { x0: 0.10, y0: 0.28, x1: 0.85, y1: 0.40, coordinate_space: 'normalized' },
        { x0: 0.10, y0: 0.46, x1: 0.60, y1: 0.55, coordinate_space: 'normalized' },
      ],
    },
  },
  {
    key: 'cit_e5f6a7b8c9d0',
    statement: '二叉树的遍历方式包括前序遍历、中序遍历和后序遍历。',
    evidenceRef: 'ev_span_005',
    pageOrSlide: 4,
    confidence: 0.93,
    metadata: {
      bboxes: [
        { x0: 0.15, y0: 0.18, x1: 0.80, y1: 0.30, coordinate_space: 'normalized' },
      ],
    },
  },
  // Stale citation (version mismatch)
  {
    key: 'cit_stale_001',
    statement: '树的深度优先搜索使用栈实现。',
    evidenceRef: 'ev_span_stale_001',
    pageOrSlide: 5,
    confidence: 0.70,
    metadata: {
      bboxes: [
        { x0: 0.10, y0: 0.20, x1: 0.75, y1: 0.33, coordinate_space: 'normalized' },
      ],
    },
  },
  // Citation without coordinate evidence (page-level only)
  {
    key: 'cit_no_coord_001',
    statement: '树的常见应用包括文件系统、HTML DOM 和路由协议。',
    evidenceRef: 'ev_span_no_coord_001',
    pageOrSlide: 5,
    confidence: 0.65,
    metadata: {
      bboxes: [],
    },
  },
  // Citation with NO_EVIDENCE status (abstain scenario)
  {
    key: null,
    statement: 'B树和B+树的区别在于...',
    evidenceRef: null,
    pageOrSlide: null,
    confidence: 0.0,
    metadata: {},
  },
]

/**
 * Sample evidence spans with various statuses.
 */
export const SAMPLE_EVIDENCE_SPANS = [
  // Active evidence on page 1
  {
    artifactId: 'art_binary_tree_pptx_001',
    documentId: 'doc_binary_tree_001',
    unitId: 'unit_slide_1',
    blockId: 'blk_def_001',
    versionRef: 'run_001_v1',
    pageOrSlide: 1,
    charStart: 0,
    charEnd: 38,
    textSnippet: '每个节点最多有两个子节点',
    score: 0.95,
    status: 'active',
    metadata: {
      bboxes: [
        { x0: 0.08, y0: 0.23, x1: 0.86, y1: 0.35, coordinate_space: 'normalized' },
      ],
    },
  },
  // Active evidence with polygon on page 2
  {
    artifactId: 'art_binary_tree_pptx_001',
    documentId: 'doc_binary_tree_001',
    unitId: 'unit_slide_2',
    blockId: 'blk_full_tree_001',
    versionRef: 'run_001_v1',
    pageOrSlide: 2,
    charStart: 0,
    charEnd: 45,
    textSnippet: '所有叶子节点都在同一层',
    score: 0.88,
    status: 'active',
    metadata: {
      bboxes: [
        { x0: 0.05, y0: 0.15, x1: 0.90, y1: 0.28, coordinate_space: 'normalized' },
        { x0: 0.05, y0: 0.35, x1: 0.70, y1: 0.45, coordinate_space: 'normalized' },
      ],
      polygons: [
        {
          points: [[0.05, 0.15], [0.90, 0.15], [0.90, 0.28], [0.05, 0.28]],
          coordinate_space: 'normalized',
        },
      ],
    },
  },
  // Active evidence with multi-region on page 3
  {
    artifactId: 'art_binary_tree_pptx_001',
    documentId: 'doc_binary_tree_001',
    unitId: 'unit_slide_3',
    blockId: 'blk_bst_props_001',
    versionRef: 'run_001_v1',
    pageOrSlide: 3,
    charStart: 0,
    charEnd: 52,
    textSnippet: '左子树所有节点的值均小于根节点',
    score: 0.91,
    status: 'active',
    metadata: {
      bboxes: [
        { x0: 0.10, y0: 0.10, x1: 0.85, y1: 0.22, coordinate_space: 'normalized' },
        { x0: 0.10, y0: 0.28, x1: 0.85, y1: 0.40, coordinate_space: 'normalized' },
        { x0: 0.10, y0: 0.46, x1: 0.60, y1: 0.55, coordinate_space: 'normalized' },
      ],
    },
  },
  // Active evidence on page 4
  {
    artifactId: 'art_binary_tree_pptx_001',
    documentId: 'doc_binary_tree_001',
    unitId: 'unit_slide_4',
    blockId: 'blk_traversal_001',
    versionRef: 'run_001_v1',
    pageOrSlide: 4,
    charStart: 0,
    charEnd: 35,
    textSnippet: '前序遍历、中序遍历和后序遍历',
    score: 0.93,
    status: 'active',
    metadata: {
      bboxes: [
        { x0: 0.15, y0: 0.18, x1: 0.80, y1: 0.30, coordinate_space: 'normalized' },
      ],
    },
  },
  // STALE evidence on page 5 (version mismatch)
  {
    artifactId: 'art_binary_tree_pptx_001',
    documentId: 'doc_binary_tree_001',
    unitId: 'unit_slide_5',
    blockId: 'blk_dfs_stale_001',
    versionRef: 'run_001_v1_old',
    pageOrSlide: 5,
    charStart: 0,
    charEnd: 28,
    textSnippet: '深度优先搜索使用栈实现',
    score: 0.70,
    status: 'stale',
    metadata: {
      bboxes: [
        { x0: 0.10, y0: 0.20, x1: 0.75, y1: 0.33, coordinate_space: 'normalized' },
      ],
    },
  },
  // Evidence without coordinates (missing bboxes)
  {
    artifactId: 'art_binary_tree_pptx_001',
    documentId: 'doc_binary_tree_001',
    unitId: 'unit_slide_5',
    blockId: 'blk_applications_001',
    versionRef: 'run_001_v1',
    pageOrSlide: 5,
    charStart: 0,
    charEnd: 30,
    textSnippet: '文件系统、HTML DOM 和路由协议',
    score: 0.65,
    status: 'active',
    metadata: {
      bboxes: [],
    },
  },
]

/**
 * Evidence that has been superseded (version mismatch) — used to test
 * RISK-02 stale detection.
 */
export const STALE_VERSION_EVIDENCE = {
  artifactId: 'art_binary_tree_pptx_001',
  documentId: 'doc_binary_tree_001',
  unitId: 'unit_slide_5',
  blockId: 'blk_dfs_stale_001',
  versionRef: 'run_001_v1_old',
  pageOrSlide: 5,
  textSnippet: '旧版本：深度优先搜索使用栈实现（已过期）',
  score: 0.50,
  status: 'stale',
  metadata: {
    bboxes: [
      { x0: 0.10, y0: 0.20, x1: 0.75, y1: 0.33, coordinate_space: 'normalized' },
    ],
  },
}

/**
 * Invalid coordinate data — used to test fail-closed behavior.
 */
export const INVALID_COORDINATE_EVIDENCE = {
  artifactId: 'art_binary_tree_pptx_001',
  documentId: 'doc_binary_tree_001',
  unitId: 'unit_slide_3',
  blockId: 'blk_invalid_coord_001',
  versionRef: 'run_001_v1',
  pageOrSlide: 3,
  textSnippet: '坐标数据已丢失或格式错误',
  score: 0.0,
  status: 'active',
  metadata: {
    bboxes: [
      { x0: -0.5, y0: 0.1, x1: 1.5, y1: 0.5, coordinate_space: 'normalized' }, // Out of bounds
    ],
  },
}

/**
 * Complete sample state for the dev page.
 */
export function createSampleViewerState() {
  return {
    documentId: SAMPLE_DOCUMENT.documentId,
    artifactId: SAMPLE_DOCUMENT.artifactId,
    totalPages: SAMPLE_DOCUMENT.totalPages,
    pageImageUrls: createSamplePageUrls(SAMPLE_DOCUMENT.totalPages),
    citations: SAMPLE_CITATIONS,
    evidenceSpans: SAMPLE_EVIDENCE_SPANS,
  }
}
