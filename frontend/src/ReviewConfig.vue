<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, credentialApi } from './api'

const props = defineProps<{ accountId: number }>()
interface ProjectInput {
  name: string; alias: string; url: string
  gitlab_url: string | null; gitlab_id: number | null; skip_slash_branches: boolean
}
type Project = ProjectInput & { id: number; is_common: boolean }
interface GitLabProject {
  id: number; name: string; web_url: string; path_with_namespace: string
}
const blankProject = (): ProjectInput => ({ name: '', alias: '', url: '', gitlab_url: null, gitlab_id: null, skip_slash_branches: true })
const projects = ref<Project[]>([]), discovered = ref<GitLabProject[]>([]), selected = ref<number[]>([])
const left = ref<number[]>([]), right = ref<number[]>([]), search = ref(''), discoveredBase = ref('')
const editing = ref<Project | null>(null), editor = ref<HTMLDialogElement | null>(null)
const draft = reactive(blankProject())
const connection = reactive({ url: '', username: '', password: '', token: '', mode: 'token' })
const busy = ref(false), error = ref(''), feedback = ref('')
const storageKey = `zhoubao.review.gitlab.${props.accountId}`
const relevant = computed(() => discovered.value.filter(item => item.path_with_namespace.toLowerCase().includes(search.value.trim().toLowerCase())))
const available = computed(() => relevant.value.filter(item => !selected.value.includes(item.id)))
const included = computed(() => relevant.value.filter(item => selected.value.includes(item.id)))
function matches(saved: Project, item: GitLabProject) {
  return (saved.gitlab_url === discoveredBase.value && saved.gitlab_id === item.id)
    || saved.url === item.web_url.replace(/\/$/, '')
}
function syncSelection() {
  selected.value = discovered.value.filter(item => projects.value.some(saved => matches(saved, item))).map(item => item.id)
  left.value = []; right.value = []
}
async function perform(action: () => Promise<void>) {
  busy.value = true; error.value = ''; feedback.value = ''
  try { await action() } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}
onMounted(() => {
  try { Object.assign(connection, JSON.parse(localStorage.getItem(storageKey) || '{}')) } catch { /* 浏览器存储可能被禁用。 */ }
  void perform(async () => { projects.value = await api<Project[]>('/reviews/projects') })
})
async function directProjects(base: string, credentials: { token: string; username: string; password: string }) {
  if (new URL(base).protocol !== 'https:') throw new Error('HTTP 地址需要使用 GitLab 中转')
  let headers: Record<string, string> = { 'PRIVATE-TOKEN': credentials.token }
  if (!credentials.token) {
    const body = new URLSearchParams({ grant_type: 'password', username: credentials.username, password: credentials.password, scope: 'read_api' })
    const response = await fetch(`${base}/oauth/token`, { method: 'POST', body, redirect: 'error', credentials: 'omit' })
    if (!response.ok) throw new Error('GitLab 用户名或密码验证失败')
    const data = await response.json()
    headers = { Authorization: `Bearer ${data.access_token}` }
  }
  return readPages(async page => {
    const response = await fetch(`${base}/api/v4/projects?per_page=100&order_by=id&sort=asc&page=${page}`, { headers, redirect: 'error', credentials: 'omit' })
    if (!response.ok) throw new Error(`GitLab 项目列表请求失败（${response.status}）`)
    return response.json()
  })
}
async function readPages(fetchPage: (page: number) => Promise<GitLabProject[]>) {
  const result = new Map<number, GitLabProject>()
  for (let page = 1; ; page++) {
    const items = await fetchPage(page)
    if (!Array.isArray(items)) throw new Error('GitLab 项目列表格式异常')
    const size = result.size
    for (const item of items) result.set(item.id, item)
    if (items.length < 100) return [...result.values()]
    if (result.size === size) throw new Error('GitLab 返回了重复的项目分页')
  }
}
function refresh() {
  void perform(async () => {
    const address = new URL(connection.url.trim())
    if (!['https:', 'http:'].includes(address.protocol) || address.username || address.password || address.search || address.hash) throw new Error('请输入不含凭据的 GitLab 地址')
    const base = address.href.replace(/\/+$/, '')
    const credentials = connection.mode === 'token' ? { token: connection.token, username: '', password: '' }
      : { token: '', username: connection.username, password: connection.password }
    if (!credentials.token && (!credentials.username || !credentials.password)) throw new Error('请填写 GitLab 访问令牌或用户名和密码')
    let result: GitLabProject[]
    try { result = await directProjects(base, credentials) }
    catch { result = await readPages(page => credentialApi('/reviews/gitlab/projects', { ...credentials, url: base, page })) }
    discovered.value = result
    discoveredBase.value = base
    syncSelection()
    feedback.value = `已获取 ${result.length} 个可访问项目`
    try { localStorage.setItem(storageKey, JSON.stringify({ ...credentials, url: base, mode: connection.mode })) }
    catch { feedback.value += '，浏览器存储不可用，登录资料仅保留在本页。' }
  })
}
function move(add: boolean) {
  selected.value = add ? [...new Set([...selected.value, ...left.value])] : selected.value.filter(id => !right.value.includes(id))
  left.value = []; right.value = []
}
function saveSelection() {
  void perform(async () => {
    const removed_ids: number[] = [], added: ProjectInput[] = []
    for (const item of discovered.value) {
      const saved = projects.value.find(project => matches(project, item))
      if (!selected.value.includes(item.id)) {
        if (saved) removed_ids.push(saved.id)
      } else if (!saved) {
        added.push({ ...blankProject(), name: item.name, url: item.web_url, gitlab_url: discoveredBase.value, gitlab_id: item.id })
      }
    }
    projects.value = await api<Project[]>('/reviews/projects', 'PUT', { removed_ids, projects: added })
    syncSelection(); feedback.value = '已保存审查项目'
  })
}
function openProject(project?: Project) {
  editing.value = project || null
  const { name, alias, url, gitlab_url, gitlab_id, skip_slash_branches } = project || blankProject()
  Object.assign(draft, { name, alias, url, gitlab_url, gitlab_id, skip_slash_branches })
  editor.value?.showModal()
}
function saveProject() {
  const id = editing.value?.id
  void perform(async () => {
    await api(id ? `/reviews/projects/${id}` : '/reviews/projects', id ? 'PUT' : 'POST', draft)
    projects.value = await api<Project[]>('/reviews/projects')
    syncSelection(); editor.value?.close(); feedback.value = '已保存审查项目'
  })
}
function toggleCommon(project: Project) {
  void perform(async () => {
    const saved = await api<Project>(`/reviews/projects/${project.id}`, 'PATCH', { is_common: !project.is_common })
    project.is_common = saved.is_common
  })
}
function removeProject(project: Project) {
  if (!window.confirm(`删除审查项目「${project.alias}」？`)) return
  void perform(async () => {
    await api(`/reviews/projects/${project.id}`, 'DELETE')
    projects.value = projects.value.filter(item => item.id !== project.id)
    syncSelection(); feedback.value = '已删除审查项目'
  })
}
</script>

