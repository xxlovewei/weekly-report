<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api'
import GitLabRefPicker from './GitLabRefPicker.vue'

const props = defineProps<{ admin: boolean; section: Tab }>()

interface Version {
  id: number; number: string; branch: string | null; branch_url: string | null; sha: string | null
  tag: string | null; tag_url: string | null; tag_sha: string | null
}
interface GitLabRef { name: string; sha: string }
interface Project { id: number; name: string; level: string | null; network: string | null; sites: string[] }
interface Item { id: number; title: string; notes: string; author: string; source_version: string | null; removed: boolean; done: boolean; dispatched: boolean; can_complete: boolean }
interface Plan {
  id: number; project_id: number; project_name: string; site: string; network: string
  version: Version; from_version: Version | null; status: 'baseline' | 'draft' | 'ready' | 'succeeded' | 'failed' | 'cancelled'
  scheduled_at: string | null; upgrade_content: string; deployed_at: string | null; rolled_back_at: string | null
  confirmed_by: string | null; revision: number; checklist_count: number; can_confirm: boolean
}
interface Detail extends Plan { items: Item[] }
interface Target { project_id: number; site: string; current?: Plan; planned?: Plan }
interface MemoTarget { site: string; done: boolean; item_id: number | null; plan_id: number | null; can_complete: boolean; baseline_covered: boolean }
interface Memo { id: number; project_id: number; title: string; notes: string; version: Version | null; network: string; done: boolean; targets: MemoTarget[] }
interface Overview { projects: Project[]; history_projects: { id: number; name: string }[]; sites: Record<string, string>; networks: Record<string, string>; targets: Target[] }
type Tab = 'overview' | 'plans' | 'memos'
type FormMode = 'plan' | 'baseline' | 'memo'

const route = useRoute(), router = useRouter()
const states = { baseline: '基线补录', draft: '待确认清单', ready: '待发版', succeeded: '发版成功', failed: '发版失败', cancelled: '已取消' }
const tab = computed(() => props.section)
const historyMode = ref(false)
const overview = ref<Overview>({ projects: [], history_projects: [], sites: {}, networks: {}, targets: [] })
const plans = ref<Plan[]>([]), history = ref<Plan[]>([]), memos = ref<Memo[]>([])
const detail = ref<Detail | null>(null), removedIds = ref<number[]>([])
const operation = ref<'edit' | 'result'>('edit'), actionPlan = ref<Plan | null>(null)
const schedule = ref(''), detailContent = ref(''), actual = ref(''), outcome = ref<'succeeded' | 'failed' | ''>('')
const editNumber = ref(''), editBranch = ref<GitLabRef | null>(null), editTag = ref<GitLabRef | null>(null)
const editBranchPicker = ref<InstanceType<typeof GitLabRefPicker> | null>(null), editTagPicker = ref<InstanceType<typeof GitLabRefPicker> | null>(null)
const overviewLevel = ref('regional'), overviewSite = ref(''), overviewNetwork = ref(''), projectSearch = ref('')
const historyProject = ref<number | ''>(''), historySite = ref(''), historyNetwork = ref('')
const historyVersion = ref(''), start = ref(''), end = ref('')
const memoStatus = ref('pending')
const editor = ref<HTMLDialogElement | null>(null), planDialog = ref<HTMLDialogElement | null>(null)
const operationDialog = ref<HTMLDialogElement | null>(null), itemTooltip = ref<HTMLElement | null>(null)
const tooltipItem = ref<Item | null>(null)
const mode = ref<FormMode>('memo'), editingMemo = ref<number | null>(null)
const projectId = ref<number | null>(null), versionId = ref<number | null>(null), sites = ref<string[]>([])
const title = ref(''), notes = ref(''), timestamp = ref(''), upgradeContent = ref('')
const versions = ref<Version[]>([])
const newVersion = ref(false), number = ref('')
const branch = ref<GitLabRef | null>(null), tag = ref<GitLabRef | null>(null)
const branchPicker = ref<InstanceType<typeof GitLabRefPicker> | null>(null), tagPicker = ref<InstanceType<typeof GitLabRefPicker> | null>(null)
const busy = ref(false), error = ref(''), feedback = ref('')
let loadedSection: Tab | undefined, handledPlan: unknown

const projects = computed(() => overview.value.projects)
const configured = computed(() => projects.value.filter(project => project.sites.length))
const pendingProjects = computed(() => projects.value.filter(project => !project.sites.length))
const project = computed(() => projects.value.find(item => item.id === projectId.value))
const siteEntries = computed(() => Object.entries(overview.value.sites))
const siteRows = computed(() => siteEntries.value.filter(([site]) => overviewLevel.value === 'national'
  ? site === 'national' : site !== 'national' && (!overviewSite.value || site === overviewSite.value)))
const overviewProjects = computed(() => configured.value.filter(item => item.level === overviewLevel.value
  && (!overviewNetwork.value || item.network === overviewNetwork.value)
  && item.name.toLowerCase().includes(projectSearch.value.trim().toLowerCase())))
