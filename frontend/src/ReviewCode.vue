<script setup lang="ts">
import { computed } from 'vue'
import hljs from 'highlight.js/lib/common'
import 'highlight.js/styles/github.css'

const props = defineProps<{ source: string; path: string }>()
const languageByExtension: Record<string, string> = {
  c: 'c', cpp: 'cpp', cs: 'csharp', go: 'go', java: 'java', js: 'javascript',
  jsx: 'javascript', kt: 'kotlin', py: 'python', rb: 'ruby', rs: 'rust',
  sh: 'bash', ts: 'typescript', tsx: 'typescript', vue: 'xml', html: 'xml',
  xml: 'xml', css: 'css', scss: 'scss', sql: 'sql', json: 'json', yaml: 'yaml',
  yml: 'yaml', md: 'markdown', diff: 'diff', patch: 'diff', ps1: 'powershell',
}

const block = computed(() => {
  // Markdown 围栏中的语言优先，其次使用审查文件的扩展名。
  const fence = props.source.trim().match(/^(`{3,}|~{3,})[ \t]*([\w.+#-]*)[^\r\n]*\r?\n([\s\S]*?)\r?\n\1[ \t]*$/)
  const source = fence?.[3] ?? props.source
  const extension = props.path.split('.').at(-1)?.toLowerCase() ?? ''
  const requested = fence?.[2]?.toLowerCase() || languageByExtension[extension]
  if (!requested || !hljs.getLanguage(requested) || source.length > 30000) {
    return { source, html: '', language: requested }
  }
  // 只渲染高亮器生成的 HTML，OCR 返回的文本由高亮器转义。
  return { source, html: hljs.highlight(source, { language: requested, ignoreIllegals: true }).value, language: requested }
})
</script>

<template>
  <div class="review-code">
    <div v-if="block.language" class="review-code-language">{{ block.language }}</div>
    <pre tabindex="0"><code v-if="block.html" class="hljs" v-html="block.html"></code><code v-else>{{ block.source }}</code></pre>
  </div>
</template>
