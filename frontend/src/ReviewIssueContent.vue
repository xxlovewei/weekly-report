<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import ReviewText from './ReviewText.vue'
import type { ReviewIssue } from './types'

defineProps<{ issue: ReviewIssue; projectAlias?: string }>()
const ReviewCode = defineAsyncComponent(() => import('./ReviewCode.vue'))
</script>

<template>
    <header class="review-issue-head">
      <div class="review-issue-title">
        <div class="review-tags">
          <span class="review-number">ISSUE-{{ String(issue.id).padStart(2, '0') }}</span>
          <span class="review-severity" :data-level="issue.severity">{{ issue.severity }}</span>
          <span class="review-project-name">{{ projectAlias }}</span>
        </div>
        <h2><ReviewText :text="issue.title" /></h2>
      </div>
      <slot name="controls" />
    </header>
    <dl class="review-metadata">
      <div><dt>修改人</dt><dd>{{ issue.author_name }}</dd></div>
      <div v-if="issue.category"><dt>问题类型</dt><dd>{{ issue.category }}</dd></div>
      <div v-if="issue.dimension"><dt>审查维度</dt><dd>{{ issue.dimension }}</dd></div>
      <div class="review-meta-wide"><dt>提交</dt><dd class="preline"><code>{{ issue.sha }}</code> {{ issue.commit_message }}</dd></div>
      <div v-if="issue.path" class="review-meta-wide"><dt>涉及文件</dt><dd><code>{{ issue.path }}</code><template v-if="issue.start_line"> · 第 {{ issue.start_line }}<template v-if="issue.end_line && issue.end_line !== issue.start_line">–{{ issue.end_line }}</template> 行</template></dd></div>
    </dl>
    <section class="review-detail">
      <h3>风险说明</h3>
      <p class="preline"><ReviewText :text="issue.risk" /></p>
    </section>
    <section v-if="issue.existing_code" class="review-detail">
      <h3>相关代码</h3>
      <ReviewCode :source="issue.existing_code" :path="issue.path" />
    </section>
    <section v-if="issue.suggestion || issue.suggestion_code" class="review-detail">
      <h3>修改建议</h3>
      <p v-if="issue.suggestion" class="preline"><ReviewText :text="issue.suggestion" /></p>
      <ReviewCode v-if="issue.suggestion_code" :source="issue.suggestion_code" :path="issue.path" />
    </section>
</template>
