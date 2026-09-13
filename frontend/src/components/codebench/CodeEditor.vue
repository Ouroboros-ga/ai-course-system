<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorState, StateEffect } from '@codemirror/state'
import {
  EditorView,
  keymap,
  lineNumbers as lineNumbersExtension,
  highlightActiveLine,
  highlightActiveLineGutter,
} from '@codemirror/view'
import { defaultKeymap, indentWithTab, history, historyKeymap } from '@codemirror/commands'
import { bracketMatching, indentOnInput, foldGutter, foldKeymap } from '@codemirror/language'
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search'
import { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { cpp } from '@codemirror/lang-cpp'
import { java } from '@codemirror/lang-java'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  readonly: { type: Boolean, default: false },
  lineNumbers: { type: Boolean, default: true },
  placeholder: { type: String, default: '' },
  editable: { type: Boolean, default: true },
  /** 编辑器配色：`dark`（默认，design.md §1.6「深色孤岛」）｜`light`（浅色，OJ 题目详情页用） */
  theme: {
    type: String,
    default: 'dark',
    validator: (value) => ['dark', 'light'].includes(value),
  },
})

const emit = defineEmits(['update:modelValue', 'ready', 'run-shortcut'])

const editorRef = ref(null)
let view = null

// 语言映射
const languageMap = {
  python: () => python(),
  python3: () => python(),
  javascript: () => javascript(),
  js: () => javascript(),
  typescript: () => javascript({ typescript: true }),
  cpp: () => cpp(),
  'c++': () => cpp(),
  c: () => cpp(),
  java: () => java(),
}

// ── 编辑器配色 ──────────────────────────────────────────────
// 深色（现行默认）：走 --code-* 令牌 = design.md §1.6「深色孤岛」。
const darkSurface = EditorView.theme({
  '&': {
    backgroundColor: 'var(--code-bg)',
    color: 'var(--code-text)',
    fontSize: 'var(--code-size)',
    fontFamily: 'var(--font-mono)',
    lineHeight: 'var(--code-line)',
    height: '100%',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: 'var(--font-mono)',
  },
  '.cm-content': {
    caretColor: 'var(--code-text)',
    padding: 'var(--space-3) 0',
  },
  '.cm-cursor': {
    borderLeftColor: 'var(--code-text)',
    borderLeftWidth: '2px',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--code-bg)',
    color: 'var(--code-muted)',
    border: 'none',
    borderRight: '1px solid var(--code-border)',
    userSelect: 'none',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'rgba(255, 255, 255, 0.04)',
    color: 'var(--code-text)',
  },
  '.cm-activeLine': {
    backgroundColor: 'rgba(255, 255, 255, 0.03)',
  },
  '.cm-selectionBackground, ::selection': {
    backgroundColor: 'rgba(53, 92, 125, 0.4) !important',
  },
  '.cm-foldPlaceholder': {
    backgroundColor: 'var(--code-panel)',
    border: '1px solid var(--code-border)',
    borderRadius: '4px',
    color: 'var(--code-muted)',
  },
  '.cm-tooltip': {
    backgroundColor: 'var(--code-panel)',
    border: '1px solid var(--code-border)',
    color: 'var(--code-text)',
    borderRadius: '6px',
  },
  '.cm-tooltip-autocomplete': {
    '& > ul > li[aria-selected]': {
      backgroundColor: 'rgba(53, 92, 125, 0.4)',
      color: 'var(--code-text)',
    },
  },
  '.cm-panels': {
    backgroundColor: 'var(--code-panel)',
    color: 'var(--code-text)',
  },
  '.cm-panels.cm-panels-top': {
    borderBottom: '1px solid var(--code-border)',
  },
  '.cm-panels.cm-panels-bottom': {
    borderTop: '1px solid var(--code-border)',
  },
  '.cm-searchMatch': {
    backgroundColor: 'rgba(198, 139, 44, 0.3)',
    outline: '1px solid var(--amber-500)',
  },
  '.cm-searchMatch.cm-searchMatch-selected': {
    backgroundColor: 'rgba(198, 139, 44, 0.5)',
  },
  '.cm-highlightSelectionMatch': {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  },
}, { dark: true })

