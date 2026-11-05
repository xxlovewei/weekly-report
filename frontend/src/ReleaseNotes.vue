<script setup lang="ts">
import { ref, useId } from 'vue'
import { api } from './api'

const props = defineProps<{ version: string }>()
const tooltipId = useId()
const open = ref(false), loading = ref(false), loaded = ref(false)
const description = ref(''), error = ref('')

async function showNotes() {
  open.value = true
  if (loaded.value || loading.value) return
  loading.value = true; error.value = ''
  try {
    const record = await api<{ description: string } | null>(`/releases/${encodeURIComponent(props.version)}`)
    description.value = record?.description || '暂无本版本的更新说明。'
    loaded.value = true
  } catch { error.value = '暂时无法读取更新内容，请稍后重试。' }
  finally { loading.value = false }
}
</script>

<template>
  <div class="release-notes" @mouseenter="showNotes" @mouseleave="open = false" @keydown.esc.stop.prevent="open = false">
    <small tabindex="0" :aria-describedby="open ? tooltipId : undefined" @focus="showNotes" @blur="open = false">当前版本：v{{ version }}</small>
    <div v-if="open" :id="tooltipId" class="release-tooltip" role="tooltip">
      <strong>v{{ version }} 更新内容</strong>
      <p>{{ loading ? '正在加载更新内容…' : error || description }}</p>
    </div>
  </div>
</template>

<style scoped>
.release-notes{position:relative}
.release-notes small{cursor:help}
.release-notes small:focus-visible{outline:2px solid #000;outline-offset:3px}
.release-tooltip{position:absolute;top:100%;left:0;z-index:60;width:min(340px,calc(100vw - 120px));padding:12px;border:2px solid #000;background:#fff;box-shadow:4px 4px 0 #000;letter-spacing:normal}
.release-tooltip strong{display:block;font-size:13px;margin-bottom:8px}
.release-tooltip p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;max-height:320px;overflow-y:auto}
</style>
