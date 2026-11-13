<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
import ReviewIssueContent from './ReviewIssueContent.vue'
import { progressStyle } from './taskStatuses'
import type { ReviewIssue } from './types'

const props = defineProps<{ issueId: number }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const issue = ref<(ReviewIssue & { project_alias: string }) | null>(null)
const error = ref('')

onMounted(async () => {
  dialog.value?.showModal()
  try { issue.value = await api<ReviewIssue & { project_alias: string }>(`/reviews/issues/${props.issueId}`) }
  catch (cause) { error.value = (cause as Error).message }
})
</script>

<template>
  <dialog ref="dialog" class="review-dialog summary-dialog" aria-labelledby="linked-review-title" @close="emit('close')">
    <header class="review-summary-head">
      <h2 id="linked-review-title">审查问题详情</h2>
      <button class="mini-button" type="button" @click="dialog?.close()">关闭</button>
    </header>
    <article v-if="issue" class="review-issue linked-review-issue">
      <ReviewIssueContent :issue="issue" :project-alias="issue.project_alias">
        <template #controls>
          <dl class="linked-review-status">
            <dt>完成状态</dt>
            <dd><span class="status-tag" :class="{ completed: issue.status === '已完成', pending: !issue.status }" :style="progressStyle(issue.status)">{{ issue.status || '未开始' }}</span></dd>
          </dl>
        </template>
      </ReviewIssueContent>
      <section class="review-issue-notes review-detail">
        <h3>备注</h3>
        <p class="preline">{{ issue.notes || '—' }}</p>
      </section>
    </article>
    <p v-else-if="error" class="review-error" role="alert">{{ error }}</p>
    <p v-else role="status">正在加载审查问题…</p>
  </dialog>
</template>
