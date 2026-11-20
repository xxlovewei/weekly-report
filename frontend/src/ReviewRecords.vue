<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from './api'
import { taskStatuses } from './taskStatuses'
import ReviewIssueContent from './ReviewIssueContent.vue'
import type { ReviewIssue as Issue } from './types'

const props = defineProps<{ day: string; summaryRequest: number; refreshKey: number }>()
const router = useRouter()
interface Commit {
  sha: string; author: string; author_name?: string; title: string; branches: string[]
  status: 'complete' | 'partial' | 'failed' | 'skipped'; reason: string
  ocr_elapsed?: string; ocr_comments?: number | null
  ocr_items_failed?: number | null; ocr_items_selected?: number | null
}
interface Project { project_id: number; alias: string; commits: Commit[]; positives: string[]; error: string }
interface ReviewDay {
  projects: Record<string, string>; issues: Issue[]
  common_project_ids: number[]
  summary: { commit_date: string; model: string; duration_seconds: number; projects: Project[] } | null
}
const data = ref<ReviewDay | null>(null)
const draft = ref<Record<number, { status: string; notes: string }>>({})
const adding = ref<number | null>(null), loading = ref(false), error = ref(''), issueError = ref<Record<number, string>>({})
const filtersExpanded = ref(true)
const filtersId = useId()
const issueListId = useId()
const expandedIssues = ref(new Set<number>())
const authorLabels = { all: '全部', mine: '仅看我', anonymous: '仅看无名氏' }
const completionLabels = { all: '全部', done: '已完成', open: '未完成' }
const author = ref<keyof typeof authorLabels>('all')
const completion = ref<keyof typeof completionLabels>('all')
const severities = ['严重', '高危', '中危', '低危', '提示'] as const
const severityOrder = new Map<string, number>(severities.map((level, index) => [level, index]))
const severity = ref<string[]>([])
const selected = ref<string[]>([]), allProjects = ref(true)
// 展开状态只控制筛选按钮的显示，不改变已经选中的项目。
const projectsExpanded = ref(false)
const projectIds = computed(() => Object.keys(data.value?.projects || {}))
const commonProjectIds = computed(() => new Set(data.value?.common_project_ids))
const hasOtherProjects = computed(() => projectIds.value.some(id => !commonProjectIds.value.has(Number(id))))
const filterSummary = computed(() => {
  const levels = severities.filter(level => severity.value.includes(level))
  const projects = selected.value.map(id => data.value?.projects[id]).filter(Boolean)
  return [
    ['修改人', authorLabels[author.value]],
    ['完成状态', completionLabels[completion.value]],
    ['严重程度', levels.join('、') || '全部'],
    ['审查项目', allProjects.value ? '全部' : (projects.join('、') || '未选择')],
  ]
})
const dialog = ref<HTMLDialogElement | null>(null)
// 已完成的问题放在最后，同一状态组按严重程度和问题编号排序。
function compareIssues(a: Issue, b: Issue) {
  const completionOrder = Number(a.status === '已完成') - Number(b.status === '已完成')
  const severityA = severityOrder.get(a.severity) ?? severities.length
  const severityB = severityOrder.get(b.severity) ?? severities.length
  return completionOrder || severityA - severityB || a.id - b.id
}
const shown = computed(() => (data.value?.issues || []).filter(issue => selected.value.includes(String(issue.project_id))
  && (author.value === 'all' || issue[author.value])
  && (completion.value === 'all' || (issue.status === '已完成') === (completion.value === 'done'))
  && (!severity.value.length || severity.value.includes(issue.severity))).sort(compareIssues))
