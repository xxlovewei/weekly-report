<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ text: string }>()
// 只解析行内代码标记，正文仍作为纯文本显示。
const parts = computed(() => props.text.split(/(`+[^`\r\n]+`+)/))
</script>

<template>
  <template v-for="(part, index) in parts" :key="index"><code v-if="index % 2">{{ part.replace(/^`+|`+$/g, '') }}</code><template v-else>{{ part }}</template></template>
</template>
