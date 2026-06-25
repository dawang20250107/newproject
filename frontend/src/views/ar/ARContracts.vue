<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import { useToast } from '../../composables/useToast.js'

const auth = useAuthStore()
const toast = useToast()
const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = 50

const filters = reactive({ q: '', dept: '' })
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

const showModal = ref(false)
const editItem = ref(null)
const saving = ref(false)
const form = reactive({
  name: '', contract_no: '', delivery_dept: '', sign_date: '', amount: '', notes: '',
})
// 关联客户：[{customer_id, customer_name, role, share}]
const parties = ref([])
// 关联项目：[{project_id, project_no, short_name, is_primary}]
const projects = ref([])

// 客户池（一次性加载，供下拉添加）
const customers = ref([])
const newPartyCustomerId = ref('')
// 项目搜索添加
const projQuery = ref('')
const projResults = ref([])
let projTimer = null

function fmtNum(v) {
  if (v === null || v === undefined || v === '') return '—'
  return (parseFloat(v) || 0).toLocaleString('zh-CN')
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const res = await ar.listContracts({ ...filters, page: page.value, size })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 280)
}

const hasActiveFilters = computed(() => !!(filters.q || filters.dept))
function resetFilters() { filters.q = ''; filters.dept = ''; load(true) }

async function loadCustomers() {
  try {
    const res = await ar.listCustomers({ size: 200 })
    customers.value = res.data.items
  } catch { customers.value = [] }
}

// ── 客户关联 ──────────────────────────────────────────────────────────────
const availableCustomers = computed(() => {
  const used = new Set(parties.value.map(p => p.customer_id))
  return customers.value.filter(c => !used.has(c.id))
})
function addParty() {
  const cid = parseInt(newPartyCustomerId.value)
  if (!cid) return
  const c = customers.value.find(x => x.id === cid)
  if (!c) return
  parties.value.push({ customer_id: cid, customer_name: c.name, role: 'main', share: '' })
  newPartyCustomerId.value = ''
}
function removeParty(i) { parties.value.splice(i, 1) }

// ── 项目关联 ──────────────────────────────────────────────────────────────
function onProjSearch() {
  clearTimeout(projTimer)
  projTimer = setTimeout(doProjSearch, 280)
}
async function doProjSearch() {
  const q = projQuery.value.trim()
  if (!q) { projResults.value = []; return }
  try {
    const params = { q, size: 10 }
    if (form.delivery_dept) params.dept = form.delivery_dept
    const res = await ar.listProjects(params)
    const used = new Set(projects.value.map(p => p.project_id))
    projResults.value = res.data.items.filter(p => !used.has(p.id))
  } catch { projResults.value = [] }
}
function addProject(p) {
  projects.value.push({ project_id: p.id, project_no: p.project_no,
    short_name: p.short_name, is_primary: true })
  projResults.value = projResults.value.filter(x => x.id !== p.id)
  projQuery.value = ''
}
function removeProject(i) { projects.value.splice(i, 1) }

// ── 增改删 ────────────────────────────────────────────────────────────────
function openCreate() {
  editItem.value = null
  Object.assign(form, { name: '', contract_no: '', delivery_dept: accessibleDepts.value[0] || '',
    sign_date: '', amount: '', notes: '' })
  parties.value = []
  projects.value = []
  projQuery.value = ''; projResults.value = []
  showModal.value = true
}

async function openEdit(item) {
  editItem.value = item
  Object.assign(form, {
    name: item.name, contract_no: item.contract_no || '',
    delivery_dept: item.delivery_dept || '', sign_date: item.sign_date || '',
    amount: item.amount ?? '', notes: item.notes || '',
  })
  parties.value = []
  projects.value = []
  projQuery.value = ''; projResults.value = []
  showModal.value = true
  // 拉取关联明细
  try {
    const res = await ar.getContract(item.id)
    const d = res.data
    parties.value = (d.parties || []).map(p => ({
      customer_id: p.customer_id, customer_name: p.customer_name,
      role: p.role || 'main', share: p.share ?? '' }))
    projects.value = (d.projects || []).map(p => ({
      project_id: p.project_id, project_no: p.project_no,
      short_name: p.short_name, is_primary: p.is_primary }))
  } catch { /* 保持空 */ }
}

