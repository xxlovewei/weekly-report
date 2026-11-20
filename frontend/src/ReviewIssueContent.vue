<script setup lang="ts">
import { computed, defineAsyncComponent, useId } from 'vue'
import ReviewText from './ReviewText.vue'
import { progressStyle } from './taskStatuses'
import type { ReviewIssue } from './types'

const props = defineProps<{ issue: ReviewIssue; projectAlias?: string; collapsible?: boolean; expanded?: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const ReviewCode = defineAsyncComponent(() => import('./ReviewCode.vue'))
const detailId = useId()
const showDetails = computed(() => !props.collapsible || props.expanded)
const issueNumber = computed(() => `ISSUE-${String(props.issue.id).padStart(2, '0')}`)
</script>

<template>
  <header class="review-issue-head" :class="{ 'review-card-head': collapsible }">
    <button
      v-if="collapsible"
      class="review-card-toggle"
      type="button"
      :aria-label="`${expanded ? '收起' : '展开'} ${issueNumber} 详情`"
      :aria-expanded="expanded"
      :aria-controls="detailId"
      @click="emit('toggle')"
    ><span aria-hidden="true">{{ expanded ? '−' : '+' }}</span></button>
    <div class="review-issue-title">
      <div class="review-tags">
        <span class="review-number">{{ issueNumber }}</span>
        <span class="review-severity" :data-level="issue.severity">{{ issue.severity }}</span>
        <span class="review-project-name">{{ projectAlias }}</span>
        <template v-if="collapsible">
          <span class="review-author-tag" :title="`修改人：${issue.author_name}`">{{ issue.author_name }}</span>
          <template v-if="!expanded">
            <span class="status-tag" :class="{ completed: issue.status === '已完成', pending: !issue.status }" :style="progressStyle(issue.status)">{{ issue.status || '未开始' }}</span>
            <span class="review-card-title"><ReviewText :text="issue.title" /></span>
          </template>
        </template>
      </div>
      <h2 v-if="!collapsible"><ReviewText :text="issue.title" /></h2>
    </div>
    <slot v-if="showDetails" name="controls" />
    <slot name="actions" />
  </header>
  <div v-show="showDetails" :id="collapsible ? detailId : undefined" class="review-issue-body">
    <!-- 收起时延迟渲染详情，备注草稿仍由审查记录页面维护。 -->
    <template v-if="showDetails">
      <h2 v-if="collapsible"><ReviewText :text="issue.title" /></h2>
      <dl class="review-metadata" :class="{ 'review-metadata-row': collapsible }">
        <div v-if="!collapsible"><dt>修改人</dt><dd>{{ issue.author_name }}</dd></div>
        <div v-if="collapsible || issue.category"><dt>问题类型</dt><dd>{{ issue.category || '—' }}</dd></div>
        <div v-if="collapsible || issue.dimension"><dt>审查维度</dt><dd>{{ issue.dimension || '—' }}</dd></div>
        <div class="review-meta-wide"><dt>提交</dt><dd class="preline"><code>{{ issue.sha }}</code> {{ issue.commit_message }}</dd></div>
        <div v-if="collapsible || issue.path" class="review-meta-wide"><dt>涉及文件</dt><dd><template v-if="issue.path"><code>{{ issue.path }}</code><template v-if="issue.start_line"> · 第 {{ issue.start_line }}<template v-if="issue.end_line && issue.end_line !== issue.start_line">–{{ issue.end_line }}</template> 行</template></template><template v-else>—</template></dd></div>
      </dl>
      <div class="review-detail-row">
        <section class="review-detail">
          <h3>风险说明</h3>
          <p class="preline"><ReviewText :text="issue.risk" /></p>
        </section>
        <section v-if="issue.existing_code" class="review-detail">
          <h3>相关代码</h3>
          <ReviewCode :source="issue.existing_code" :path="issue.path" />
        </section>
      </div>
      <div v-if="issue.suggestion || issue.suggestion_code" class="review-detail-row review-suggestion-row">
        <section v-if="issue.suggestion" class="review-detail">
          <h3>修改建议</h3>
          <p class="preline"><ReviewText :text="issue.suggestion" /></p>
        </section>
        <section v-if="issue.suggestion_code" class="review-detail">
          <h3 v-if="collapsible || !issue.suggestion">{{ collapsible ? '修改建议的代码' : '修改建议' }}</h3>
          <ReviewCode :source="issue.suggestion_code" :path="issue.path" />
        </section>
      </div>
      <slot />
    </template>
  </div>
</template>