const listExpanded = computed(() => shown.value.length > 0 && shown.value.every(issue => expandedIssues.value.has(issue.id)))
function toggleList() {
  // 也更新被筛选掉的卡片，切换筛选条件后仍保持批量操作的结果。
  expandedIssues.value = new Set(listExpanded.value ? [] : data.value?.issues.map(issue => issue.id))
}
function toggleIssue(id: number) {
  if (expandedIssues.value.has(id)) expandedIssues.value.delete(id)
  else expandedIssues.value.add(id)
}
const severityCounts = computed(() => severities.map(label => ({
  label, count: data.value?.issues.filter(issue => issue.severity === label).length || 0,
})))
const commitCount = computed(() => data.value?.summary?.projects.reduce((total, project) => total + project.commits.length, 0) || 0)
const reviewedCount = computed(() => data.value?.summary?.projects.reduce((total, project) => total + project.commits.filter(commit => commit.status === 'complete').length, 0) || 0)
const contributors = computed(() => new Set(data.value?.summary?.projects.flatMap(project => project.commits.map(commit => commit.author).filter(Boolean))).size)
const duration = computed(() => {
  const seconds = data.value?.summary?.duration_seconds || 0
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
})
const statusLabel: Record<string, string> = { complete: '已审查', partial: '部分完成', failed: '失败', skipped: '跳过' }
const positiveProjects = computed(() => (data.value?.summary?.projects || []).filter(project => project.positives.length))
const coverageProjects = computed(() => (data.value?.summary?.projects || []).filter(project => project.error || project.commits.length))
const coverageCounts = computed(() => Object.entries(statusLabel).map(([status, label]) => ({
  label, count: coverageProjects.value.reduce((total, project) => total + project.commits.filter(commit => commit.status === status).length, 0),
})))
const issueCountsByCommit = computed(() => {
  const counts = new Map<string, number>()
  for (const issue of data.value?.issues || []) {
    const key = `${issue.project_id}:${issue.sha}`
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return counts
})
let serial = 0
watch(() => [props.day, props.refreshKey] as const, async ([day]) => {
  const current = ++serial
  loading.value = true; error.value = ''; issueError.value = {}; data.value = null
  expandedIssues.value.clear()
  try {
    const result = await api<ReviewDay>(`/reviews/days/${day}`)
    if (current !== serial) return
    data.value = result
    const ids = projectIds.value
    selected.value = allProjects.value ? ids : selected.value.filter(id => ids.includes(id))
    if (ids.length) allProjects.value = selected.value.length === ids.length
    draft.value = Object.fromEntries(result.issues.map(issue => [issue.id, { status: issue.status || '', notes: issue.notes }]))
  } catch (cause) { if (current === serial) error.value = (cause as Error).message }
  finally { if (current === serial) loading.value = false }
}, { immediate: true })
watch(() => props.summaryRequest, () => { if (!dialog.value?.open) dialog.value?.showModal() })
function selectAll(value: boolean) {
  allProjects.value = value
  selected.value = value ? projectIds.value : []
}
function toggleProject(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
  allProjects.value = selected.value.length === projectIds.value.length
}
const noteTimers = new Map<number, number>()
const saving = new Map<number, Promise<boolean>>()
const savingNotes = ref(new Set<number>())
const saveDelay = 650
const navigationError = ref('')

function issuePatch(issue: Issue) {
  const values = draft.value[issue.id]
  const patch: Partial<Pick<Issue, 'status' | 'notes'>> = {}
  if (values.status !== (issue.status || '')) patch.status = values.status || null
  if (values.notes.trim() !== issue.notes) patch.notes = values.notes.trim()
  return patch
}
function hasChanges(issue: Issue) {
  return Object.keys(issuePatch(issue)).length > 0
}
function clearNoteTimer(id: number) {
  window.clearTimeout(noteTimers.get(id))
  noteTimers.delete(id)
}
function queueNotes(issue: Issue) {
  if (noteTimers.has(issue.id)) return
  noteTimers.set(issue.id, window.setTimeout(() => {
    clearNoteTimer(issue.id)
    void saveIssue(issue)
  }, saveDelay))
}
async function saveIssue(issue: Issue): Promise<boolean> {
  const previous = saving.get(issue.id)
  if (previous) {
    if (!await previous) return false
    return saveIssue(issue)
  }
  const patch = issuePatch(issue)
  issueError.value[issue.id] = ''
  if (!Object.keys(patch).length) return true
  const values = draft.value[issue.id]
  if (values.status === '忽略' && ['高危', '严重'].includes(issue.severity) && !values.notes.trim()) {
    issueError.value[issue.id] = '忽略高危或严重问题时，请填写备注。'
    return false
  }
  const sent = { ...values }
  const pending = (async () => {
    savingNotes.value.add(issue.id)
    try {
      const saved = await api<Pick<Issue, 'status' | 'notes'>>(`/reviews/issues/${issue.id}`, 'PATCH', patch)
      // 请求期间可以继续输入，只同步尚未再次修改的字段。
      if (values.status === sent.status) values.status = saved.status || ''
      if (values.notes === sent.notes && patch.notes === undefined) values.notes = saved.notes
      Object.assign(issue, saved)
      return true
    } catch (cause) {
      issueError.value[issue.id] = `保存失败：${(cause as Error).message}`
      return false
    } finally {
      savingNotes.value.delete(issue.id)
    }
  })()
  saving.set(issue.id, pending)
  try { return await pending } finally { saving.delete(issue.id) }
}
async function flushIssue(issue: Issue): Promise<boolean> {
  clearNoteTimer(issue.id)
  if (!await saveIssue(issue)) return false
  return !hasChanges(issue) || flushIssue(issue)
}
async function flushReview() {
  navigationError.value = ''
  const issues = (data.value?.issues || []).filter(issue => saving.has(issue.id) || hasChanges(issue))
  const saved = (await Promise.all(issues.map(flushIssue))).every(Boolean)
  if (!saved) navigationError.value = '有审查问题尚未保存，请检查对应卡片中的提示。'
  return saved
}
defineExpose({ flushReview })
const unregister = router.beforeEach((to, from) => {
  if (from.name === 'review-records' && (to.name !== from.name || to.query.date !== from.query.date)) return flushReview()
})
function beforeUnload(event: BeforeUnloadEvent) {
  if (saving.size || data.value?.issues.some(hasChanges)) event.preventDefault()
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onUnmounted(() => {
  unregister()
  window.removeEventListener('beforeunload', beforeUnload)
  for (const id of noteTimers.keys()) clearNoteTimer(id)
})
async function addToBoard(issue: Issue) {
  adding.value = issue.id
  try {
    if (!await flushIssue(issue)) return
    await api(`/reviews/issues/${issue.id}/task`, 'POST')
    issue.task_added = true
  } catch (cause) { issueError.value[issue.id] = (cause as Error).message }
  finally { adding.value = null }
}
function toggleSeverity(level: string) {
  severity.value = severity.value.includes(level) ? severity.value.filter(item => item !== level) : [...severity.value, level]
}
</script>

<template>
  <section class="panel review-panel review-filters" aria-label="筛选审查记录">
    <header class="review-filter-head">
      <button class="review-card-toggle review-filter-toggle" type="button" :aria-label="filtersExpanded ? '收起筛选' : '展开筛选'" :title="filtersExpanded ? '收起筛选' : '展开筛选'" :aria-expanded="filtersExpanded" :aria-controls="filtersId" @click="filtersExpanded = !filtersExpanded">
        <span aria-hidden="true">{{ filtersExpanded ? '−' : '+' }}</span>
      </button>
      <button class="mini-button" type="button" :aria-expanded="listExpanded" :aria-controls="issueListId" :disabled="!shown.length" @click="toggleList">{{ listExpanded ? '收起列表' : '展开列表' }}</button>
      <div v-if="!filtersExpanded" class="review-filter-summary" role="group" aria-label="当前筛选条件" tabindex="0">
        <span v-for="([label, value]) in filterSummary" :key="label">{{ label }}：{{ value }}</span>
      </div>
    </header>
    <div v-show="filtersExpanded" :id="filtersId" class="review-filter-body">
      <div class="review-filter-top">
        <div class="review-filter-group" role="group" aria-label="修改人">
          <strong>修改人</strong>
          <div class="review-tags">
            <button class="mini-button" :aria-pressed="author === 'mine'" @click="author = author === 'mine' ? 'all' : 'mine'">{{ authorLabels.mine }}</button>
            <button class="mini-button" :aria-pressed="author === 'anonymous'" @click="author = author === 'anonymous' ? 'all' : 'anonymous'">{{ authorLabels.anonymous }}</button>
          </div>
        </div>
        <div class="review-filter-group" role="group" aria-label="完成状态">
          <strong>完成状态</strong>
          <div class="review-tags">
            <button v-for="(label, value) in completionLabels" :key="value" class="mini-button" :aria-pressed="completion === value" @click="completion = value">{{ label }}</button>
          </div>
        </div>
        <div class="review-filter-group" role="group" aria-label="严重程度">
          <strong>严重程度</strong>
          <div class="review-tags">
            <button class="mini-button" :aria-pressed="!severity.length" @click="severity = []">全部</button>
            <button v-for="level in severities" :key="level" class="mini-button" :aria-pressed="severity.includes(level)" @click="toggleSeverity(level)">{{ level }}</button>
          </div>
        </div>
        <div class="review-filter-group review-filter-projects" role="group" aria-label="审查项目">
          <strong>审查项目</strong>
          <div class="review-tags">
            <button class="mini-button review-project-action" type="button" :disabled="!projectIds.length" @click="selectAll(!allProjects)">{{ allProjects ? '取消全选' : '全选' }}</button>
            <button v-if="hasOtherProjects" class="mini-button review-project-action" type="button" :aria-expanded="projectsExpanded" @click="projectsExpanded = !projectsExpanded">{{ projectsExpanded ? '收起' : '展开全部' }}</button>
            <button v-for="(alias, id) in data?.projects" v-show="projectsExpanded || commonProjectIds.has(Number(id))" :key="id" class="mini-button project-tag" :aria-pressed="selected.includes(String(id))" @click="toggleProject(String(id))">{{ alias }}</button>
          </div>
        </div>
      </div>
    </div>
  </section>
  <section :id="issueListId" class="review-results" aria-label="审查问题列表">
    <p v-if="navigationError" class="review-error" role="alert">{{ navigationError }}</p>
    <p v-if="loading" class="empty" role="status">正在加载 {{ day }} 的审查记录…</p>
    <p v-else-if="error" class="empty review-error" role="alert">{{ error }}</p>
    <p v-else-if="!shown.length" class="empty">{{ data?.summary ? '没有符合条件的审查问题' : `${day} 暂无审查日报` }}</p>
    <article v-for="issue in shown" :key="issue.id" class="panel review-panel review-issue">
      <ReviewIssueContent :issue="issue" :project-alias="data?.projects[issue.project_id]" :expanded="expandedIssues.has(issue.id)" collapsible @toggle="toggleIssue(issue.id)">
        <template #controls>
          <label class="review-card-status">完成状态<select v-model="draft[issue.id].status" aria-label="完成状态" :disabled="!issue.editable || adding === issue.id" @change="flushIssue(issue)">
            <option value="">未开始</option><option>忽略</option><option v-for="status in taskStatuses" :key="status">{{ status }}</option>
          </select></label>
        </template>
        <template #actions>
          <button type="button" class="secondary-button review-issue-add" :disabled="adding !== null || issue.task_added || draft[issue.id].status === '忽略'" @click="addToBoard(issue)">{{ issue.task_added ? '已添加' : '添加到任务看板' }}</button>
        </template>
        <div class="review-issue-notes">
          <label>备注<textarea v-model="draft[issue.id].notes" aria-label="备注" rows="2" maxlength="5000" :disabled="!issue.editable || adding === issue.id" @input="queueNotes(issue)" @compositionend="queueNotes(issue)" /></label>
          <small v-if="issue.editable" role="status">{{ savingNotes.has(issue.id) ? '正在保存…' : !issueError[issue.id] && hasChanges(issue) ? '等待自动保存…' : issueError[issue.id] ? '' : '备注自动保存' }}</small>
          <div v-if="issueError[issue.id]" class="review-error" role="alert">
            {{ issueError[issue.id] }}
            <button v-if="issueError[issue.id].startsWith('保存失败') && hasChanges(issue)" class="mini-button" @click="flushIssue(issue)">重试</button>
          </div>
        </div>
      </ReviewIssueContent>
      <p v-if="!expandedIssues.has(issue.id) && issueError[issue.id]" class="review-error" role="alert">{{ issueError[issue.id] }}</p>
    </article>
  </section>
  <dialog ref="dialog" class="review-dialog summary-dialog review-report-dialog" aria-labelledby="review-summary-title">
    <header class="review-summary-head">
      <div><h2 id="review-summary-title">审查总结</h2><time :datetime="day">{{ day }}</time></div>
      <button class="mini-button" @click="dialog?.close()">关闭</button>
    </header>
    <template v-if="data?.summary">
      <dl class="review-summary-run">
        <div><dt>审查模型</dt><dd><code>{{ data.summary.model }}</code></dd></div>
        <div><dt>审查时长</dt><dd>{{ duration }}</dd></div>
        <div><dt>提交日期</dt><dd>{{ data.summary.commit_date }}</dd></div>
      </dl>
      <dl class="review-summary-stats">
        <div><dt>审查项目</dt><dd>{{ data.summary.projects.length }}</dd></div>
        <div><dt>修改人</dt><dd>{{ contributors }}</dd></div>
        <div><dt>完整审查 / 提交</dt><dd>{{ reviewedCount }} / {{ commitCount }}</dd></div>
        <div><dt>问题总数</dt><dd>{{ data.issues.length }}</dd></div>
      </dl>
      <div class="review-tags review-summary-severities" aria-label="问题严重程度分布">
        <span v-for="{ label, count } in severityCounts" :key="label" class="review-severity" :data-level="label">{{ label }} {{ count }}</span>
      </div>
      <div class="review-report-body" tabindex="0" role="region" aria-label="审查报告明细">
        <section v-for="project in positiveProjects" :key="project.project_id" class="review-summary-project">
          <header><h3>{{ project.alias }}</h3><span>{{ project.commits.length }} 个提交</span></header>
          <p v-if="project.error" class="review-error">{{ project.error }}</p>
          <h4>正面评价</h4>
          <ul><li v-for="point in project.positives" :key="point">{{ point }}</li></ul>
        </section>
        <section class="review-summary-project" aria-labelledby="review-coverage-heading">
          <h3 id="review-coverage-heading">审查覆盖说明</h3>
          <p v-if="!coverageProjects.length">本次日报没有待审查的提交。</p>
          <template v-else>
            <p>{{ coverageCounts.map(({ label, count }) => `${label} ${count} 个提交`).join(' · ') }}</p>
            <p v-if="coverageProjects.some(project => project.error || project.commits.some(commit => commit.status !== 'complete'))">
              建议优先补审未完整覆盖的提交，并检查读取失败的项目。
            </p>
            <details v-for="project in coverageProjects" :key="project.project_id" open>
            <summary>{{ project.alias }} · {{ project.commits.length }} 个提交</summary>
            <p v-if="project.error" class="review-error">{{ project.error }}</p>
            <ul class="review-coverage">
              <li v-for="commit in project.commits" :key="commit.sha">
                <span class="status-tag" :class="{ completed: commit.status === 'complete', pending: commit.status !== 'complete' }">{{ statusLabel[commit.status] }}</span>
                <div>
                  <code>{{ commit.sha.slice(0, 8) }}</code> · {{ commit.author_name || commit.author || '无名氏' }}<template v-if="commit.title"> · {{ commit.title }}</template>
                  <p>{{ commit.ocr_comments ?? issueCountsByCommit.get(`${project.project_id}:${commit.sha}`) ?? 0 }} 条意见<template v-if="commit.ocr_elapsed"> · 耗时 {{ commit.ocr_elapsed }}</template></p>
                  <p v-if="commit.reason || commit.ocr_items_failed != null">{{ commit.reason }}<template v-if="commit.ocr_items_failed != null"> · {{ commit.ocr_items_selected }} 个审查项中 {{ commit.ocr_items_failed }} 个失败</template></p>
                </div>
              </li>
            </ul>
            </details>
          </template>
        </section>
      </div>
    </template>
    <p v-else>{{ loading ? '正在加载日报…' : error || '当天暂无审查日报' }}</p>
  </dialog>
</template>
