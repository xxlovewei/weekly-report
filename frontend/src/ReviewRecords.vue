<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from './api'
import { taskStatuses } from './taskStatuses'
import ReviewText from './ReviewText.vue'

const ReviewCode = defineAsyncComponent(() => import('./ReviewCode.vue'))
const props = defineProps<{ day: string; summaryRequest: number; refreshKey: number }>()
const router = useRouter()
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
const adding = ref<number | null>(null), loading = ref(false), error = ref(''), issueError = ref<Record<number, string>>({})
const author = ref<'all' | 'mine' | 'anonymous'>('all')
const completion = ref<'all' | 'done' | 'open'>('all')
const severities = ['严重', '高危', '中危', '低危', '提示'] as const
const severity = ref<string[]>([])
const selected = ref<string[]>([]), allProjects = ref(true)
const dialog = ref<HTMLDialogElement | null>(null)
const shown = computed(() => (data.value?.issues || []).filter(issue => selected.value.includes(String(issue.project_id))
  && (author.value === 'all' || issue[author.value])
  && (completion.value === 'all' || (issue.status === '已完成') === (completion.value === 'done'))
  && (!severity.value.length || severity.value.includes(issue.severity))))
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
let serial = 0
watch(() => [props.day, props.refreshKey] as const, async ([day]) => {
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
async function addToWork(issue: Issue) {
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
    <div class="review-filter-top">
      <div class="review-filter-group" role="group" aria-label="修改人">
        <strong>修改人</strong>
        <div class="review-tags">
          <button class="mini-button" :aria-pressed="author === 'mine'" @click="author = author === 'mine' ? 'all' : 'mine'">仅看我</button>
          <button class="mini-button" :aria-pressed="author === 'anonymous'" @click="author = author === 'anonymous' ? 'all' : 'anonymous'">仅看无名氏</button>
        </div>
      </div>
      <div class="review-filter-group" role="group" aria-label="完成状态">
        <strong>完成状态</strong>
        <div class="review-tags">
          <button v-for="([value, label]) in [['all', '全部'], ['done', '已完成'], ['open', '未完成']] as const" :key="value" class="mini-button" :aria-pressed="completion === value" @click="completion = value">{{ label }}</button>
        </div>
      </div>
      <div class="review-filter-group" role="group" aria-label="严重程度">
        <strong>严重程度</strong>
        <div class="review-tags">
          <button class="mini-button" :aria-pressed="!severity.length" @click="severity = []">全部</button>
          <button v-for="level in severities" :key="level" class="mini-button" :aria-pressed="severity.includes(level)" @click="toggleSeverity(level)">{{ level }}</button>
        </div>
      </div>
    </div>
    <div class="review-filter-projects" role="group" aria-label="审查项目">
      <strong>审查项目</strong>
      <div class="review-tags">
        <button class="mini-button" @click="selectAll(true)">全选</button>
        <button class="mini-button" @click="selectAll(false)">取消全选</button>
        <button v-for="(alias, id) in data?.projects" :key="id" class="mini-button project-tag" :aria-pressed="selected.includes(String(id))" @click="toggleProject(String(id))">{{ alias }}</button>
      </div>
    </div>
  </section>
  <p v-if="navigationError" class="review-error" role="alert">{{ navigationError }}</p>
  <p v-if="loading" class="empty" role="status">正在加载 {{ day }} 的审查记录…</p>
  <p v-else-if="error" class="empty review-error" role="alert">{{ error }}</p>
  <p v-else-if="!shown.length" class="empty">{{ data?.summary ? '没有符合条件的审查问题' : `${day} 暂无审查日报` }}</p>
  <article v-for="issue in shown" :key="issue.id" class="panel review-panel review-issue">
    <header class="review-issue-head">
      <div class="review-issue-title">
        <div class="review-tags">
          <span class="review-number">ISSUE-{{ String(issue.id).padStart(2, '0') }}</span>
          <span class="review-severity" :data-level="issue.severity">{{ issue.severity }}</span>
          <span class="review-project-name">{{ data?.projects[issue.project_id] }}</span>
        </div>
        <h2><ReviewText :text="issue.title" /></h2>
      </div>
      <div class="review-issue-controls">
        <label>完成状态<select v-model="draft[issue.id].status" aria-label="完成状态" :disabled="!issue.editable || adding === issue.id" @change="flushIssue(issue)">
          <option value="">未开始</option><option v-for="status in [...taskStatuses, '忽略']" :key="status">{{ status }}</option>
        </select></label>
        <button class="secondary-button" :disabled="adding !== null || issue.task_added" @click="addToWork(issue)">{{ issue.task_added ? '已添加到本周工作' : '添加到本周工作' }}</button>
      </div>
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
    <div class="review-issue-notes">
      <label>备注<textarea v-model="draft[issue.id].notes" aria-label="备注" rows="2" maxlength="5000" :disabled="!issue.editable || adding === issue.id" @input="queueNotes(issue)" @compositionend="queueNotes(issue)" /></label>
      <small v-if="issue.editable" role="status">{{ savingNotes.has(issue.id) ? '正在保存…' : !issueError[issue.id] && hasChanges(issue) ? '等待自动保存…' : issueError[issue.id] ? '' : '备注自动保存' }}</small>
      <div v-if="issueError[issue.id]" class="review-error" role="alert">
        {{ issueError[issue.id] }}
        <button v-if="issueError[issue.id].startsWith('保存失败') && hasChanges(issue)" class="mini-button" @click="flushIssue(issue)">重试</button>
      </div>
    </div>
  </article>
  <dialog ref="dialog" class="review-dialog summary-dialog" aria-labelledby="review-summary-title">
    <header class="review-summary-head">
      <div><h2 id="review-summary-title">日报总结</h2><time :datetime="day">{{ day }}</time></div>
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
      <section v-for="project in data.summary.projects" :key="project.project_id" class="review-summary-project">
        <header><h3>{{ project.alias }}</h3><span>{{ project.commits.length }} 个提交</span></header>
        <p v-if="project.error" class="review-error">{{ project.error }}</p>
        <h4>正面评价</h4>
        <ul v-if="project.positives.length"><li v-for="point in project.positives" :key="point">{{ point }}</li></ul>
        <p v-else>暂无可列出的正面评价</p>
        <details v-if="project.commits.length" :open="project.commits.some(commit => commit.status !== 'complete')">
          <summary>提交与审查覆盖</summary>
          <ul class="review-coverage">
            <li v-for="commit in project.commits" :key="commit.sha">
              <span class="status-tag" :class="{ completed: commit.status === 'complete', pending: commit.status === 'failed' }">{{ statusLabel[commit.status] }}</span>
              <div><code>{{ commit.sha.slice(0, 8) }}</code> · {{ commit.author || '无名氏' }} · {{ commit.title }}<p v-if="commit.reason">{{ commit.reason }}</p></div>
            </li>
          </ul>
        </details>
      </section>
    </template>
    <p v-else>{{ loading ? '正在加载日报…' : error || '当天暂无审查日报' }}</p>
  </dialog>
</template>