// One Dark 系配色（深色底上的现行取色）
const darkTokens = EditorView.theme({
  '.cm-keyword': { color: '#C678DD' },
  '.cm-string': { color: '#98C379' },
  '.cm-string-2': { color: '#98C379' },
  '.cm-number': { color: '#D19A66' },
  '.cm-comment': { color: 'var(--code-muted)', fontStyle: 'italic' },
  '.cm-function': { color: '#61AFEF' },
  '.cm-functionName': { color: '#61AFEF' },
  '.cm-variableName': { color: '#E06C75' },
  '.cm-type': { color: '#E5C07B' },
  '.cm-operator': { color: '#56B6C2' },
  '.cm-punctuation': { color: 'var(--code-text)' },
  '.cm-meta': { color: '#E5C07B' },
  '.cm-attribute': { color: '#E5C07B' },
  '.cm-tag': { color: '#E06C75' },
  '.cm-property': { color: '#61AFEF' },
  '.cm-qualifier': { color: '#E5C07B' },
  '.cm-atom': { color: '#D19A66' },
  '.cm-builtin': { color: '#E5C07B' },
  '.cm-def': { color: '#61AFEF' },
  '.cm-variable-2': { color: '#61AFEF' },
  '.cm-variable-3': { color: '#E5C07B' },
  '.cm-link': { color: '#61AFEF' },
  '.cm-hr': { color: 'var(--code-muted)' },
}, { dark: true })

// ── 浅色（OJ 题目详情页，对齐洛谷：白底黑字 + One Light 配色）────────
// ⚠️ 这里**硬编码**浅色值、不走 var(--code-*)：<CodeEditor theme="light"> 必须自洽，
// 不能依赖外层容器记得覆盖令牌 —— 依赖外层就会出现「编辑器浅了、工具栏还是深的」
// 的半吊子状态（周边 UI 的浅色由 CodeWorkbench 根上的 .code-surface--light 负责）。
const lightSurface = EditorView.theme({
  '&': {
    backgroundColor: '#FBFBFC',
    color: '#24292F',
    fontSize: 'var(--code-size)',
    fontFamily: 'var(--font-mono)',
    lineHeight: 'var(--code-line)',
    height: '100%',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: 'var(--font-mono)',
  },
  '.cm-content': {
    caretColor: '#24292F',
    padding: 'var(--space-3) 0',
  },
  '.cm-cursor': {
    borderLeftColor: '#24292F',
    borderLeftWidth: '2px',
  },
  '.cm-gutters': {
    backgroundColor: '#F6F8FA',
    color: '#8B949E',
    border: 'none',
    borderRight: '1px solid #E3E6EA',
    userSelect: 'none',
  },
  '.cm-activeLineGutter': {
    backgroundColor: '#EDEFF2',
    color: '#24292F',
  },
  '.cm-activeLine': {
    backgroundColor: '#F3F4F6',
  },
  '.cm-selectionBackground, ::selection': {
    backgroundColor: 'rgba(9, 105, 218, 0.14) !important',
  },
  '.cm-foldPlaceholder': {
    backgroundColor: '#F6F8FA',
    border: '1px solid #E3E6EA',
    borderRadius: '4px',
    color: '#8B949E',
  },
  '.cm-tooltip': {
    backgroundColor: '#FFFFFF',
    border: '1px solid #E3E6EA',
    color: '#24292F',
    borderRadius: '6px',
    boxShadow: '0 6px 20px rgba(16, 24, 32, 0.10)',
  },
  '.cm-tooltip-autocomplete': {
    '& > ul > li[aria-selected]': {
      backgroundColor: 'rgba(9, 105, 218, 0.12)',
      color: '#24292F',
    },
  },
  '.cm-panels': {
    backgroundColor: '#F6F8FA',
    color: '#24292F',
  },
  '.cm-panels.cm-panels-top': {
    borderBottom: '1px solid #E3E6EA',
  },
  '.cm-panels.cm-panels-bottom': {
    borderTop: '1px solid #E3E6EA',
  },
  '.cm-searchMatch': {
    backgroundColor: 'rgba(154, 106, 0, 0.18)',
    outline: '1px solid #B5892B',
  },
  '.cm-searchMatch.cm-searchMatch-selected': {
    backgroundColor: 'rgba(154, 106, 0, 0.32)',
  },
  '.cm-highlightSelectionMatch': {
    backgroundColor: 'rgba(9, 105, 218, 0.10)',
  },
}, { dark: false })

// One Light 系配色（浅色底上对比度足够，观感接近洛谷的默认高亮）
const lightTokens = EditorView.theme({
  '.cm-keyword': { color: '#A626A4' },
  '.cm-string': { color: '#50A14F' },
  '.cm-string-2': { color: '#50A14F' },
  '.cm-number': { color: '#986801' },
  '.cm-comment': { color: '#8B949E', fontStyle: 'italic' },
  '.cm-function': { color: '#4078F2' },
  '.cm-functionName': { color: '#4078F2' },
  '.cm-variableName': { color: '#E45649' },
  '.cm-type': { color: '#C18401' },
  '.cm-operator': { color: '#0184BC' },
  '.cm-punctuation': { color: '#383A42' },
  '.cm-meta': { color: '#C18401' },
  '.cm-attribute': { color: '#986801' },
  '.cm-tag': { color: '#E45649' },
  '.cm-property': { color: '#4078F2' },
  '.cm-qualifier': { color: '#C18401' },
  '.cm-atom': { color: '#986801' },
  '.cm-builtin': { color: '#C18401' },
  '.cm-def': { color: '#4078F2' },
  '.cm-variable-2': { color: '#383A42' },
  '.cm-variable-3': { color: '#C18401' },
  '.cm-link': { color: '#0184BC' },
  '.cm-hr': { color: '#C8CDD4' },
}, { dark: false })