async function save() {
  if (!form.name.trim()) { alert('请填写合同名称'); return }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      contract_no: form.contract_no.trim(),
      delivery_dept: form.delivery_dept,
      sign_date: form.sign_date || null,
      amount: form.amount === '' ? null : form.amount,
      notes: form.notes.trim(),
      parties: parties.value.map(p => ({
        customer_id: p.customer_id, role: p.role,
        share: p.share === '' ? null : p.share })),
      projects: projects.value.map(p => ({
        project_id: p.project_id, is_primary: p.is_primary })),
    }
    if (editItem.value) await ar.updateContract(editItem.value.id, payload)
    else await ar.createContract(payload)
    showModal.value = false
    load(editItem.value ? false : true)
  } catch (e) {
    alert(e?.msg || e?.error || '保存失败，请检查必填项与部门权限')
  } finally { saving.value = false }
}

async function remove(item) {
  if (!confirm(`确定删除合同「${item.name}」？\n（仅删除合同及其关联关系，不影响客户与项目本体）`)) return
  try { await ar.deleteContract(item.id); load() }
  catch (e) { alert(e?.msg || '删除失败') }
}

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const ctx = useContextMenu()
const ROW_COPY_COLS = [
  { key: 'name', label: '合同名称' },
  { key: 'contract_no', label: '合同编号' },
  { key: 'delivery_dept', label: '交付部门' },
  { key: 'sign_date', label: '签订日期' },
  { key: 'amount', label: '合同额', format: v => fmtNum(v) },
  { key: 'party_count', label: '关联方数' },
  { key: 'project_count', label: '关联项目数' },
]
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}
async function copyWholeRow(c) {
  const ok = await copyRowTSV(c, ROW_COPY_COLS, { header: true })
  ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')
}
const ctxItems = computed(() => {
  const c = ctx.menu.payload
  if (!c) return []
  return [
    { key: 'edit', label: '编辑 / 维护关联', icon: 'edit', shortcut: 'E', action: r => openEdit(r) },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: r => copyWholeRow(r) },
        { divider: true },
        { key: 'copy-name', label: '合同名称', icon: 'cell', action: r => copyField(r.name, r.name) },
        { key: 'copy-no', label: '合同编号', icon: 'invoice', hidden: !c.contract_no, action: r => copyField(r.contract_no, r.contract_no) },
      ],
    },
    { divider: true },
    { key: 'del', label: '删除合同', icon: 'trash', danger: true, hidden: !auth.canDelete, action: r => remove(r) },
  ]
})

function onRowDblClick(item, e) {
  if (e.target.closest('input, button, select, textarea, a')) return
  if (!auth.canArWrite) return
  openEdit(item)
}

