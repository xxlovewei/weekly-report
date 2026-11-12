<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from './api'
import { taskStatuses } from './taskStatuses'

const props = defineProps<{ day: string; summaryRequest: number }>()
interface Issue {
  id: number; project_id: number; author: string; author_name: string; mine: boolean; anonymous: boolean
  title: string; severity: string; category: string; dimension: string; sha: string; commit_message: string
  path: string; start_line: number | null; end_line: number | null; existing_code: string
  risk: string; suggestion: string; suggestion_code: string; status: string | null; notes: string
  task_added: boolean; editable: boolean
}
interface Commit { sha: string; author: string; title: string; branches: string[]; status: string; reason: string }
interface Project { project_id: number; alias: string; commits: Commit[]; positives: string[]; error: string }
interface ReviewDay {
  projects: Record<string, string>; issues: Issue[]
  summary: { commit_date: string; model: string; duration_seconds: number; projects: Project[] } | null
}
const data = ref<ReviewDay | null>(null)
const draft = ref<Record<number, { status: string; notes: string }>>({})
const busy = ref<number | null>(null), loading = ref(false), error = ref(''), issueError = ref<Record<number, string>>({})
const author = ref<'all' | 'mine' | 'anonymous'>('all')
const completion = ref<'all' | 'done' | 'open'>('all')
const selected = ref<string[]>([]), allProjects = ref(true)
const dialog = ref<HTMLDialogElement | null>(null)
const shown = computed(() => (data.value?.issues || []).filter(issue => selected.value.includes(String(issue.project_id))
  && (author.value === 'all' || issue[author.value])
  && (completion.value === 'all' || (issue.status === '已完成') === (completion.value === 'done'))))
const severityCounts = computed(() => ['严重', '高危', '中危', '低危', '提示'].map(label => `${label} ${data.value?.issues.filter(issue => issue.severity === label).length || 0}`))
const commitCount = computed(() => data.value?.summary?.projects.reduce((total, project) => total + project.commits.length, 0) || 0)
const reviewedCount = computed(() => data.value?.summary?.projects.reduce((total, project) => total + project.commits.filter(commit => commit.status === 'complete').length, 0) || 0)
const contributors = computed(() => new Set(data.value?.summary?.projects.flatMap(project => project.commits.map(commit => commit.author).filter(Boolean))).size)
const duration = computed(() => {
  const seconds = data.value?.summary?.duration_seconds || 0
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
})
const statusLabel: Record<string, string> = { complete: '已审查', partial: '部分完成', failed: '失败', skipped: '跳过' }
let serial = 0
watch(() => props.day, async day => {
  const current = ++serial
  loading.value = true; error.value = ''; issueError.value = {}; data.value = null
  try {
    const result = await api<ReviewDay>(`/reviews/days/${day}`)
    if (current !== serial) return
    data.value = result
    const ids = Object.keys(result.projects)
    selected.value = allProjects.value ? ids : selected.value.filter(id => ids.includes(id))
    draft.value = Object.fromEntries(result.issues.map(issue => [issue.id, { status: issue.status || '', notes: issue.notes }]))
  } catch (cause) { if (current === serial) error.value = (cause as Error).message }
  finally { if (current === serial) loading.value = false }
}, { immediate: true })
watch(() => props.summaryRequest, () => { if (!dialog.value?.open) dialog.value?.showModal() })
function selectAll(value: boolean) {
  allProjects.value = value
  selected.value = value ? Object.keys(data.value?.projects || {}) : []
}
function toggleProject(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
  allProjects.value = selected.value.length === Object.keys(data.value?.projects || {}).length
}
async function saveIssue(issue: Issue, addTask = false) {
  busy.value = issue.id; issueError.value[issue.id] = ''
  const values = draft.value[issue.id]
  try {
    if (issue.editable && (values.status !== (issue.status || '') || values.notes.trim() !== issue.notes)) {
      const patch = { status: values.status || null, notes: values.notes.trim() }
      await api(`/reviews/issues/${issue.id}`, 'PATCH', patch)
      Object.assign(issue, patch)
    }
    if (addTask) {
      await api(`/reviews/issues/${issue.id}/task`, 'POST')
      issue.task_added = true
    }
  } catch (cause) { issueError.value[issue.id] = (cause as Error).message }
  finally { busy.value = null }
}
function changeStatus(issue: Issue) {
  if (draft.value[issue.id].status === '忽略' && ['高危', '严重'].includes(issue.severity) && !draft.value[issue.id].notes.trim()) {
    issueError.value[issue.id] = '忽略高危或严重问题时，请先填写备注。'
    return
  }
  void saveIssue(issue)
}
</script>

