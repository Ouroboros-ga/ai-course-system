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

// 自定义主题 - 适配项目设计令牌
const sfxCodeTheme = EditorView.theme({
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

// 语法高亮颜色定制
const sfxSyntaxHighlighting = EditorView.baseTheme({
  '&light .cm-keyword, &dark .cm-keyword': { color: '#C678DD' },
  '&light .cm-string, &dark .cm-string': { color: '#98C379' },
  '&light .cm-string-2, &dark .cm-string-2': { color: '#98C379' },
  '&light .cm-number, &dark .cm-number': { color: '#D19A66' },
  '&light .cm-comment, &dark .cm-comment': { color: 'var(--code-muted)', fontStyle: 'italic' },
  '&light .cm-function, &dark .cm-function': { color: '#61AFEF' },
  '&light .cm-functionName, &dark .cm-functionName': { color: '#61AFEF' },
  '&light .cm-variableName, &dark .cm-variableName': { color: '#E06C75' },
  '&light .cm-type, &dark .cm-type': { color: '#E5C07B' },
  '&light .cm-operator, &dark .cm-operator': { color: '#56B6C2' },
  '&light .cm-punctuation, &dark .cm-punctuation': { color: 'var(--code-text)' },
  '&light .cm-meta, &dark .cm-meta': { color: '#E5C07B' },
  '&light .cm-attribute, &dark .cm-attribute': { color: '#E5C07B' },
  '&light .cm-tag, &dark .cm-tag': { color: '#E06C75' },
  '&light .cm-property, &dark .cm-property': { color: '#61AFEF' },
  '&light .cm-qualifier, &dark .cm-qualifier': { color: '#E5C07B' },
  '&light .cm-atom, &dark .cm-atom': { color: '#D19A66' },
  '&light .cm-builtin, &dark .cm-builtin': { color: '#E5C07B' },
  '&light .cm-def, &dark .cm-def': { color: '#61AFEF' },
  '&light .cm-variable-2, &dark .cm-variable-2': { color: '#61AFEF' },
  '&light .cm-variable-3, &dark .cm-variable-3': { color: '#E5C07B' },
  '&light .cm-link, &dark .cm-link': { color: '#61AFEF' },
  '&light .cm-hr, &dark .cm-hr': { color: 'var(--code-muted)' },
})

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
    sfxCodeTheme,
    sfxSyntaxHighlighting,
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
  <div class="code-editor-wrapper">
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