<template>
  <section class="panel review-panel">
    <h2>GitLab 连接</h2>
    <form class="review-form" @submit.prevent="refresh">
      <label>GitLab 地址<input v-model="connection.url" type="url" placeholder="https://gitlab.example.com" required /></label>
      <label>登录方式<select v-model="connection.mode"><option value="token">访问令牌</option><option value="password">用户名和密码</option></select></label>
      <label v-if="connection.mode === 'token'">访问令牌<input v-model="connection.token" type="password" autocomplete="off" required /></label>
      <template v-else>
        <label>GitLab 用户名<input v-model="connection.username" required /></label>
        <label>GitLab 密码<input v-model="connection.password" type="password" autocomplete="off" required /></label>
      </template>
      <button class="secondary-button" :disabled="busy">刷新项目</button>
    </form>
    <p role="status" v-if="feedback">{{ feedback }}</p><p class="review-error" role="alert" v-if="error">{{ error }}</p>
    <div v-if="discoveredBase" class="review-transfer">
      <label>搜索 GitLab 项目<input v-model="search" type="search" placeholder="项目路径" /></label>
      <div class="review-transfer-grid">
        <label>可选项目（{{ available.length }}）<select v-model="left" multiple size="8"><option v-for="item in available" :key="item.id" :value="item.id">{{ item.path_with_namespace }}</option></select></label>
        <div class="review-transfer-actions">
          <button class="mini-button" type="button" :disabled="busy || !left.length" @click="move(true)">加入 →</button>
          <button class="mini-button" type="button" :disabled="busy || !right.length" @click="move(false)">← 移除</button>
        </div>
        <label>已选项目（{{ selected.length }}）<select v-model="right" multiple size="8"><option v-for="item in included" :key="item.id" :value="item.id">{{ item.path_with_namespace }}</option></select></label>
      </div>
      <button class="primary-button" type="button" :disabled="busy" @click="saveSelection">保存项目选择</button>
    </div>
  </section>
  <section class="panel review-panel">
    <div class="review-panel-head"><h2>审查项目</h2><button class="primary-button" type="button" :disabled="busy" @click="openProject()">＋ 手动新增</button></div>
    <div v-for="project in projects" :key="project.id" class="review-project">
      <div><strong>{{ project.alias }}</strong><p>{{ project.name }}</p><a :href="project.url" target="_blank" rel="noopener noreferrer">{{ project.url }}</a><p>分支范围：{{ project.skip_slash_branches ? '只审查名称不含 / 的分支' : '所有分支' }}</p></div>
      <div class="top-actions">
        <button class="mini-button" type="button" :disabled="busy" @click="toggleCommon(project)">{{ project.is_common ? '取消常用' : '设为常用' }}</button>
        <button class="mini-button" type="button" :disabled="busy" @click="openProject(project)">编辑</button>
        <button class="mini-button danger" type="button" :disabled="busy" @click="removeProject(project)">删除</button>
      </div>
    </div>
    <p v-if="!projects.length" class="empty">暂无审查项目</p>
  </section>
  <dialog ref="editor" class="review-dialog">
    <form class="stack-form" @submit.prevent="saveProject">
      <h2>{{ editing ? '编辑审查项目' : '手动新增审查项目' }}</h2>
      <label>项目名称<input v-model="draft.name" maxlength="250" required /></label>
      <label>项目别名<input v-model="draft.alias" maxlength="250" :placeholder="draft.name || '默认使用项目名称'" /></label>
      <label>项目 URL<input v-model="draft.url" type="url" maxlength="1000" required /></label>
      <label class="review-checkbox"><input v-model="draft.skip_slash_branches" type="checkbox" />只审查名称不含 / 的分支</label>
      <p class="review-error" v-if="error" role="alert">{{ error }}</p>
      <div class="top-actions"><button type="button" class="secondary-button" @click="editor?.close()">取消</button><button class="primary-button" :disabled="busy">保存项目</button></div>
    </form>
  </dialog>
</template>