const onScopeChange = () => {
  if (filters.dept && !accessibleDepts.value.includes(filters.dept)) filters.dept = ''
  page.value = 1
  load()
}
onMounted(() => {
  load(); loadCustomers()
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>合同管理</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          合同 · 多客户（主/次 + 分成）· 多项目关联 — 支持一个合同多客户多项目、一个项目挂多个合同
        </div>
      </div>
      <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" @click="openCreate">+ 新增合同</button>
    </div>

    <!-- Filter strip -->
    <div class="filter-strip">
      <div class="search-box">
        <input v-model="filters.q" class="search-input" placeholder="搜索合同名称 / 合同编号"
               @input="onSearchInput" @keyup.enter="load(true)" />
        <button v-if="filters.q" class="search-clear" @click="filters.q=''; load(true)">✕</button>
      </div>
      <select v-model="filters.dept" class="sel-bu" @change="load(true)">
        <option value="">全部事业部</option>
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
      <button v-if="hasActiveFilters" class="filter-reset" @click="resetFilters">重置筛选</button>
    </div>

    <!-- Table -->
    <div class="card fh-fill" :class="{ 'data-reloading': loading && items.length }">
      <div class="table-wrap page-scroll">
        <table class="ct-table">
          <thead>
            <tr>
              <th>合同名称</th>
              <th>合同编号</th>
              <th>交付部门</th>
              <th class="ctr">签订日期</th>
              <th class="rgt">合同金额</th>
              <th class="ctr">客户数</th>
              <th class="ctr">项目数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length"><td colspan="7" class="empty-cell">⏳ 加载中…</td></tr>
            <tr v-else-if="!items.length"><td colspan="7" class="empty-cell">暂无合同，点击「新增合同」开始</td></tr>
            <tr v-for="c in items" :key="c.id" class="data-row" @contextmenu.prevent="ctx.open($event, c)" @dblclick="onRowDblClick(c, $event)">
              <td class="ct-name">{{ c.name }}</td>
              <td class="text-muted mono">{{ c.contract_no || '—' }}</td>
              <td><span class="dept-chip">{{ c.delivery_dept || '—' }}</span></td>
              <td class="ctr text-sm">{{ c.sign_date || '—' }}</td>
              <td class="rgt mono">{{ fmtNum(c.amount) }}</td>
              <td class="ctr"><span class="cnt-chip">{{ c.party_count }}</span></td>
              <td class="ctr"><span class="cnt-chip">{{ c.project_count }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
      </div>
    </div>

    <!-- Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal=false">
        <div class="modal-box" style="max-width:760px">
          <div class="modal-header">
            <h3>{{ editItem ? '编辑合同' : '新增合同' }}</h3>
            <button class="modal-close" @click="showModal=false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2"><span>合同名称 <em>*</em></span>
                <input v-model="form.name" placeholder="合同全称" /></label>
              <label class="form-field"><span>合同编号</span>
                <input v-model="form.contract_no" placeholder="可选" /></label>
              <label class="form-field"><span>交付部门</span>
                <select v-model="form.delivery_dept">
                  <option value="">（不限）</option>
                  <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
                </select></label>
              <label class="form-field"><span>签订日期</span>
                <input v-model="form.sign_date" type="date" /></label>
              <label class="form-field"><span>合同金额（元）</span>
                <input v-model="form.amount" placeholder="可选，纯数字" /></label>
              <label class="form-field span2"><span>备注</span>
                <input v-model="form.notes" placeholder="可选" /></label>
            </div>

            <!-- 客户关联 -->
            <div class="link-section">
              <div class="link-head">
                <span class="link-title">关联客户</span>
                <span class="link-sub">一个合同可挂多个客户，标主/次并可填分成比例</span>
              </div>
              <div class="add-row">
                <select v-model="newPartyCustomerId" class="add-sel">
                  <option value="">+ 选择客户加入…</option>
                  <option v-for="c in availableCustomers" :key="c.id" :value="c.id">{{ c.name }}</option>
                </select>
                <button class="btn btn-ghost btn-sm" :disabled="!newPartyCustomerId" @click="addParty">添加</button>
              </div>
              <div v-if="!parties.length" class="link-empty">尚未关联客户</div>
              <div v-for="(p, i) in parties" :key="p.customer_id" class="link-chip">
                <span class="chip-name">{{ p.customer_name }}</span>
                <select v-model="p.role" class="chip-sel">
                  <option value="main">主客户</option>
                  <option value="sub">次客户</option>
                </select>
                <input v-model="p.share" class="chip-share" placeholder="分成%" />
                <button class="chip-x" @click="removeParty(i)">✕</button>
              </div>
            </div>

            <!-- 项目关联 -->
            <div class="link-section">
              <div class="link-head">
                <span class="link-title">关联项目</span>
                <span class="link-sub">一个合同可对多个项目；一个项目也能挂多个合同</span>
              </div>
              <div class="add-row">
                <input v-model="projQuery" class="add-sel" placeholder="搜索项目简称/编号加入…" @input="onProjSearch" />
              </div>
              <div v-if="projResults.length" class="proj-results">
                <div v-for="p in projResults" :key="p.id" class="proj-result" @click="addProject(p)">
                  <span class="mono">{{ p.project_no }}</span> · {{ p.short_name }}
                  <span class="text-muted">（{{ p.delivery_dept }}）</span>
                  <span class="add-hint">+ 添加</span>
                </div>
              </div>
              <div v-if="!projects.length" class="link-empty">尚未关联项目</div>
              <div v-for="(p, i) in projects" :key="p.project_id" class="link-chip">
                <span class="mono">{{ p.project_no }}</span>
                <span class="chip-name">{{ p.short_name }}</span>
                <label class="chip-primary"><input type="checkbox" v-model="p.is_primary" /> 主合同</label>
                <button class="chip-x" @click="removeProject(i)">✕</button>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal=false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存合同' }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 右键上下文菜单 -->
    <ContextMenu :ctx="ctx" :items="ctxItems" />
  </div>
</template>

<style scoped>
.topbar { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 14px; }
.filter-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.search-box { position: relative; display: flex; align-items: center; flex: 1; min-width: 260px; max-width: 420px; }
.search-input { width: 100%; padding: 9px 30px 9px 12px; border: 1px solid var(--border); border-radius: 10px; background: rgba(255,255,255,0.8); font-size: 13px; }
.search-input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(201,99,66,0.12); }
.search-clear { position: absolute; right: 8px; width: 18px; height: 18px; border: none; border-radius: 50%; background: rgba(0,0,0,0.08); color: var(--muted); font-size: 10px; cursor: pointer; }
.filter-reset { font-size: 12px; color: var(--primary); background: none; border: none; cursor: pointer; }

.ct-table { width: 100%; font-size: 12.5px; }
.ct-table th { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); padding: 9px 12px; background: rgba(0,0,0,0.025); border-bottom: 1px solid rgba(0,0,0,0.06); white-space: nowrap; }
/* 固定视口：表头吸顶，仅表体内部滚动（用不透明色，避免滚动内容透出） */
.table-wrap thead th { position: sticky; top: 0; z-index: 5; background: #f5f2ee; }
.ct-table td { padding: 9px 12px; vertical-align: middle; }
.ct-table .data-row:hover { background: rgba(201,99,66,0.04); }
.ct-table .data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.035); }
.ct-name { font-weight: 600; color: var(--text); }
.empty-cell { padding: 44px !important; text-align: center; color: var(--muted); }
.mono { font-family: monospace; font-size: 11.5px; }
.dept-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 600; white-space: nowrap; }
.cnt-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; background: rgba(21,101,192,0.1); color: #1565c0; font-weight: 700; }
.text-muted { color: var(--muted); }
.text-sm { font-size: 12px; }
.ctr { text-align: center; }
.rgt { text-align: right; font-variant-numeric: tabular-nums; }
.row-actions { display: flex; gap: 4px; justify-content: center; }
.icon-btn { padding: 4px 10px; border-radius: 7px; border: 1px solid var(--border); background: rgba(255,252,250,0.7); color: var(--muted); cursor: pointer; font-size: 12px; }
.icon-btn:hover { border-color: var(--primary); color: var(--primary); }
.icon-btn-danger:hover { border-color: #c62828; color: #c62828; }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; flex-shrink: 0; }
.page-btn { padding: 5px 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,252,250,0.7); font-size: 13px; cursor: pointer; }
.page-btn:disabled { opacity: .35; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }

