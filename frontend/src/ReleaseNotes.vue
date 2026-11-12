<script setup lang="ts">
import { ref, useId } from 'vue'
import { api } from './api'

const props = defineProps<{ version: string; compact?: boolean }>()
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
    <small data-sidebar-tour="release-notes" tabindex="0" :aria-describedby="open ? tooltipId : undefined" @focus="showNotes" @blur="open = false"><span v-if="!compact">当前版本：</span>v{{ version }}</small>
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
/* 引导弹窗贴着版本号时，把更新说明放到弹窗下方，并保留可悬停的路径。 */
.release-notes:has(small.driver-active-element) .release-tooltip{--release-tour-gap:180px;top:calc(100% + var(--release-tour-gap))}
.release-notes:has(small.driver-active-element) .release-tooltip::before{content:"";position:absolute;bottom:100%;left:0;width:38px;height:calc(var(--release-tour-gap) + 4px)}
.release-notes:has(small.driver-active-element) .release-tooltip p{max-height:clamp(48px,calc(100dvh - 340px),320px)}
</style>