const targets = computed(() => new Map(overview.value.targets.map(item => [`${item.project_id}/${item.site}`, item])))
const historyProjects = computed(() => [...new Map([
  ...overview.value.history_projects.map(row => [row.id, row.name] as const),
  ...projects.value.map(row => [row.id, row.name] as const),
]).entries()])
const visibleMemos = computed(() => memos.value.filter(item => memoStatus.value === 'all' || item.done === (memoStatus.value === 'done')))
function isEditable(plan: Plan) { return plan.status === 'draft' || plan.status === 'ready' }
const editable = computed(() => !!detail.value && isEditable(detail.value))
const kept = computed(() => detail.value?.items.filter(item => !removedIds.value.includes(item.id)) || [])
const checklistChanged = computed(() => detail.value?.items.some(item => item.removed !== removedIds.value.includes(item.id)))
const formTitle = computed(() => mode.value === 'plan' ? '新增升级计划' : mode.value === 'baseline' ? '补录部署基线' : editingMemo.value ? '编辑备忘' : '新增备忘')
const timeFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit',
  day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

function dateText(value: string | null) { return value ? timeFormat.format(new Date(value)) : '未知' }
function dateInput(value: string | null) {
  const date = value ? new Date(value) : new Date()
  return new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 16)
}
function datePayload(value: string) { return value ? `${value}:00+08:00` : null }
function projectName(id: number) { return projects.value.find(row => row.id === id)?.name || `项目 #${id}` }
function siteName(site: string) { return overview.value.sites[site] || site }
function networkName(network: string | null) { return network ? overview.value.networks[network] || network : '待配置' }
function target(project: Project, site: string) { return targets.value.get(`${project.id}/${site}`) }

async function run(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  feedback.value = ''
  try { await work() } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}

async function loadOverview() { overview.value = await api<Overview>('/deployments/overview') }
async function loadHistory() {
  const query = new URLSearchParams({ history: 'true' })
  for (const [key, value] of Object.entries({ project_id: historyProject.value, site: historySite.value,
    network: historyNetwork.value, version: historyVersion.value, start: start.value, end: end.value })) {
    if (value) query.set(key, String(value))
  }
  history.value = await api<Plan[]>(`/deployments/plans?${query}`)
}
async function loadTab() {
  if (tab.value === 'overview') await loadOverview()
  if (tab.value === 'plans') {
    if (historyMode.value) await loadHistory()
    else plans.value = await api<Plan[]>('/deployments/plans')
  }
  if (tab.value === 'memos') memos.value = await api<Memo[]>('/deployments/memos')
}
async function showSection(next: Tab) {
  if (tab.value !== next) await router.push({ name: 'deployments', query: { tab: next } })
  loadedSection = next
  await loadTab()
}
function showPlanList(historical: boolean) {
  if (historyMode.value === historical) return
  historyMode.value = historical
  void run(loadTab)
}
function showHistory(projectId: number, site: string) {
  historyProject.value = projectId; historySite.value = site; historyNetwork.value = ''
  historyVersion.value = ''; start.value = ''; end.value = ''
  historyMode.value = true
  void run(() => showSection('plans'))
}
async function loadRoute() {
  const section = tab.value, plan = route.query.plan
  if (section !== loadedSection) {
    loadedSection = section
    await loadTab()
  }
  if (plan !== handledPlan) {
    handledPlan = plan
    const id = Number(plan)
    if (Number.isSafeInteger(id) && id > 0) await loadDetail(id)
  }
}
onMounted(() => run(async () => {
  await loadOverview()
  loadedSection = 'overview'
  await loadRoute()
}))
watch([tab, () => route.query.plan, busy], () => {
  if (route.name === 'deployments' && !busy.value && (tab.value !== loadedSection || route.query.plan !== handledPlan)) {
    void run(loadRoute)
  }
})

function setDetail(value: Detail, keepSelection = false) {
  const previous = new Map(detail.value?.items.map(item => [item.id, item.removed]))
  const selected = new Set(removedIds.value)
  removedIds.value = value.items.filter(item => keepSelection && previous.get(item.id) === item.removed
    ? selected.has(item.id) : item.removed).map(item => item.id)
  detail.value = value
}
async function loadDetail(id: number) {
  setDetail(await api<Detail>(`/deployments/plans/${id}`))
  await nextTick()
  if (!planDialog.value?.open) planDialog.value?.showModal()
}
function openDetail(id: number) { void run(() => loadDetail(id)) }
function detailAction(path: string, method: string, payload: object, keepSelection = false) {
  void run(async () => {
    const value = await api<Detail>(`/deployments/plans/${detail.value!.id}${path}`, method, payload)
    setDetail(value, keepSelection)
    await loadTab()
  })
}
function complete(planId: number, itemId: number, done: boolean) {
  if (detail.value?.id === planId && planDialog.value?.open) {
    detailAction(`/items/${itemId}`, 'PATCH', { done }, true)
  } else {
    void run(async () => {
      await api(`/deployments/plans/${planId}/items/${itemId}`, 'PATCH', { done })
      await loadTab()
    })
  }
}
function toggleCompletion(event: Event, planId: number, itemId: number, previous: boolean) {
  const input = event.target as HTMLInputElement
  const done = input.checked
  input.checked = previous
  complete(planId, itemId, done)
}
function refreshChecklist() {
  if (!detail.value) return
  const id = detail.value.id
  void run(async () => {
    const path = `/deployments/plans/${id}`
    const latest = await api<Detail>(path)
    setDetail(latest, true)
    if (props.admin && isEditable(latest)) {
      setDetail(await api<Detail>(`${path}/checklist/refresh`, 'POST', { revision: latest.revision }), true)
    }
    await loadTab()
  })
}
function toggleRemoved(item: Item) {
  removedIds.value = removedIds.value.includes(item.id) ? removedIds.value.filter(id => id !== item.id) : [...removedIds.value, item.id]
}
function itemState(item: Item) {
  return removedIds.value.includes(item.id) ? 'removed' : item.done ? 'done' : 'pending'
}
const itemStates = { removed: '本次已移除', done: '已完成', pending: '待检查' }