/* link sections */
.link-section { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--border); }
.link-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.link-title { font-weight: 700; font-size: 13px; color: var(--text); }
.link-sub { font-size: 11.5px; color: var(--muted); }
.add-row { display: flex; gap: 8px; margin-bottom: 8px; }
.add-sel { flex: 1; padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; background: #fff; }
.link-empty { font-size: 12px; color: var(--muted); padding: 6px 0; }
.link-chip { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; background: rgba(255,255,255,0.6); flex-wrap: wrap; }
.chip-name { font-weight: 600; font-size: 12.5px; }
.chip-sel { padding: 3px 6px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
.chip-share { width: 72px; padding: 3px 6px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
.chip-primary { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 3px; }
.chip-x { margin-left: auto; width: 20px; height: 20px; border: none; border-radius: 50%; background: rgba(0,0,0,0.06); color: var(--muted); cursor: pointer; font-size: 11px; }
.chip-x:hover { background: rgba(198,40,40,0.12); color: #c62828; }
.proj-results { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; max-height: 180px; overflow: auto; }
.proj-result { padding: 7px 10px; font-size: 12.5px; cursor: pointer; border-bottom: 1px solid rgba(0,0,0,0.04); }
.proj-result:hover { background: rgba(201,99,66,0.06); }
.add-hint { float: right; color: var(--primary); font-weight: 600; font-size: 11.5px; }
</style>