<template>
  <section class="panel review-panel review-filters" aria-label="筛选审查记录">
    <div class="review-filter-row"><strong>提交人</strong><div class="review-tags">
      <button class="mini-button" :aria-pressed="author === 'mine'" @click="author = author === 'mine' ? 'all' : 'mine'">仅看我</button>
      <button class="mini-button" :aria-pressed="author === 'anonymous'" @click="author = author === 'anonymous' ? 'all' : 'anonymous'">仅看无名氏</button>
    </div></div>
    <div class="review-filter-row"><strong>审查项目</strong><div class="review-tags">
      <button class="mini-button" @click="selectAll(true)">全选</button><button class="mini-button" @click="selectAll(false)">取消全选</button>
      <button v-for="(alias, id) in data?.projects" :key="id" class="mini-button project-tag" :aria-pressed="selected.includes(String(id))" @click="toggleProject(String(id))">{{ alias }}</button>
    </div></div>
    <div class="review-filter-row"><strong>是否已完成</strong><div class="review-tags">
      <button v-for="([value, label]) in [['all', '全部'], ['done', '已完成'], ['open', '未完成']] as const" :key="value" class="mini-button" :aria-pressed="completion === value" @click="completion = value">{{ label }}</button>
    </div></div>
  </section>
  <p v-if="loading" class="empty" role="status">正在加载 {{ day }} 的审查记录…</p>
  <p v-else-if="error" class="empty review-error" role="alert">{{ error }}</p>
  <p v-else-if="!shown.length" class="empty">{{ data?.summary ? '没有符合条件的审查问题' : `${day} 暂无审查日报` }}</p>
  <article v-for="issue in shown" :key="issue.id" class="panel review-panel review-issue">
    <div class="review-panel-head"><div class="review-tags"><span class="review-number">ISSUE-{{ String(issue.id).padStart(2, '0') }}</span><span class="review-severity" :class="{ critical: ['严重', '高危'].includes(issue.severity) }">{{ issue.severity }}</span><span>{{ data?.projects[issue.project_id] }}</span></div>
      <button class="secondary-button" :disabled="busy !== null || issue.task_added" @click="saveIssue(issue, true)">{{ issue.task_added ? '已添加到任务' : '添加到任务' }}</button></div>
    <h2>{{ issue.title }}</h2>
    <dl class="review-metadata">
      <div><dt>修改人</dt><dd>{{ issue.author_name }}</dd></div>
      <div v-if="issue.category"><dt>问题类型</dt><dd>{{ issue.category }}</dd></div>
      <div v-if="issue.dimension"><dt>审查维度</dt><dd>{{ issue.dimension }}</dd></div>
      <div><dt>提交</dt><dd><code>{{ issue.sha }}</code> {{ issue.commit_message }}</dd></div>
      <div v-if="issue.path"><dt>涉及文件</dt><dd>{{ issue.path }}<template v-if="issue.start_line"> · 第 {{ issue.start_line }}<template v-if="issue.end_line && issue.end_line !== issue.start_line">–{{ issue.end_line }}</template> 行</template></dd></div>
    </dl>
    <template v-if="issue.existing_code"><h3>相关代码</h3><pre><code>{{ issue.existing_code }}</code></pre></template>
    <h3>风险说明</h3><p class="preline">{{ issue.risk }}</p>
    <template v-if="issue.suggestion || issue.suggestion_code"><h3>修改建议</h3><p class="preline" v-if="issue.suggestion">{{ issue.suggestion }}</p><pre v-if="issue.suggestion_code"><code>{{ issue.suggestion_code }}</code></pre></template>
    <div class="review-issue-actions">
      <label>完成状态<select v-model="draft[issue.id].status" aria-label="完成状态" :disabled="busy !== null || !issue.editable" @change="changeStatus(issue)">
        <option value="">未开始</option><option v-for="status in [...taskStatuses, '忽略']" :key="status">{{ status }}</option>
      </select></label>
      <label>备注<textarea v-model="draft[issue.id].notes" aria-label="备注" rows="2" maxlength="5000" :disabled="busy !== null || !issue.editable" /></label>
      <button class="mini-button" :disabled="busy !== null || !issue.editable || (draft[issue.id].notes.trim() === issue.notes && draft[issue.id].status === (issue.status || ''))" @click="saveIssue(issue)">保存备注</button>
    </div>
    <p v-if="issueError[issue.id]" class="review-error" role="alert">{{ issueError[issue.id] }}</p>
  </article>
  <dialog ref="dialog" class="review-dialog summary-dialog" aria-labelledby="review-summary-title">
    <div class="review-panel-head"><h2 id="review-summary-title">日报总结 · {{ day }}</h2><button class="mini-button" @click="dialog?.close()">关闭</button></div>
    <template v-if="data?.summary">
      <p><strong>审查模型</strong> {{ data.summary.model }}　<strong>审查时长</strong> {{ duration }}</p>
      <p>提交日期 {{ data.summary.commit_date }} · {{ data.summary.projects.length }} 个项目 · {{ contributors }} 位修改人 · {{ commitCount }} 个提交 · 完整审查 {{ reviewedCount }}/{{ commitCount }}</p>
      <p>共 {{ data.issues.length }} 个问题 · {{ severityCounts.join(' · ') }}</p>
      <section v-for="project in data.summary.projects" :key="project.project_id" class="review-summary-project">
        <h3>{{ project.alias }} · {{ project.commits.length }} 个提交</h3>
        <p v-if="project.error" class="review-error">{{ project.error }}</p>
        <strong>正面评价</strong>
        <ul v-if="project.positives.length"><li v-for="point in project.positives" :key="point">{{ point }}</li></ul>
        <p v-else>暂无可列出的正面评价</p>
        <details v-if="project.commits.length" :open="project.commits.some(commit => commit.status !== 'complete')">
          <summary>提交与审查覆盖</summary>
          <ul><li v-for="commit in project.commits" :key="commit.sha"><code>{{ commit.sha.slice(0, 8) }}</code> · {{ commit.author || '无名氏' }} · {{ commit.title }} · {{ statusLabel[commit.status] }}<template v-if="commit.reason"> · {{ commit.reason }}</template></li></ul>
        </details>
      </section>
    </template>
    <p v-else>{{ loading ? '正在加载日报…' : error || '当天暂无审查日报' }}</p>
  </dialog>
</template>