function showItemInfo(item: Item, event: MouseEvent | FocusEvent) {
  const popup = itemTooltip.value
  const card = (event.currentTarget as HTMLElement).closest('.release-check')
  if (!popup || !card) return
  const rect = card.getBoundingClientRect(), width = Math.min(360, window.innerWidth - 24)
  const below = window.innerHeight - rect.bottom - 8, above = rect.top - 8
  const opensAbove = below < 180 && above > below
  Object.assign(popup.style, {
    left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`, width: `${width}px`,
    top: opensAbove ? 'auto' : `${rect.bottom + 4}px`, bottom: opensAbove ? `${window.innerHeight - rect.top + 4}px` : 'auto',
    maxHeight: `${Math.max(0, Math.min(320, opensAbove ? above : below))}px`,
  })
  tooltipItem.value = item
  if (!popup.matches(':popover-open')) popup.showPopover()
}
function hideItemInfo() {
  if (itemTooltip.value?.matches(':popover-open')) itemTooltip.value.hidePopover()
  tooltipItem.value = null
}
function scrollItemInfo(event: WheelEvent | KeyboardEvent) {
  const popup = itemTooltip.value
  if (!popup?.matches(':popover-open')) return
  const delta = event instanceof WheelEvent ? event.deltaY : event.key === 'ArrowDown' ? 48 : -48
  if (delta > 0 ? popup.scrollTop + popup.clientHeight >= popup.scrollHeight : popup.scrollTop <= 0) return
  event.preventDefault()
  popup.scrollTop += delta
}
onBeforeUnmount(hideItemInfo)

async function openOperation(plan: Plan, next: 'edit' | 'result') {
  operation.value = next; actionPlan.value = plan; error.value = ''
  schedule.value = dateInput(plan.scheduled_at); detailContent.value = plan.upgrade_content
  editNumber.value = plan.version.number
  editBranch.value = plan.version.branch ? { name: plan.version.branch, sha: plan.version.sha || '' } : null
  editTag.value = plan.version.tag ? { name: plan.version.tag, sha: plan.version.tag_sha || '' } : null
  outcome.value = ''; actual.value = dateInput(null)
  await nextTick()
  operationDialog.value?.showModal()
}
function saveOperation() {
  void run(async () => {
    const plan = actionPlan.value
    if (!plan) return
    const path = `/deployments/plans/${plan.id}`
    if (operation.value === 'edit') {
      if (editBranchPicker.value?.hasUnselectedText()) throw new Error('请从 GitLab 查询结果中选择分支，或清空分支')
      if (editTagPicker.value?.hasUnselectedText()) throw new Error('请从 GitLab 查询结果中选择标签，或清空标签')
      const version = { number: editNumber.value, branch: editBranch.value?.name ?? null, sha: editBranch.value?.sha || null,
        tag: editTag.value?.name ?? null, tag_sha: editTag.value?.sha || null }
      const changed = plan.status === 'draft' && (version.number !== plan.version.number || version.branch !== plan.version.branch
        || version.sha !== plan.version.sha || version.tag !== plan.version.tag || version.tag_sha !== plan.version.tag_sha)
      await api(`${path}/schedule`, 'PATCH', { revision: plan.revision, scheduled_at: datePayload(schedule.value), upgrade_content: detailContent.value,
        ...(changed ? { version } : {}) })
    } else if (outcome.value && actual.value) {
      try { await api(`${path}/result`, 'POST', { revision: plan.revision, result: outcome.value, actual_at: datePayload(actual.value) }) }
      catch (cause) { await loadTab(); throw cause }
    } else return
    operationDialog.value?.close()
    await loadTab()
    feedback.value = operation.value === 'edit' ? '计划已修改' : '发版结果已保存'
  })
}
function deletePlan(plan: Plan) {
  if (!window.confirm(`删除${siteName(plan.site)}的升级计划？已派发的检查任务会收回。`)) return
  void run(async () => {
    await api(`/deployments/plans/${plan.id}/cancel`, 'POST', { revision: plan.revision })
    await loadTab()
    feedback.value = '升级计划已删除'
  })
}

function resetVersion() {
  branch.value = null; tag.value = null; number.value = ''
}
async function loadVersions(selectId?: number) {
  versions.value = []
  versionId.value = null
  resetVersion()
  if (mode.value === 'memo' || !projectId.value) return
  versions.value = await api<Version[]>(`/deployments/projects/${projectId.value}/versions`)
  versionId.value = selectId ?? versions.value[0]?.id ?? null
  newVersion.value = !versions.value.length
}
function changeProject() {
  sites.value = (mode.value === 'memo' || project.value?.sites.length === 1) ? [...(project.value?.sites || [])] : []
  void run(() => loadVersions())
}
function openForm(next: FormMode, memo?: Memo) {
  mode.value = next; editingMemo.value = memo?.id ?? null
  projectId.value = memo?.project_id ?? configured.value[0]?.id ?? null
  title.value = memo?.title || ''; notes.value = memo?.notes || ''
  sites.value = memo ? memo.targets.map(item => item.site)
    : (next === 'memo' || project.value?.sites.length === 1) ? [...(project.value?.sites || [])] : []
  timestamp.value = next === 'plan' ? dateInput(null) : ''; upgradeContent.value = ''
  versions.value = []; versionId.value = null; newVersion.value = false; resetVersion()
  editor.value?.showModal()
  void run(async () => {
    if (next !== 'memo') await loadOverview()
    await loadVersions()
  })
}
async function saveForm() {
  await run(async () => {
    const targetSites = project.value?.level === 'national' ? project.value.sites : sites.value
    if (!projectId.value || !targetSites.length) throw new Error('请至少选择一个适用机房')
    const payload = { project_id: projectId.value, sites: targetSites }
    if (mode.value === 'memo') {
      const root = '/deployments/memos'
      await api(editingMemo.value ? `${root}/${editingMemo.value}` : root, editingMemo.value ? 'PUT' : 'POST',
        { ...payload, title: title.value, notes: notes.value })
      await showSection('memos')
      feedback.value = '备忘已保存'
    } else {
      const baseline = mode.value === 'baseline'
      if (newVersion.value) {
        if (branchPicker.value?.hasUnselectedText()) throw new Error('请从 GitLab 查询结果中选择分支，或清空分支')
        if (tagPicker.value?.hasUnselectedText()) throw new Error('请从 GitLab 查询结果中选择标签，或清空标签')
        const saved = await api<Version>(`/deployments/projects/${projectId.value}/${baseline ? 'baseline-versions' : 'versions'}`,
          'POST', { number: number.value, branch: branch.value?.name ?? null, sha: branch.value?.sha ?? null,
            tag: tag.value?.name ?? null, tag_sha: tag.value?.sha ?? null })
        versions.value.unshift(saved); versionId.value = saved.id; newVersion.value = false
      }
      if (!versionId.value) throw new Error('请选择版本')
      const rows = await api<Plan[]>(`/deployments/${baseline ? 'baselines' : 'plans'}`, 'POST', {
        ...payload, version_id: versionId.value, ...(baseline ? { deployed_at: datePayload(timestamp.value) }
          : { scheduled_at: datePayload(timestamp.value), upgrade_content: upgradeContent.value }),
      })
      if (baseline) {
        historyProject.value = projectId.value; historySite.value = ''; historyNetwork.value = ''
        historyVersion.value = ''; start.value = ''; end.value = ''
      }
      historyMode.value = baseline
      await showSection('plans')
      feedback.value = baseline ? `已补录 ${rows.length} 个机房的基线` : `已生成 ${rows.length} 条升级计划`
    }
    editor.value?.close()
  })
}
</script>

<template>
  <section class="panel deployment">
    <p v-if="error" class="review-error" role="alert">{{ error }}</p>
    <p v-if="feedback" role="status">{{ feedback }}</p>

    <template v-if="tab === 'overview'">
      <div class="release-toolbar">
        <label>部署级别<select v-model="overviewLevel"><option value="regional">路局级</option><option value="national">国铁级</option></select></label>
        <label v-if="overviewLevel === 'regional'">铁路局<select v-model="overviewSite"><option value="">全部铁路局</option><option v-for="[id, name] in siteEntries.slice(1)" :key="id" :value="id">{{ name }}</option></select></label>
        <label>部署网络<select v-model="overviewNetwork"><option value="">全部网络</option><option v-for="(name, id) in overview.networks" :key="id" :value="id">{{ name }}</option></select></label>
        <label>项目搜索<input v-model="projectSearch" type="search" placeholder="项目名称" /></label>
        <button v-if="admin" class="primary-button" :disabled="busy || !configured.length" @click="openForm('plan')">新增升级计划</button>
      </div>
      <div v-if="overviewProjects.length" class="release-table release-matrix" tabindex="0" aria-label="项目与机房部署总览">
        <table>
          <thead><tr><th scope="col">部署机房</th><th v-for="entry in overviewProjects" :key="entry.id" scope="col">{{ entry.name }}<small>{{ networkName(entry.network) }}</small></th></tr></thead>
          <tbody>
            <tr v-for="[site, name] in siteRows" :key="site">
              <th scope="row">{{ name }}</th>
              <td v-for="entry in overviewProjects" :key="entry.id">
                <template v-if="target(entry, site)?.current">
                  <button type="button" class="release-link release-version" @click="showHistory(entry.id, site)">{{ target(entry, site)?.current?.version.number }}</button>
                  <small>{{ dateText(target(entry, site)!.current!.deployed_at) }}</small>
                  <a v-if="target(entry, site)?.current?.version.branch" :href="target(entry, site)?.current?.version.branch_url || undefined" target="_blank" rel="noopener noreferrer">{{ target(entry, site)?.current?.version.branch }}</a>
                  <small v-if="target(entry, site)?.current?.version.tag">
                    标签 <a :href="target(entry, site)?.current?.version.tag_url || undefined" target="_blank" rel="noopener noreferrer">{{ target(entry, site)?.current?.version.tag }}</a>
                  </small>
                </template>
                <span v-else class="release-muted">未登记</span>
                <button v-if="target(entry, site)?.planned" class="release-upcoming" @click="openDetail(target(entry, site)!.planned!.id)">
                  计划 {{ target(entry, site)?.planned?.version.number }}<small>{{ dateText(target(entry, site)!.planned!.scheduled_at) }}</small>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">没有符合筛选条件的部署项目</p>
      <details v-if="pendingProjects.length" class="release-unconfigured">
        <summary>{{ pendingProjects.length }} 个项目待配置</summary>
        <p>{{ pendingProjects.map(item => item.name).join('、') }}</p>
        <RouterLink v-if="admin" to="/review-config">前往审查配置</RouterLink>
      </details>
    </template>

    <template v-else-if="tab === 'plans'">
      <div class="release-toolbar">
        <label>计划范围<select :value="historyMode ? 'history' : 'open'" :disabled="busy" @change="showPlanList(($event.target as HTMLSelectElement).value === 'history')">
          <option value="open">待执行</option><option value="history">发版历史</option>
        </select></label>
        <button v-if="admin" class="primary-button" :disabled="busy || !configured.length" @click="openForm('plan')">新增升级计划</button>
        <button v-if="admin" class="secondary-button" :disabled="busy || !configured.length" @click="openForm('baseline')">补录部署基线</button>
      </div>
      <form v-if="historyMode" class="release-toolbar" @submit.prevent="run(loadHistory)">
        <label>项目<select v-model="historyProject"><option value="">全部项目</option><option v-for="[id, name] in historyProjects" :key="id" :value="id">{{ name }}</option></select></label>
        <label>机房<select v-model="historySite"><option value="">全部机房</option><option v-for="[id, name] in siteEntries" :key="id" :value="id">{{ name }}</option></select></label>
        <label>网络<select v-model="historyNetwork"><option value="">全部网络</option><option v-for="(name, id) in overview.networks" :key="id" :value="id">{{ name }}</option></select></label>
        <label>版本号<input v-model.trim="historyVersion" placeholder="x.x.x" /></label>
        <label>起始日期<input v-model="start" type="date" :max="end || undefined" /></label>
        <label>截止日期<input v-model="end" type="date" :min="start || undefined" /></label>
        <button class="secondary-button" :disabled="busy">查询</button>
      </form>
      <div class="release-table" tabindex="0" :aria-label="historyMode ? '发版历史' : '升级计划'">
        <table>
          <thead><tr><th scope="col">项目</th><th scope="col">部署位置</th><th scope="col">目标版本</th><th scope="col">GitLab 分支</th><th scope="col">GitLab 标签</th>
            <th scope="col">{{ historyMode ? '实际发版 / 回滚时间' : '计划时间' }}</th><th scope="col">升级内容</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
          <tbody>
            <tr v-for="row in historyMode ? history : plans" :key="row.id">
              <th scope="row">{{ row.project_name }}</th>
              <td>{{ siteName(row.site) }}<small>{{ networkName(row.network) }}</small></td>
              <td>{{ row.version.number }}<small v-if="row.from_version">从 {{ row.from_version.number }} 升级</small></td>
              <td><a v-if="row.version.branch" :href="row.version.branch_url || undefined" target="_blank" rel="noopener noreferrer">{{ row.version.branch }}</a><span v-else class="release-muted">—</span></td>
              <td><a v-if="row.version.tag" :href="row.version.tag_url || undefined" target="_blank" rel="noopener noreferrer">{{ row.version.tag }}</a><span v-else class="release-muted">—</span></td>
              <td>{{ dateText(historyMode ? row.rolled_back_at || row.deployed_at : row.scheduled_at) }}</td>
              <td><span class="release-upgrade-summary" :title="row.upgrade_content || undefined">{{ row.upgrade_content || '—' }}</span></td>
              <td>{{ states[row.status] }}</td>
              <td><div class="release-row-actions">
                <template v-if="admin && isEditable(row)">
                  <button type="button" class="mini-button release-action-icon" title="修改" aria-label="修改" :disabled="busy" @click="openOperation(row, 'edit')">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5 4 4M4 20l4-.8L20 7l-4-4L4.8 15z" /></svg>
                  </button>
                  <button type="button" class="mini-button release-action-icon danger" title="删除" aria-label="删除" :disabled="busy" @click="deletePlan(row)">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" /></svg>
                  </button>
                </template>
                <span v-if="row.status !== 'baseline'" class="release-check-trigger" :title="row.checklist_count === 0 ? '无需检查' : undefined"
                  :tabindex="row.checklist_count === 0 ? 0 : undefined">
                  <button type="button" class="mini-button" :disabled="busy || row.checklist_count === 0" @click="openDetail(row.id)">备忘检查</button>
                </span>
                <button v-if="admin && isEditable(row)" type="button" class="mini-button release-confirm-button" :disabled="busy || !row.can_confirm"
                  :title="row.can_confirm ? undefined : '先完成清单中的所有保留项'" @click="openOperation(row, 'result')">确认发版</button>
                <span v-if="row.status === 'baseline'" class="release-muted">—</span>
              </div></td>
            </tr>
            <tr v-if="!(historyMode ? history : plans).length"><td colspan="9" class="empty">{{ historyMode ? '暂无符合条件的发版历史' : '暂无待执行的升级计划' }}</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <template v-else>
      <div class="release-toolbar">
        <label>备忘状态<select v-model="memoStatus"><option value="pending">未完成</option><option value="done">已完成</option><option value="all">全部</option></select></label>
        <button class="primary-button" :disabled="busy || !configured.length" @click="openForm('memo')">新增备忘</button>
      </div>
      <p v-if="!visibleMemos.length" class="empty">暂无符合条件的备忘</p>
      <article v-for="memo in visibleMemos" :key="memo.id" class="release-memo">
        <div>
          <h3>{{ memo.title }}</h3>
          <p class="release-muted">{{ projectName(memo.project_id) }} · {{ networkName(memo.network) }} · {{ memo.done ? '已完成' : '未完成' }}<span v-if="memo.version"> · 已归档至 {{ memo.version.number }}</span></p>
          <p v-if="memo.notes" class="release-notes">{{ memo.notes }}</p>
        </div>
        <button v-if="!memo.version" class="mini-button" :disabled="busy || !configured.some(p => p.id === memo.project_id && p.network === memo.network)" @click="openForm('memo', memo)">编辑</button>
        <details>
          <summary>机房进度（{{ memo.targets.filter(item => item.done).length }}/{{ memo.targets.length }}）</summary>
          <div class="release-targets">
            <label v-for="item in memo.targets" :key="item.site">
              <input type="checkbox" :checked="item.done" :disabled="busy || !item.can_complete"
                @change="item.plan_id && item.item_id && toggleCompletion($event, item.plan_id, item.item_id, item.done)" />
              {{ siteName(item.site) }}<small v-if="item.baseline_covered">已由基线覆盖</small><small v-else-if="!item.plan_id">待纳入清单</small>
            </label>
          </div>
        </details>
      </article>
    </template>
  </section>

  <dialog ref="editor" class="review-dialog summary-dialog release-dialog" aria-labelledby="release-editor-title">
    <form class="stack-form" @submit.prevent="saveForm">
      <h2 id="release-editor-title">{{ formTitle }}</h2>
      <label>项目<select v-model="projectId" required :disabled="busy || editingMemo !== null" @change="changeProject">
        <option :value="null" disabled>请选择项目</option><option v-for="item in configured" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select></label>
      <p v-if="project">{{ project.level === 'national' ? '国铁级' : '路局级' }} · {{ networkName(project.network) }}</p>
      <fieldset v-if="project && project.level !== 'national'" class="release-fieldset">
        <legend>部署机房</legend>
        <div v-if="project.sites.length > 1" class="release-choice-actions">
          <button type="button" class="mini-button" :disabled="busy" @click="sites = [...project.sites]">全选</button>
          <button type="button" class="mini-button" :disabled="busy" @click="sites = []">清空</button>
        </div>
        <div class="release-targets">
          <label v-for="site in project.sites" :key="site">
            <input v-model="sites" type="checkbox" :value="site" :disabled="busy" />
            <span>{{ siteName(site) }}</span>
            <span v-if="mode !== 'memo'" class="release-site-version" :class="{ 'release-site-version-empty': !target(project, site)?.current }">{{ target(project, site)?.current?.version.number || '未部署' }}</span>
          </label>
        </div>
      </fieldset>
      <template v-if="mode === 'memo'">
        <label>任务名称<input v-model.trim="title" required maxlength="180" /></label>
        <label>备注<textarea v-model="notes" rows="4" maxlength="5000" placeholder="记录配置修改、SQL 执行或其他上线操作" /></label>
      </template>
      <template v-else>
        <div v-if="versions.length" class="release-choice-actions">
          <button type="button" class="mini-button" :aria-pressed="!newVersion" @click="newVersion = false">使用已有版本</button>
          <button type="button" class="mini-button" :aria-pressed="newVersion" @click="newVersion = true">登记新版本</button>
        </div>
        <div class="release-form-row">
          <label v-if="newVersion">版本号<input v-model.trim="number" type="text" placeholder="x.x.x" pattern="(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)" required maxlength="40" /></label>
          <label v-else>版本号<select v-model="versionId" required><option :value="null" disabled>请选择版本</option><option v-for="item in versions" :key="item.id" :value="item.id">{{ [item.number, item.branch, item.tag].filter(Boolean).join(' · ') }}</option></select></label>
          <label>{{ mode === 'plan' ? '计划时间（北京时间）' : '实际上线时间（北京时间，选填）' }}
            <input v-model="timestamp" type="datetime-local" :required="mode === 'plan'" />
          </label>
        </div>
        <div v-if="newVersion && projectId" class="release-form-row">
            <GitLabRefPicker :key="`branch-${projectId}`" ref="branchPicker" v-model="branch" :project-id="projectId" kind="branches" :disabled="busy" />
            <GitLabRefPicker :key="`tag-${projectId}`" ref="tagPicker" v-model="tag" :project-id="projectId" kind="tags" :disabled="busy" />
        </div>
        <label v-if="mode === 'plan'">升级内容<textarea v-model="upgradeContent" rows="4" wrap="soft" maxlength="5000" /></label>
      </template>
      <p v-if="error" class="review-error" role="alert">{{ error }}</p>
      <div class="top-actions"><button type="button" class="secondary-button" @click="editor?.close()">关闭</button><button class="primary-button" :disabled="busy || !projectId">保存</button></div>
    </form>
  </dialog>

  <dialog ref="planDialog" class="review-dialog summary-dialog release-dialog release-check-dialog" aria-labelledby="release-detail-title" @close="hideItemInfo" @scroll="hideItemInfo">
    <section v-if="detail" class="stack-form">
      <header class="release-dialog-header"><h2 id="release-detail-title">备忘检查清单</h2><button type="button" class="mini-button release-dialog-close" aria-label="关闭" @click="planDialog?.close()">×</button></header>
      <div class="release-check-summary"><p>{{ detail.project_name }} · {{ siteName(detail.site) }} · {{ detail.version.number }}</p><strong>{{ kept.filter(item => item.done).length }} / {{ kept.length }} 已完成</strong></div>
      <p v-if="!detail.items.length" class="release-muted">此机房暂无适用的发版备忘</p>
      <div v-else class="release-check-grid">
        <article v-for="item in detail.items" :key="item.id" class="release-check" :class="`release-check-${itemState(item)}`"
          @mouseenter="showItemInfo(item, $event)" @mouseleave="hideItemInfo">
          <span class="release-check-state" :aria-label="itemStates[itemState(item)]" role="img">{{ { removed: '⊘', done: '✓', pending: '◷' }[itemState(item)] }}</span>
          <div class="release-check-copy" tabindex="0" :aria-describedby="tooltipItem?.id === item.id ? 'release-item-tooltip' : undefined"
            @focus="showItemInfo(item, $event)" @blur="hideItemInfo" @wheel="scrollItemInfo"
            @keydown.up="scrollItemInfo" @keydown.down="scrollItemInfo">
            <strong>{{ item.title }}</strong>
            <small>{{ item.author }}<span v-if="item.source_version"> · {{ item.source_version }}</span></small>
            <p>{{ item.notes || '—' }}</p>
          </div>
          <div v-if="editable" class="release-check-actions">
            <button v-if="admin || item.can_complete" type="button" class="mini-button" :disabled="busy || !item.can_complete || !item.dispatched || itemState(item) === 'removed'"
              @click="complete(detail.id, item.id, !item.done)">{{ item.done ? '标记为未完成' : '标记已完成' }}</button>
            <button v-if="admin" type="button" class="mini-button" :disabled="busy" @click="toggleRemoved(item)">{{ itemState(item) === 'removed' ? '取消移除' : '本次移除' }}</button>
          </div>
        </article>
      </div>
      <p v-if="error" class="review-error" role="alert">{{ error }}</p>
      <div class="top-actions">
        <button type="button" class="secondary-button" :disabled="busy" @click="refreshChecklist">刷新</button>
        <button v-if="admin && editable" type="button" class="primary-button" :disabled="busy || (detail.status === 'ready' && !checklistChanged && kept.every(item => item.dispatched))"
          @click="detailAction('/checklist', 'PUT', { revision: detail.revision, removed_ids: removedIds })">确认清单并派发</button>
      </div>
    </section>
    <aside id="release-item-tooltip" ref="itemTooltip" popover="manual" role="tooltip" class="release-item-tooltip">
      <template v-if="tooltipItem">
        <strong>{{ tooltipItem.title }}</strong>
        <small>创建人 {{ tooltipItem.author }}<span v-if="tooltipItem.source_version"> · 来源版本 {{ tooltipItem.source_version }}</span></small>
        <small>{{ itemStates[itemState(tooltipItem)] }} · {{ tooltipItem.dispatched ? '已派发' : '未派发' }}</small>
        <p class="release-notes">{{ tooltipItem.notes || '无备注' }}</p>
      </template>
    </aside>
  </dialog>

  <dialog ref="operationDialog" class="review-dialog summary-dialog release-dialog" aria-labelledby="release-operation-title" @close="actionPlan = null">
    <form v-if="actionPlan" class="stack-form" @submit.prevent="saveOperation">
      <header class="release-dialog-header"><h2 id="release-operation-title">{{ operation === 'edit' ? '修改升级计划' : '确认发版' }}</h2><button type="button" class="mini-button release-dialog-close" aria-label="关闭" @click="operationDialog?.close()">×</button></header>
      <p>{{ actionPlan.project_name }} · {{ siteName(actionPlan.site) }} · {{ actionPlan.version.number }}</p>
      <template v-if="operation === 'edit'">
        <div class="release-form-row">
          <label v-if="actionPlan.status === 'draft'">版本号<input v-model.trim="editNumber" type="text" pattern="(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)" maxlength="40" required /></label>
          <label>计划时间（北京时间）<input v-model="schedule" type="datetime-local" required /></label>
        </div>
        <div v-if="actionPlan.status === 'draft'" class="release-form-row">
          <GitLabRefPicker ref="editBranchPicker" v-model="editBranch" :project-id="actionPlan.project_id" kind="branches" :disabled="busy" />
          <GitLabRefPicker ref="editTagPicker" v-model="editTag" :project-id="actionPlan.project_id" kind="tags" :disabled="busy" />
        </div>
        <label>升级内容<textarea v-model="detailContent" rows="4" wrap="soft" maxlength="5000" /></label>
      </template>
      <template v-else>
        <fieldset class="release-fieldset release-outcomes">
          <legend>发版结果</legend>
          <label><input v-model="outcome" type="radio" name="release-outcome" value="succeeded" required />发版成功</label>
          <label><input v-model="outcome" type="radio" name="release-outcome" value="failed" required />发版失败</label>
        </fieldset>
        <label>{{ outcome === 'failed' ? '实际回滚时间（北京时间）' : '实际发版时间（北京时间）' }}<input v-model="actual" type="datetime-local" required /></label>
      </template>
      <p v-if="error" class="review-error" role="alert">{{ error }}</p>
      <div class="top-actions"><button class="primary-button" :disabled="busy || (operation === 'result' && !outcome)">保存</button></div>
    </form>
  </dialog>
</template>

<style scoped>
.deployment { min-width: 0; max-width: none; }
.release-toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: .75rem; margin-block: .5rem 1rem; }
.release-toolbar label { display: grid; gap: .25rem; }
.release-toolbar input, .release-toolbar select { max-width: 14rem; }
.release-table { max-width: 100%; overflow: auto; }
.release-table table { width: 100%; border-collapse: separate; border-spacing: 0; text-align: left; }
.release-table th, .release-table td { border-bottom: 1px solid var(--line, #cbd5e1); padding: .75rem; vertical-align: top; }
.release-matrix :is(td, th[scope="col"]) { min-width: 9rem; }
.release-matrix th:first-child { position: sticky; left: 0; z-index: 1; background: var(--panel, Canvas); min-width: 10rem; }
.release-table small { display: block; }
.release-table a { overflow-wrap: anywhere; }
.release-muted, small { color: var(--muted, #596579); }
.release-link { cursor: pointer; text-align: left; background: none; padding: 0; border: 0; color: var(--primary, #135ab1); text-decoration: underline; }
.release-version { font-size: 1rem; font-weight: 700; }
.release-upcoming { display: block; margin-top: .5rem; padding: .25rem .4rem; text-align: left; border: 1px solid var(--line, #cbd5e1); border-radius: .35rem; cursor: pointer; }
.release-unconfigured { margin-top: 1rem; }
.release-memo { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .5rem; align-items: start; border-top: 1px solid var(--line, #cbd5e1); padding-block: .85rem; }
.release-memo details { grid-column: 1 / -1; }
.release-memo p, .release-memo h3 { margin-block: .2rem; }
.release-notes { white-space: pre-wrap; overflow-wrap: anywhere; }
.release-targets { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr)); gap: .5rem; margin-block: .5rem; }
.release-targets label { display: flex; align-items: center; gap: .35rem; }
.release-targets label { flex-wrap: wrap; }
.release-targets label input, .release-outcomes input { width: auto; }
.release-site-version { border-radius: .25rem; padding: .12rem .35rem; background: #e7f2ff; color: #244f80; font-size: .72rem; overflow-wrap: anywhere; }
.release-site-version-empty { background: #eef0f3; color: #52606e; }
.release-form-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: .75rem; }
.release-form-row label { min-width: 0; }
.release-dialog { width: min(46rem, calc(100vw - 2rem)); max-height: calc(100dvh - 2rem); overflow: auto; }
.release-dialog .release-toolbar { margin: 0; }
.release-fieldset { border: 1px solid var(--line, #cbd5e1); border-radius: .5rem; padding: .5rem .75rem; }
.release-choice-actions { display: flex; gap: .5rem; }
.release-upgrade-summary { display: block; max-width: 12rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.release-row-actions { display: flex; flex-wrap: wrap; gap: .45rem; min-width: 12rem; }
.release-check-trigger { display: inline-flex; }
.release-check-trigger[title] button { pointer-events: none; }
.release-action-icon, .release-dialog-close { display: inline-grid; place-items: center; width: 34px; height: 34px; padding: 0; }
.release-action-icon svg { width: 16px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.release-confirm-button:enabled { background: #ccff00; }
.release-dialog-header, .release-check-summary { display: flex; justify-content: space-between; align-items: center; gap: .75rem; }
.release-dialog-header h2, .release-check-summary p { margin: 0; }
.release-dialog-close { flex: none; font-size: 1.35rem; line-height: 1; }
.release-check-summary { align-items: baseline; flex-wrap: wrap; }
.release-check-summary strong { color: #315838; }
.release-check-dialog { width: min(54rem, calc(100vw - 2rem)); }
.release-check-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; }
.release-check {
  position: relative; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: .6rem;
  min-width: 0; height: 7.75rem; padding: .75rem .75rem .75rem 2.65rem;
  border: 1px solid #cad6e0; border-radius: .65rem; background: #fff;
}
.release-check-done { border-color: #95c6a3; background: #f4fbf5; }
.release-check-removed { border-color: #d5d8de; background: #f0f1f3; color: #59606d; }
.release-check-removed .release-check-copy strong { text-decoration: line-through; }
.release-check-state {
  position: absolute; top: .7rem; left: .7rem; display: grid; place-items: center;
  width: 1.5rem; height: 1.5rem; border-radius: 50%; background: #e8eef5; color: #354e69; font-weight: 900;
}
.release-check-done .release-check-state { background: #dbf2e1; color: #126129; }
.release-check-removed .release-check-state { background: #dfe2e7; color: #59606d; }
.release-check-copy { min-width: 0; overflow: hidden; }
.release-check-copy strong, .release-check-copy small, .release-check-copy p { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.release-check-copy p { margin: .4rem 0 0; color: #52606e; }
.release-check-actions { display: grid; gap: .6rem; }
.release-item-tooltip {
  position: fixed; inset: auto; margin: 0; padding: .75rem; overflow: auto; pointer-events: none;
  border: 1px solid #aeb9c6; border-radius: .55rem; background: #fff; color: #182334; box-shadow: 0 4px 14px #18233430;
  overflow-wrap: anywhere;
}
.release-item-tooltip small { display: block; margin-top: .25rem; }
.release-item-tooltip p { margin: .5rem 0 0; }
.release-outcomes { display: flex; gap: .9rem; flex-wrap: wrap; }
.release-outcomes label { display: flex; align-items: center; gap: .35rem; }
@media (max-width: 660px) { .release-check-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 480px) { .release-form-row { grid-template-columns: minmax(0, 1fr); } }
</style>