function surfaceTheme(name) {
  return name === 'light' ? lightSurface : darkSurface
}

function tokenTheme(name) {
  return name === 'light' ? lightTokens : darkTokens
}

// 运行快捷键
const runKeymap = keymap.of([
  {
    key: 'Ctrl-Enter',
    run: () => {
      emit('run-shortcut')
      return true
    },
    preventDefault: true,
  },
  {
    key: 'Cmd-Enter',
    run: () => {
      emit('run-shortcut')
      return true
    },
    preventDefault: true,
  },
])

// 获取语言扩展
function getLanguageExtension(lang) {
  const langKey = lang?.toLowerCase()
  const langFn = languageMap[langKey]
  return langFn ? langFn() : null
}

// 构建扩展列表
function buildExtensions(lang) {
  const extensions = [
    surfaceTheme(props.theme),
    tokenTheme(props.theme),
    history(),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    highlightActiveLine(),
    highlightActiveLineGutter(),
    highlightSelectionMatches(),
    foldGutter({
      openText: '▾',
      closedText: '▸',
    }),
    autocompletion({
      activateOnTyping: true,
      icons: false,
    }),
    keymap.of([
      ...defaultKeymap,
      ...historyKeymap,
      ...foldKeymap,
      ...closeBracketsKeymap,
      ...searchKeymap,
      ...completionKeymap,
      indentWithTab,
    ]),
    runKeymap,
    EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        emit('update:modelValue', update.state.doc.toString())
      }
    }),
    EditorView.editable.of(props.editable && !props.readonly),
  ]

  if (props.lineNumbers) {
    extensions.push(lineNumbersExtension())
  }

  const langExt = getLanguageExtension(lang)
  if (langExt) {
    extensions.push(langExt)
  }

  return extensions
}

// 初始化编辑器
function initEditor() {
  if (!editorRef.value) return

  const state = EditorState.create({
    doc: props.modelValue,
    extensions: buildExtensions(props.language),
  })

  view = new EditorView({
    state,
    parent: editorRef.value,
  })

  emit('ready', view)
}

// 切换语言
function changeLanguage(newLang) {
  if (!view) return

  const langExt = getLanguageExtension(newLang)
  if (!langExt) return

  // 重新配置语言扩展
  view.dispatch({
    effects: StateEffect.reconfigure.of(buildExtensions(newLang)),
  })
}

// 外部更新内容时同步到编辑器
watch(() => props.modelValue, (newVal) => {
  if (!view) return
  const currentValue = view.state.doc.toString()
  if (newVal !== currentValue) {
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: newVal },
    })
  }
})

// 语言变化
watch(() => props.language, (newLang) => {
  changeLanguage(newLang)
})

// 配色变化（OJ 详情页 / 课程实验页可不同）
watch(() => props.theme, () => {
  if (!view) return
  view.dispatch({
    effects: StateEffect.reconfigure.of(buildExtensions(props.language)),
  })
})

// 只读变化
watch(() => props.readonly, () => {
  if (!view) return
  view.dispatch({
    effects: StateEffect.reconfigure.of(buildExtensions(props.language)),
  })
})

onMounted(() => {
  initEditor()
})

onBeforeUnmount(() => {
  if (view) {
    view.destroy()
    view = null
  }
})

// 暴露方法
defineExpose({
  focus: () => view?.focus(),
  getView: () => view,
  insertText: (text) => {
    if (!view) return
    view.dispatch(view.state.replaceSelection(text))
    view.focus()
  },
})
</script>

<template>
  <div class="code-editor-wrapper" :class="`code-editor-wrapper--${theme}`">
    <div ref="editorRef" class="code-editor-root"></div>
  </div>
</template>

<style scoped>
.code-editor-wrapper {
  width: 100%;
  height: 100%;
  min-height: 0;
  background: var(--code-bg);
  overflow: hidden;
}

/* 浅色变体自成一体：不依赖外层容器覆盖令牌 */
.code-editor-wrapper--light {
  background: #FBFBFC;
}

.code-editor-root {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.code-editor-root :deep(.cm-editor) {
  height: 100%;
}

.code-editor-root :deep(.cm-scroller) {
  overflow: auto;
}
</style>
