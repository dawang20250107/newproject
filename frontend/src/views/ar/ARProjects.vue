<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, defineAsyncComponent } from 'vue'
import { useToast } from '../../composables/useToast.js'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { downloadBlob } from '../../utils/download.js'
import { fmtCompact, fmtMoney } from '../../utils/format.js'
import { TOOLTIP } from '../../utils/chartTheme.js'
import BaseChart from '../../components/ar/BaseChart.vue'
import ImportPrecheckModal from '../../components/ImportPrecheckModal.vue'
import ColumnFilter from '../../components/ColumnFilter.vue'
import SkeletonRow from '../../components/SkeletonRow.vue'

const toast = useToast()
const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const stats = ref(null)
const loading = ref(false)
const loadErr = ref('')
const page = ref(1)
const size = 50
const jumpPage = ref(1)
function doJump() {
  const tp = Math.ceil(total.value / size)
  const p = Math.max(1, Math.min(tp, jumpPage.value || 1))
  page.value = p; load()
}

// 顶部仅保留全局关键字搜索 + 无列头等价物的页面级开关（共享业务 / 草稿）。
// 真实数据列（交付部门 / 客户等级 / 开票模式 / 状态 等）改用 Excel 风格列头筛选。
const filters = reactive({ q: '', is_shared: '', is_draft: '' })
// ── Excel 风格列头筛选 + 排序 ───────────────────────────────────────────────
const colFilters = reactive({})    // field -> {op, value}
const sortField = ref('')
const sortOrder = ref('')          // 'asc' | 'desc' | ''
const CUSTOMER_LEVELS = ['S级', 'A级', 'B级', 'C级', 'D级']
const STATUSES = ['运作中', '中断', '结束']
const INVOICE_MODES = ['全额', '差额']
function setColFilter(field, val) {
  if (val == null) delete colFilters[field]
  else colFilters[field] = val
  page.value = 1; clearSelection(); reloadAll()
}
function setSort(field, order) {
  sortField.value = order ? field : ''
  sortOrder.value = order || ''
  page.value = 1; load()
}
const activeColFilterCount = computed(() => Object.keys(colFilters).length)
// 统计条按单一交付部门聚合：列头仅选了一个事业部时带入，否则按全部口径。
const statDept = computed(() => {
  const sel = colFilters.delivery_dept
  return (sel && Array.isArray(sel.value) && sel.value.length === 1) ? sel.value[0] : ''
})
function buildParams() {
  const p = { page: page.value, size }
  if (filters.q.trim()) p.q = filters.q.trim()
  if (filters.is_shared) p.is_shared = filters.is_shared
  if (filters.is_draft) p.is_draft = filters.is_draft
  if (Object.keys(colFilters).length) p.filters = JSON.stringify(colFilters)
  if (sortField.value && sortOrder.value) { p.sort = sortField.value; p.order = sortOrder.value }
  return p
}
const statusClass = s => ({ '运作中': 'st-on', '中断': 'st-pause', '结束': 'st-end' }[s] || 'st-on')
const showModal = ref(false)
const editItem = ref(null)
const saving = ref(false)
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)
const importResult = ref(null)   // { ok, title, sections: [{label, items, warn?}] }
const precheckResult = ref(null)
const precheckBusy = ref(false)
const pendingFile = ref(null)    // 保存原文件，AI 介入确认后重提

// ── 多选 + 批量删除 ─────────────────────────────────────────────────────────
const selectedIds = ref(new Set())          // 按 id 记忆选择（本页）
const selectAllMatching = ref(false)        // 勾选整个筛选集（跨所有分页）
const bulkDeleting = ref(false)
const showDelConfirm = ref(false)
const delConfirmText = ref('')              // 二次输入待删条数，防误删
const pageAllSelected = computed(() =>
  items.value.length > 0 && items.value.every(r => selectedIds.value.has(r.id)))
const selectedCount = computed(() => selectAllMatching.value ? total.value : selectedIds.value.size)
const hasSelection = computed(() => selectAllMatching.value || selectedIds.value.size > 0)
const delConfirmOk = computed(() => delConfirmText.value.trim() === String(selectedCount.value))
// 待删项目预览（确认时列出，让用户核对到底删哪些）
const selectedPreview = computed(() =>
  selectAllMatching.value ? [] : items.value.filter(r => selectedIds.value.has(r.id)))
function toggleRow(id) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) { s.delete(id); selectAllMatching.value = false } else s.add(id)
  selectedIds.value = s
}
function toggleSelectPage() {
  const s = new Set(selectedIds.value)
  if (pageAllSelected.value) { items.value.forEach(r => s.delete(r.id)); selectAllMatching.value = false }
  else items.value.forEach(r => s.add(r.id))
  selectedIds.value = s
}
function clearSelection() { selectedIds.value = new Set(); selectAllMatching.value = false }
function bulkDelete() {
  if (!selectedCount.value) return
  delConfirmText.value = ''
  showDelConfirm.value = true
}
async function confirmBulkDelete() {
  if (!delConfirmOk.value) return
  bulkDeleting.value = true
  try {
    if (selectAllMatching.value) await ar.bulkDeleteProjects({ all: true }, buildParams())
    else await ar.bulkDeleteProjects({ ids: [...selectedIds.value] })
    showDelConfirm.value = false
    clearSelection()
    reloadAll()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { bulkDeleting.value = false }
}

const form = reactive({
  customer_name: '', short_name: '', delivery_dept: '', sub_dept: '',
  business_mode: '', customer_level: 'A级', status: '运作中', sales_contact: '', project_manager: '',
  has_contract: '有', contract_date: '', reconciliation_days: 0,
  invoice_wait_days: 0, post_invoice_days: 0, cycle_start_day: 1, invoice_mode: '全额',
  invoice_type: '专票', tax_rate: '0.06', notes: '',
  customer_id: '',
})
// 项目台账内联改状态（与客户详情两边改同一字段，自动同步）
async function changeStatus(item) {
  try { await ar.updateProject(item.id, { status: item.status }) }
  catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

// 客户池（一次性加载）+ 当前项目挂靠的合同
const customers = ref([])
const linkedContracts = ref([])    // [{contract_id, name, contract_no, is_primary}]
const ctQuery = ref('')
const ctResults = ref([])
let ctTimer = null

const totalDays = computed(() =>
  (parseInt(form.reconciliation_days) || 0) +
  (parseInt(form.invoice_wait_days) || 0) +
  (parseInt(form.post_invoice_days) || 0))

const isShared = computed(() =>
  form.sales_contact && form.project_manager &&
  form.sales_contact !== form.project_manager)

watch(() => form.invoice_type, val => { if (val === '不开票') form.tax_rate = '0' })

// Scoped to the user's currently-active department selection (set from
// the global picker in the sidebar footer). Falls back to all allowed.
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

// Field-permission column visibility
const show = k => auth.canArView(k)

function fmtNum(v) {
  const n = parseFloat(v) || 0
  return n.toLocaleString('zh-CN')
}

async function load(reset = false) {
  if (reset) { page.value = 1; clearSelection() }  // 改筛选/搜索即清空选择，避免误删旧筛选项
  loading.value = true
  loadErr.value = ''
  try {
    const res = await ar.listProjects(buildParams())
    items.value = res.data.items
    total.value = res.data.total
  } catch (e) { loadErr.value = e?.error || e?.message || '加载失败，请刷新重试'
  } finally { loading.value = false }
}

async function loadStats() {
  try {
    const res = await ar.projectStats({ dept: statDept.value })
    stats.value = res.data
  } catch { stats.value = null }
}

function reloadAll() { load(true); loadStats() }

// 搜索防抖：输入停顿 280ms 再查，避免每次按键都打接口、页码反复重置
let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 280)
}
function clearSearch() { filters.q = ''; load(true) }

const hasActiveFilters = computed(() =>
  !!(filters.q || filters.is_draft || activeColFilterCount.value || sortField.value ||
     (filters.is_shared && !auth.perms?.ar_shared_only)))

function resetFilters() {
  filters.q = ''
  if (!auth.perms?.ar_shared_only) filters.is_shared = ''
  filters.is_draft = ''
  Object.keys(colFilters).forEach(k => delete colFilters[k])
  sortField.value = ''
  sortOrder.value = ''
  page.value = 1
  reloadAll()
}

async function loadCustomers() {
  try { customers.value = (await ar.listCustomers({ size: 200 })).data.items }
  catch { customers.value = [] }
}

// 合同搜索添加（项目侧挂靠）
function onCtSearch() {
  clearTimeout(ctTimer)
  ctTimer = setTimeout(doCtSearch, 280)
}
async function doCtSearch() {
  const q = ctQuery.value.trim()
  if (!q) { ctResults.value = []; return }
  try {
    const params = { q, size: 10 }
    if (form.delivery_dept) params.dept = form.delivery_dept
    const res = await ar.listContracts(params)
    const used = new Set(linkedContracts.value.map(c => c.contract_id))
    ctResults.value = res.data.items.filter(c => !used.has(c.id))
  } catch { ctResults.value = [] }
}
function addContract(c) {
  linkedContracts.value.push({ contract_id: c.id, name: c.name,
    contract_no: c.contract_no, is_primary: true })
  ctResults.value = ctResults.value.filter(x => x.id !== c.id)
  ctQuery.value = ''
}
function removeContract(i) { linkedContracts.value.splice(i, 1) }

function openCreate() {
  editItem.value = null
  Object.assign(form, {
    customer_name: '', short_name: '', delivery_dept: accessibleDepts.value[0] || '',
    sub_dept: '', business_mode: '', customer_level: 'A级', status: '运作中',
    sales_contact: '', project_manager: '', has_contract: '有', contract_date: '',
    reconciliation_days: 0, invoice_wait_days: 0, post_invoice_days: 0,
    cycle_start_day: 1,
    invoice_mode: '全额', invoice_type: '专票', tax_rate: '0.06', notes: '',
    customer_id: '',
  })
  linkedContracts.value = []
  ctQuery.value = ''; ctResults.value = []
  showModal.value = true
}

async function openEdit(item) {
  editItem.value = item
  Object.assign(form, {
    customer_name: item.customer_name,
    short_name: item.short_name,
    delivery_dept: item.delivery_dept, sub_dept: item.sub_dept,
    business_mode: item.business_mode, customer_level: item.customer_level || 'A级', status: item.status || '运作中',
    sales_contact: item.sales_contact, project_manager: item.project_manager,
    has_contract: item.has_contract, contract_date: item.contract_date || '',
    reconciliation_days: item.reconciliation_days,
    invoice_wait_days: item.invoice_wait_days,
    post_invoice_days: item.post_invoice_days,
    cycle_start_day: item.cycle_start_day || 1,
    invoice_mode: item.invoice_mode, invoice_type: item.invoice_type,
    tax_rate: item.tax_rate, notes: item.notes,
    customer_id: item.customer_id || '',
  })
  linkedContracts.value = []
  ctQuery.value = ''; ctResults.value = []
  showModal.value = true
  // 拉详情带出当前挂靠合同
  try {
    const d = (await ar.getProject(item.id)).data
    linkedContracts.value = (d.contracts || []).map(c => ({
      contract_id: c.contract_id, name: c.name,
      contract_no: c.contract_no, is_primary: c.is_primary }))
    if (d.customer_id) form.customer_id = d.customer_id
  } catch { /* 保持空 */ }
}

// Required fields — sub_dept / contract_date / tax_rate are optional
const REQUIRED = [
  ['customer_name', '客户名称'], ['short_name', '项目简称'],
  ['delivery_dept', '交付部门'], ['business_mode', '业务模式'],
  ['customer_level', '客户等级'], ['sales_contact', '销售对接人'],
  ['project_manager', '项目负责人'], ['has_contract', '有无合同'],
  ['invoice_mode', '开票模式'], ['invoice_type', '专票/普票'],
]

async function save() {
  const missing = REQUIRED.filter(([k]) => form[k] === '' || form[k] === null || form[k] === undefined)
  if (missing.length) {
    toast.error('请填写所有必填字段：' + missing.map(([, l]) => l).join('、'))
    return
  }
  saving.value = true
  const contractIds = linkedContracts.value.map(c => c.contract_id)
  try {
    if (editItem.value) {
      const payload = { ...form, customer_id: form.customer_id || null, contract_ids: contractIds }
      if (editItem.value.is_draft) payload.is_draft = false
      delete payload._complete_draft
      await ar.updateProject(editItem.value.id, payload)
    } else {
      const saved = await ar.createProject({ ...form, customer_id: form.customer_id || null, contract_ids: contractIds })
      // 新建后确保立即可见：清空搜索、按新项目部门（列头筛选）锁定、回到首页
      filters.q = ''
      const newDept = saved?.data?.delivery_dept || form.delivery_dept
      if (newDept && accessibleDepts.value.includes(newDept)) {
        colFilters.delivery_dept = { op: 'in', value: [newDept] }
      }
      page.value = 1
    }
    showModal.value = false
    reloadAll()
  } catch (e) {
    toast.error(e?.msg || e?.error || '操作失败')
  } finally { saving.value = false }
}

async function remove(item) {
  if (!confirm(`确定删除项目「${item.short_name || item.customer_name}」？\n⚠ 该项目下的应收账款明细和回款记录将一并永久删除，不可恢复。`)) return
  try { await ar.deleteProject(item.id); reloadAll() }
  catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

async function completeDraft(item) {
  editItem.value = item
  Object.assign(form, {
    customer_name: item.customer_name || item.short_name,
    short_name: item.short_name,
    delivery_dept: item.delivery_dept, sub_dept: item.sub_dept || '',
    business_mode: item.business_mode || '', customer_level: item.customer_level || 'A级', status: item.status || '运作中',
    sales_contact: item.sales_contact || '', project_manager: item.project_manager || '',
    has_contract: item.has_contract || '无', contract_date: item.contract_date || '',
    reconciliation_days: item.reconciliation_days || 0,
    invoice_wait_days: item.invoice_wait_days || 0,
    post_invoice_days: item.post_invoice_days || 0,
    invoice_mode: item.invoice_mode || '全额', invoice_type: item.invoice_type || '专票',
    tax_rate: item.tax_rate || '0.06', notes: item.notes || '',
    _complete_draft: true,
  })
  showModal.value = true
}

const isDraftEdit = computed(() => !!(editItem.value?.is_draft))

async function downloadTemplate() {
  try {
    const res = await ar.projectTemplate()
    downloadBlob(res, '项目信息导入模板.xlsx')
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  if (fileInput.value) fileInput.value.value = ''
  pendingFile.value = f
  importing.value = true
  precheckResult.value = null
  try {
    const fd = new FormData(); fd.append('file', f)
    const report = (await ar.precheckProjects(fd)).data
    if (report && !report.skipPrecheck && report.attention > 0) {
      precheckResult.value = report; return
    }
    await doImport(f)
  } catch (err) {
    importResult.value = { ok: false, title: '导入失败', sections: [{ label: '错误信息', warn: true, items: [err?.msg || err?.error || err?.message || '服务器错误，请联系管理员'] }] }
  } finally { importing.value = false }
}

async function doImport(f) {
  const fd = new FormData(); fd.append('file', f)
  const res = await ar.importProjects(fd); const d = res.data
  if (d.rejected) {
    importResult.value = { ok: false, title: d.message || '导入未执行，请按提示修正后重新导入',
      sections: [{ label: `以下 ${d.errors?.length || 0} 处需在表格中修正`, warn: true, items: d.errors || [] }] }
  } else {
    const counts = [`新增 ${d.created} 条`]
    if (d.updated) counts.push(`更新 ${d.updated} 条`)
    importResult.value = { ok: true, title: `导入完成：${counts.join('，')}`, sections: [] }
  }
  reloadAll()
}

async function onPrecheckApply({ mode }) {
  if (mode !== 'import') return
  precheckBusy.value = true
  try {
    await doImport(pendingFile.value)
    precheckResult.value = null
  } catch (err) {
    toast.error(err?.msg || err?.error || '操作失败')
  } finally { precheckBusy.value = false; importing.value = false }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportProjects(buildParams())
    downloadBlob(res, '项目信息.xlsx')
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { exporting.value = false }
}

const onScopeChange = () => {
  // 事业部范围切换：若列头筛了已超出范围的事业部，剔除越界值（清空则去掉该列筛选）
  const sel = colFilters.delivery_dept
  if (sel && Array.isArray(sel.value)) {
    const kept = sel.value.filter(d => accessibleDepts.value.includes(d))
    if (kept.length) colFilters.delivery_dept = { op: 'in', value: kept }
    else delete colFilters.delivery_dept
  }
  page.value = 1
  reloadAll()
}

// 待完善草稿「转正」：把信息齐全(有交付部门)的草稿转为正式项目并同步客户，保留应收数据
const promotingDrafts = ref(false)
async function promoteDrafts() {
  promotingDrafts.value = true
  try {
    const pv = (await ar.promoteDraftProjects({ preview: 1 })).data
    if (!pv.total) { toast.error('没有待完善草稿'); return }
    let tip = `共 ${pv.total} 个草稿：\n· 可直接转正（有交付部门）${pv.ready} 个 → 转为正式项目并同步客户\n`
    if (pv.need_dept > 0) tip += `· 缺交付部门 ${pv.need_dept} 个 → 无法自动转，需到台账补部门后再转\n`
    tip += `\n确认转正这 ${pv.ready} 个？（应收数据保留，不会丢）`
    if (pv.ready === 0) { toast.error('暂无可直接转正的草稿，请先补交付部门。'); return }
    if (!confirm(tip)) return
    const res = await ar.promoteDraftProjects({})
    toast.success(res.data?.message || '已转正')
    if (filters.is_draft) filters.is_draft = ''
    reloadAll()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { promotingDrafts.value = false }
}

onMounted(() => {
  if (auth.perms?.ar_shared_only) filters.is_shared = '1'
  load(); loadStats(); loadCustomers(); window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div>
    <!-- Header -->
    <div class="topbar">
      <div>
        <h1>项目台账</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">为应收账款提供项目主数据 · 合同账期 · 开票配置</div>
      </div>
    </div>

    <div>
    <!-- Stats strip -->
    <div class="stats-strip">
      <div class="stat-pill">
        <div class="stat-label">项目总数</div>
        <div class="stat-value">{{ stats?.total ?? '—' }}</div>
      </div>
      <div class="stat-pill stat-pill-gold">
        <div class="stat-label">S 级客户</div>
        <div class="stat-value">{{ stats?.s_count ?? 0 }}</div>
      </div>
      <div class="stat-pill stat-pill-blue">
        <div class="stat-label">A 级客户</div>
        <div class="stat-value">{{ stats?.a_count ?? 0 }}</div>
      </div>
      <div class="stat-pill stat-pill-purple">
        <div class="stat-label">共享业务</div>
        <div class="stat-value">{{ stats?.shared ?? 0 }}</div>
      </div>
      <div v-if="stats?.draft_count" class="stat-pill stat-pill-draft">
        <div class="stat-label" style="cursor:pointer" @click="filters.is_draft='true'; load(true)" title="点击筛选草稿项目">待完善草稿</div>
        <div class="stat-draft-row">
          <span class="stat-value" style="color:#c0392b">{{ stats.draft_count }}</span>
          <button v-if="auth.canArWrite" class="draft-clear-btn" :disabled="promotingDrafts" @click.stop="promoteDrafts" title="把有交付部门的草稿转为正式项目并同步客户（保留应收）">{{ promotingDrafts ? '转正中…' : '草稿转正' }}</button>
        </div>
      </div>
      <div class="stat-pill stat-pill-mom">
        <div class="stat-label">本月新签（环比）</div>
        <div class="stat-value">
          {{ stats?.new_this_month ?? 0 }}
          <span v-if="stats && stats.mom_growth !== null" class="mom-tag" :class="stats.mom_growth >= 0 ? 'mom-up' : 'mom-down'">
            {{ stats.mom_growth >= 0 ? '▲' : '▼' }} {{ Math.abs(stats.mom_growth) }}%
          </span>
          <span v-else class="mom-tag mom-flat">无基期</span>
        </div>
      </div>
      <div class="stat-actions">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate" title="下载模板">↓ 模板</button>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer">
          {{ importing ? '导入中…' : '↑ 导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" :disabled="importing" />
        </label>
        <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">↓ 导出</button>
        <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" @click="openCreate">+ 新增项目</button>
      </div>
    </div>

    <!-- Filter strip -->
    <div class="filter-strip">
      <div class="search-box">
        <svg class="search-ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <input v-model="filters.q" class="search-input"
               placeholder="搜索项目编号 / 客户名称 / 项目简称 / 负责人 / 销售对接人"
               @input="onSearchInput" @keyup.enter="load(true)" />
        <button v-if="filters.q" class="search-clear" title="清除" @click="clearSearch">✕</button>
      </div>
      <!-- 真实数据列（事业部 / 等级 / 状态 / 开票 等）改用列头 ⏷ 筛选 + 排序；
           此处仅保留无列头等价物的页面级开关（共享业务 / 草稿）。 -->
      <select v-model="filters.is_shared" class="sel-mo" @change="load(true)"
              :disabled="auth.perms?.ar_shared_only">
        <option value="">全部业务</option>
        <option value="true">共享业务</option>
        <option value="false">非共享</option>
      </select>
      <select v-model="filters.is_draft" class="sel-mo" @change="load(true)">
        <option value="">全部项目</option>
        <option value="true">待完善草稿</option>
        <option value="false">已完善项目</option>
      </select>
      <button v-if="hasActiveFilters" class="filter-reset" @click="resetFilters">重置筛选</button>
    </div>

    <!-- 选择 + 批量删除工具条（选中后出现） -->
    <div v-if="hasSelection && auth.canDelete" class="bulk-bar">
      <span class="bulk-n">已选 <strong>{{ selectedCount }}</strong> 个项目</span>
      <button v-if="pageAllSelected && !selectAllMatching && total > items.length"
        class="bulk-all" @click="selectAllMatching = true">选择全部 {{ total }} 个</button>
      <span v-if="selectAllMatching" class="bulk-all-on">已选中整个筛选集（跨所有分页）</span>
      <button class="bulk-del" :disabled="bulkDeleting" @click="bulkDelete">
        {{ bulkDeleting ? '删除中…' : `删除选中(${selectedCount})` }}
      </button>
      <button class="bulk-cancel" @click="clearSelection">取消</button>
    </div>

    <!-- Table card -->
    <div class="card" :class="{ 'data-reloading': loading && items.length }">
      <div class="table-wrap">
        <table class="proj-table">
          <thead>
            <tr>
              <th v-if="auth.canDelete" class="ctr sel-col">
                <input type="checkbox" :checked="pageAllSelected" :disabled="!items.length"
                  title="全选本页" @change="toggleSelectPage" />
              </th>
              <th><ColumnFilter label="项目编号" field="project_no" type="text" :model-value="colFilters.project_no" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('project_no',v)" @sort="o=>setSort('project_no',o)" /></th>
              <th v-if="show('p_contract_name') || show('p_short_name')"><ColumnFilter label="客户 / 简称" field="customer_name" type="text" :model-value="colFilters.customer_name" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('customer_name',v)" @sort="o=>setSort('customer_name',o)" /></th>
              <th class="ctr"><ColumnFilter label="状态" field="status" type="enum" :options="STATUSES" :model-value="colFilters.status" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('status',v)" @sort="o=>setSort('status',o)" /></th>
              <th v-if="show('p_delivery_dept')"><ColumnFilter label="交付部门" field="delivery_dept" type="enum" :options="accessibleDepts" :model-value="colFilters.delivery_dept" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('delivery_dept',v)" @sort="o=>setSort('delivery_dept',o)" /></th>
              <th v-if="show('p_sub_dept')"><ColumnFilter label="二级部门" field="sub_dept" type="text" :model-value="colFilters.sub_dept" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('sub_dept',v)" @sort="o=>setSort('sub_dept',o)" /></th>
              <th v-if="show('p_business_mode')"><ColumnFilter label="业务模式" field="business_mode" type="text" :model-value="colFilters.business_mode" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('business_mode',v)" @sort="o=>setSort('business_mode',o)" /></th>
              <th v-if="show('p_customer_level')" class="ctr"><ColumnFilter label="客户等级" field="customer_level" type="enum" :options="CUSTOMER_LEVELS" :model-value="colFilters.customer_level" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('customer_level',v)" @sort="o=>setSort('customer_level',o)" /></th>
              <th v-if="show('p_project_manager')"><ColumnFilter label="负责人" field="project_manager" type="text" :model-value="colFilters.project_manager" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('project_manager',v)" @sort="o=>setSort('project_manager',o)" /></th>
              <th v-if="show('p_sales_contact')"><ColumnFilter label="销售" field="sales_contact" type="text" :model-value="colFilters.sales_contact" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('sales_contact',v)" @sort="o=>setSort('sales_contact',o)" /></th>
              <th v-if="show('p_has_contract')" class="ctr">合同</th>
              <th v-if="show('p_contract_date')" class="ctr"><ColumnFilter label="签订日期" field="contract_date" type="date" :model-value="colFilters.contract_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('contract_date',v)" @sort="o=>setSort('contract_date',o)" /></th>
              <th v-if="show('p_account_period')" class="ctr">总账期</th>
              <th v-if="show('p_invoice_config')" class="ctr"><ColumnFilter label="开票" field="invoice_mode" type="enum" :options="INVOICE_MODES" :model-value="colFilters.invoice_mode" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('invoice_mode',v)" @sort="o=>setSort('invoice_mode',o)" /></th>
              <th v-if="show('p_notes')">备注</th>
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-if="loading && !items.length">
              <SkeletonRow v-for="n in 8" :key="n" :cols="10" />
            </template>
            <tr v-else-if="loadErr">
              <td colspan="16" class="empty-cell">⚠️ {{ loadErr }} <button style="border:none;background:none;color:var(--primary);cursor:pointer;font-size:13px;text-decoration:underline" @click="load()">重试</button></td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="16" class="empty-cell"><div class="empty-inner">暂无项目数据，点击「新增项目」开始</div></td>
            </tr>
            <tr v-for="item in items" :key="item.id" class="data-row"
              :class="{ 'row-sel': selectAllMatching || selectedIds.has(item.id) }">
              <td v-if="auth.canDelete" class="ctr sel-col">
                <input type="checkbox" :checked="selectAllMatching || selectedIds.has(item.id)"
                  @change="toggleRow(item.id)" />
              </td>
              <td>
                <span class="proj-no-tag">{{ item.project_no }}</span>
                <span v-if="item.is_draft" class="badge-draft" title="导入自动创建，请补充完善">待完善</span>
              </td>
              <td v-if="show('p_contract_name') || show('p_short_name')"
                :title="item.customer_name + (item.short_name ? ' / ' + item.short_name : '')">
                <div class="contract-name">{{ item.customer_name }}</div>
                <div v-if="item.short_name" class="short-name">{{ item.short_name }}</div>
              </td>
              <td class="ctr">
                <select v-if="auth.canArWrite" v-model="item.status" class="proj-st-sel" :class="statusClass(item.status)" @change="changeStatus(item)">
                  <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
                </select>
                <span v-else class="st-pill" :class="statusClass(item.status)">{{ item.status }}</span>
              </td>
              <td v-if="show('p_delivery_dept')"><span class="dept-chip">{{ item.delivery_dept }}</span></td>
              <td v-if="show('p_sub_dept')" class="text-muted" :title="item.sub_dept || ''">{{ item.sub_dept || '—' }}</td>
              <td v-if="show('p_business_mode')" class="text-muted" :title="item.business_mode || ''">{{ item.business_mode || '—' }}</td>
              <td v-if="show('p_customer_level')" class="ctr">
                <span class="level-chip" :class="'lv-' + (item.customer_level || '')">{{ item.customer_level || '—' }}</span>
              </td>
              <td v-if="show('p_project_manager')" class="person" :title="item.project_manager || ''">{{ item.project_manager }}</td>
              <td v-if="show('p_sales_contact')" class="person" :title="item.sales_contact || ''">
                {{ item.sales_contact }}
                <span v-if="item.is_shared" class="badge-shared">共享</span>
              </td>
              <td v-if="show('p_has_contract')" class="ctr">
                <span :class="item.has_contract === '有' ? 'yn-yes' : 'yn-no'">{{ item.has_contract }}</span>
              </td>
              <td v-if="show('p_contract_date')" class="ctr text-sm">{{ item.contract_date || '—' }}</td>
              <td v-if="show('p_account_period')" class="ctr">
                <span class="days-chip">{{ item.total_days }}天</span>
              </td>
              <td v-if="show('p_invoice_config')" class="ctr">
                <span class="invoice-mode" :class="item.invoice_mode === '全额' ? 'mode-full' : 'mode-diff'">{{ item.invoice_mode }}</span>
                <div class="text-sm text-muted">{{ item.invoice_type }} · {{ (parseFloat(item.tax_rate) * 100).toFixed(0) }}%</div>
              </td>
              <td v-if="show('p_notes')" class="text-muted text-sm" :title="item.notes || ''">{{ item.notes || '—' }}</td>
              <td class="ctr">
                <div class="row-actions">
                  <button v-if="item.is_draft && auth.canArWrite" class="icon-btn icon-btn-complete" @click="completeDraft(item)" title="补充完善草稿项目">完善</button>
                  <button class="icon-btn" @click="openEdit(item)" title="编辑">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button v-if="auth.canDelete" class="icon-btn icon-btn-danger" @click="remove(item)" title="删除">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
        <span class="pg-jump">到第<input type="number" v-model.number="jumpPage" :min="1" :placeholder="`1-${Math.ceil(total / size)}`" class="pg-jump-input" @keyup.enter="doJump" />页</span>
      </div>
    </div>
    </div><!-- /projTab list -->


    <!-- Modal：编辑/新增卡片——点击遮罩不关闭，必须显式「取消」或「保存」，防误触退出 -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay">
        <div class="modal-box" style="max-width:720px">
          <div class="modal-header">
            <div>
              <h3>{{ isDraftEdit ? '完善草稿项目' : (editItem ? '编辑项目' : '新增项目') }}</h3>
              <div class="modal-subtitle">
                <span v-if="isDraftEdit" class="badge-draft" style="margin-right:6px">待完善</span>
                {{ editItem ? editItem.project_no : '编号将自动生成 · 标 * 为必填' }}
                <span v-if="isDraftEdit" style="margin-left:6px;color:#c0392b"> — 请补充完整后保存，将自动移出草稿</span>
              </div>
            </div>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>

          <!-- Derived info bar -->
          <div class="derived-bar">
            <div class="derived-item">
              <span class="derived-label">总账期</span>
              <span class="derived-value">{{ totalDays }} 天</span>
            </div>
            <span v-if="isShared" class="badge-shared" style="font-size:12px;padding:3px 10px">共享业务</span>
            <span v-else class="badge-self">自营业务</span>
          </div>

          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2">
                <span>客户名称 <em>*</em></span>
                <input v-model="form.customer_name" list="customer-suggest"
                       placeholder="客户公司全称（即客户/往来单位名称，自动汇入客户名单；预收录入时自动带出）" />
                <datalist id="customer-suggest">
                  <option v-for="c in customers" :key="c.id" :value="c.name" />
                </datalist>
              </label>
              <label class="form-field">
                <span>项目简称 <em>*</em></span>
                <input v-model="form.short_name" placeholder="显示在明细中" />
              </label>
              <label class="form-field">
                <span>交付部门 <em>*</em></span>
                <select v-model="form.delivery_dept">
                  <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>二级部门</span>
                <input v-model="form.sub_dept" placeholder="可选" />
              </label>
              <label class="form-field">
                <span>业务模式 <em>*</em></span>
                <input v-model="form.business_mode" />
              </label>
              <label class="form-field">
                <span>客户等级 <em>*</em> <span class="lvl-hint" title="客户等级以客户为准：在此设置会同步到该客户及其名下所有项目">ⓘ 同步到客户</span></span>
                <select v-model="form.customer_level">
                  <option v-for="l in CUSTOMER_LEVELS" :key="l" :value="l">{{ l }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>状态</span>
                <select v-model="form.status">
                  <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>销售对接人 <em>*</em></span>
                <input v-model="form.sales_contact" />
              </label>
              <label class="form-field">
                <span>项目负责人 <em>*</em></span>
                <input v-model="form.project_manager" />
              </label>
              <label class="form-field">
                <span>有无合同 <em>*</em></span>
                <select v-model="form.has_contract"><option>有</option><option>无</option></select>
              </label>
              <label class="form-field">
                <span>签订日期</span>
                <input v-model="form.contract_date" type="date" />
              </label>
              <label class="form-field">
                <span>合同对账期（天） <em>*</em></span>
                <input v-model.number="form.reconciliation_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>开票等待期（天） <em>*</em></span>
                <input v-model.number="form.invoice_wait_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>票后等待期（天） <em>*</em></span>
                <input v-model.number="form.post_invoice_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>对账周期起始日</span>
                <input v-model.number="form.cycle_start_day" type="number" min="1" max="28"
                  title="1=自然月（月初到月末，默认）；如月结周期为每月15日到下月14日则填15。应收到期 = 运作日期所在账期的结束日 + 总账期天数；修改后已有明细到期日自动重算" />
              </label>
              <label class="form-field">
                <span>开票模式 <em>*</em></span>
                <select v-model="form.invoice_mode"><option>全额</option><option>差额</option></select>
              </label>
              <label class="form-field">
                <span>专票 / 普票 <em>*</em></span>
                <select v-model="form.invoice_type"><option>专票</option><option>普票</option><option>不开票</option></select>
              </label>
              <label class="form-field">
                <span>税率（如 0.06 = 6%）</span>
                <input v-model="form.tax_rate" placeholder="0.06，不开票可留空" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="form.notes" placeholder="可选" />
              </label>
            </div>

            <!-- 关联客户 + 合同（已隐藏：客户关系统一走「客户名称」字段自动挂接，避免重复冲突）-->
            <div class="link-section" v-if="false">
              <div class="link-head">
                <span class="link-title">关联客户 / 合同</span>
                <span class="link-sub">直接挂客户主体与所属合同（一个项目可挂多个合同）</span>
              </div>
              <div class="form-grid" style="margin-bottom:10px">
                <label class="form-field span2">
                  <span>关联客户</span>
                  <select v-model="form.customer_id">
                    <option value="">（不关联客户）</option>
                    <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
                  </select>
                </label>
              </div>
              <div class="add-row">
                <input v-model="ctQuery" class="add-sel" placeholder="搜索合同名称/编号挂靠…" @input="onCtSearch" />
              </div>
              <div v-if="ctResults.length" class="ct-results">
                <div v-for="c in ctResults" :key="c.id" class="ct-result" @click="addContract(c)">
                  <span class="mono">{{ c.contract_no || '—' }}</span> · {{ c.name }}
                  <span class="text-muted">（{{ c.delivery_dept || '不限' }}）</span>
                  <span class="add-hint">+ 挂靠</span>
                </div>
              </div>
              <div v-if="!linkedContracts.length" class="link-empty">尚未挂靠合同</div>
              <div v-for="(c, i) in linkedContracts" :key="c.contract_id" class="link-chip">
                <span class="mono">{{ c.contract_no || '—' }}</span>
                <span class="chip-name">{{ c.name }}</span>
                <label class="chip-primary"><input type="checkbox" v-model="c.is_primary" /> 主合同</label>
                <button class="chip-x" @click="removeContract(i)">✕</button>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存项目' }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 导入结果弹窗 -->
    <Teleport to="body">
      <div v-if="importResult" class="modal-overlay" @click.self="importResult = null">
        <div class="modal-box" style="max-width:800px">
          <div class="modal-header">
            <h3 :class="importResult.ok ? 'imp-ok' : 'imp-fail'">{{ importResult.ok ? '✓ ' : '✕ ' }}{{ importResult.title }}</h3>
            <button class="modal-close" @click="importResult = null">✕</button>
          </div>
          <div class="modal-body imp-body">
            <div v-for="sec in importResult.sections" :key="sec.label" class="imp-section">
              <div class="imp-sec-label" :class="{ 'imp-sec-warn': sec.warn }">{{ sec.label }}</div>
              <ul class="imp-sec-list">
                <li v-for="item in sec.items" :key="item">{{ item }}</li>
              </ul>
            </div>
            <div v-if="!importResult.sections?.length" class="imp-empty">无附加信息</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-primary" @click="importResult = null">知道了</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 导入预检弹窗 -->
    <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy" :readonly="true"
      @close="precheckResult = null" @apply="onPrecheckApply" />

    <!-- 批量删除确认：列出待删项目 + 二次输入条数 -->
    <Teleport to="body">
      <div v-if="showDelConfirm" class="modal-overlay" @click.self="showDelConfirm = false">
        <div class="modal-box" style="max-width:460px">
          <div class="modal-header">
            <div><h3>确认删除 {{ selectedCount }} 个项目</h3></div>
            <button class="modal-close" @click="showDelConfirm = false">✕</button>
          </div>
          <div class="modal-body">
            <p class="del-warn">⚠ 项目下的应收账款明细、回款将一并删除，<strong>不可恢复</strong>。</p>

            <!-- 待删清单（核对）。整个筛选集模式仅显示计数 -->
            <div v-if="selectAllMatching" class="del-allnote">
              当前为<strong>整个筛选集</strong>（跨所有分页，共 {{ total }} 个），按当前筛选条件删除。
            </div>
            <ul v-else class="del-list">
              <li v-for="p in selectedPreview" :key="p.id">
                <span class="proj-no-tag">{{ p.project_no }}</span>
                <span class="del-name">{{ p.short_name || p.customer_name }}</span>
                <span class="dept-chip">{{ p.delivery_dept }}</span>
              </li>
            </ul>

            <p class="del-tip">请输入待删数量 <strong>{{ selectedCount }}</strong> 以确认：</p>
            <input v-model="delConfirmText" class="del-input" :placeholder="`输入 ${selectedCount}`"
              @keyup.enter="confirmBulkDelete" />
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showDelConfirm = false">取消</button>
            <button class="btn-danger-solid" :disabled="!delConfirmOk || bulkDeleting" @click="confirmBulkDelete">
              {{ bulkDeleting ? '删除中…' : '确认删除' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<style scoped>
/* ── 主 Tab ─────────────────────────────────────────────────────────────────── */
.proj-tabs { display: flex; gap: 4px; margin: 2px 0 16px; border-bottom: 1px solid rgba(180,140,110,.2); }
.pt-tab {
  position: relative; border: none; background: none; cursor: pointer;
  padding: 9px 18px; font-size: 14px; font-weight: 600; color: var(--muted);
  border-radius: 9px 9px 0 0; transition: color .15s, background .15s;
}
.pt-tab:hover { color: var(--primary); background: rgba(201,99,66,.05); }
.pt-tab.on { color: var(--primary); font-weight: 800; }
.pt-tab.on::after { content: ''; position: absolute; left: 12px; right: 12px; bottom: -1px; height: 3px; border-radius: 3px 3px 0 0; background: linear-gradient(90deg, #c96342, #e8a05a); }

/* ── 客户/项目分析 ──────────────────────────────────────────────────────────── */
.econ-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.econ-dim { display: inline-flex; border: 1px solid rgba(180,140,110,.3); border-radius: 9px; overflow: hidden; }
.ed-btn { border: none; background: #fff; cursor: pointer; padding: 7px 16px; font-size: 13px; font-weight: 600; color: var(--muted); }
.ed-btn.on { background: var(--primary); color: #fff; }
.econ-hint { font-size: 12px; color: var(--muted); margin-left: auto; }
.econ-kpis { display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px; margin-bottom: 16px; }
@media (max-width: 1200px) { .econ-kpis { grid-template-columns: repeat(4, 1fr); } }
@media (max-width: 640px) { .econ-kpis { grid-template-columns: repeat(2, 1fr); } }
.econ-kpi { background: rgba(255,255,255,0.65); border: 1px solid rgba(180,140,110,.16); border-radius: 12px; padding: 11px 14px; }
.ek-label { font-size: 11.5px; color: var(--muted); }
.ek-hint { margin-left: 3px; cursor: help; opacity: .6; }
.ek-value { font-size: 20px; font-weight: 800; line-height: 1.25; margin-top: 2px; }
.ek-sub { font-size: 11px; color: var(--muted); margin-top: 1px; }
.econ-grid { display: grid; grid-template-columns: 1.1fr 1fr; gap: 16px; }
@media (max-width: 1000px) { .econ-grid { grid-template-columns: 1fr; } }
.econ-empty, .econ-td-empty { display: flex; align-items: center; justify-content: center; height: 320px; color: var(--muted); font-size: 13px; }
.econ-td-empty { height: auto; padding: 30px; }
.econ-table-wrap { overflow: auto; max-height: 360px; }
.econ-table { width: 100%; border-collapse: collapse; font-size: 12.5px; white-space: nowrap; }
.econ-table th { position: sticky; top: 0; background: rgba(0,0,0,.025); text-align: right; font-size: 11px; font-weight: 700; color: var(--muted); padding: 8px 10px; border-bottom: 1px solid rgba(0,0,0,.07); }
.econ-table th.l, .econ-table td.l { text-align: left; }
.econ-table td { text-align: right; padding: 8px 10px; border-bottom: 1px solid rgba(0,0,0,.04); }
.econ-table tbody tr:hover { background: rgba(201,99,66,.04); }
.econ-table .muted { color: var(--muted); }
.econ-table .strong { font-weight: 700; }
.econ-table .neg { color: #c62828; }
.econ-row-loss { background: rgba(198,40,40,.04); }
.econ-row-unlinked { color: var(--muted); }
.econ-name { font-weight: 600; color: var(--text); }
.econ-lvl { display: inline-block; color: #fff; font-size: 10px; font-weight: 700; padding: 0 5px; border-radius: 5px; margin-left: 6px; vertical-align: middle; }
.econ-bu { font-size: 11px; color: var(--muted); margin-left: 6px; }

/* Stats strip */
.stats-strip { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.stat-pill {
  display: flex; flex-direction: column; gap: 2px;
  padding: 10px 18px; border-radius: 12px;
  background: rgba(255,255,255,0.92); border: 1px solid rgba(255,255,255,0.8);
  box-shadow: 0 2px 12px rgba(0,0,0,0.06); min-width: 88px;
}
.stat-pill-gold { border-left: 3px solid #c9a227; }
.stat-pill-blue { border-left: 3px solid #1565c0; }
.stat-pill-purple { border-left: 3px solid #6a1b9a; }
.stat-pill-mom { border-left: 3px solid #2e7d32; }
.stat-label { font-size: 11px; color: var(--muted); font-weight: 500; letter-spacing: 0.03em; }
.stat-value { font-size: 20px; font-weight: 700; color: var(--text); line-height: 1.2; display: flex; align-items: baseline; gap: 6px; }
.mom-tag { font-size: 12px; font-weight: 700; }
.mom-up { color: #2e7d32; }
.mom-down { color: #c62828; }
.mom-flat { color: var(--muted); font-weight: 500; }
.stat-actions { display: flex; gap: 6px; align-items: center; margin-left: auto; flex-wrap: wrap; }
/* Table — compact density */
.proj-table { width: 100%; font-size: 11.5px; table-layout: auto; }
.proj-table th {
  font-size: 10px; font-weight: 700; letter-spacing: 0;
  color: var(--muted); padding: 6px 7px; background: rgba(0,0,0,0.025);
  border-bottom: 1px solid rgba(0,0,0,0.06); white-space: nowrap;
}
/* 列头允许筛选漏斗按钮溢出展示，不被裁切 */
.proj-table thead th { overflow: visible; }
/* 单元格强制单行：行高不随列宽变化，从设计上杜绝「滚动条↔换行↔高度」回流抖动。
   两行结构的单元格（客户名+简称）每行各自单行截断，整体高度仍恒定。 */
.proj-table td { padding: 5px 7px; vertical-align: middle; white-space: nowrap; }
/* no transition: avoids per-row repaint churn as rows scroll under the cursor */
.proj-table .data-row { }
.proj-table .data-row:hover { background: rgba(201,99,66,0.04); }
.proj-table .data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.035); }

.empty-cell { padding: 48px !important; text-align: center; }
.empty-inner { color: var(--muted); font-size: 14px; }

.proj-no-tag { font-family: monospace; font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,0.04); padding: 2px 7px; border-radius: 5px; white-space: nowrap; }
/* 长文本列截断+省略号（完整内容见悬停提示） */
.contract-name { font-weight: 600; font-size: 13px; color: var(--text); max-width: 190px; overflow: hidden; text-overflow: ellipsis; }
.short-name { font-size: 11.5px; color: var(--muted); margin-top: 2px; max-width: 190px; overflow: hidden; text-overflow: ellipsis; }
.proj-table td.person { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
.proj-table td.text-muted { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
.dept-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 600; white-space: nowrap; }
.person { font-size: 12.5px; color: var(--text); white-space: nowrap; }
.badge-shared { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: rgba(106,27,154,0.1); color: #6a1b9a; font-weight: 600; margin-left: 5px; }
.badge-draft { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: rgba(192,57,43,0.12); color: #c0392b; font-weight: 600; margin-left: 5px; white-space: nowrap; }
.icon-btn-complete { font-size: 11px; font-weight: 600; color: #1565c0; border-color: rgba(21,101,192,0.3); background: rgba(21,101,192,0.06); width: auto; padding: 0 8px; }
.icon-btn-complete:hover { border-color: #1565c0; background: rgba(21,101,192,0.12); color: #1565c0; }
.badge-self { font-size: 12px; padding: 2px 10px; border-radius: 8px; background: rgba(46,125,50,0.1); color: #2e7d32; font-weight: 600; }
.level-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; font-weight: 700; background: rgba(0,0,0,0.05); color: var(--muted); }
.level-chip.lv-S级 { background: rgba(201,162,39,0.15); color: #a8851c; }
.level-chip.lv-A级 { background: rgba(21,101,192,0.12); color: #1565c0; }
.level-chip.lv-B级 { background: rgba(46,125,50,0.1); color: #2e7d32; }
.level-chip.lv-C级 { background: rgba(155,128,112,0.15); color: var(--muted); }
.level-chip.lv-D级 { background: rgba(100,100,100,0.1); color: #888; }
.yn-yes { color: #2e7d32; font-weight: 600; }
.yn-no { color: var(--muted); }
.days-chip { font-size: 12px; padding: 2px 8px; border-radius: 8px; background: rgba(21,101,192,0.08); color: #1565c0; font-weight: 600; white-space: nowrap; }
.invoice-mode { font-size: 12px; padding: 2px 8px; border-radius: 8px; font-weight: 600; }
.mode-full { background: rgba(46,125,50,0.1); color: #2e7d32; }
.mode-diff { background: rgba(245,127,23,0.1); color: #f57f17; }
.text-muted { color: var(--muted); }
.text-sm { font-size: 12px; }
.ctr { text-align: center; }

/* 多选列 + 批量删除工具条 */
.sel-col { width: 36px; padding-left: 10px !important; padding-right: 4px !important; }
.sel-col input { cursor: pointer; width: 15px; height: 15px; accent-color: var(--primary); }
.proj-table .data-row.row-sel { background: rgba(198,40,40,0.05); }
.proj-table .data-row.row-sel:hover { background: rgba(198,40,40,0.08); }
.bulk-bar {
  display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 9px 16px;
  border-radius: 10px; background: rgba(198,40,40,0.06); border: 1px solid rgba(198,40,40,0.25);
}
.bulk-n { font-size: 13px; color: var(--text); }
.bulk-all { border: none; background: none; color: var(--primary); font-size: 12.5px; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.bulk-all-on { font-size: 12.5px; color: var(--primary); font-weight: 700; }
.bulk-del { margin-left: auto; border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.bulk-del:disabled { opacity: .6; cursor: default; }
.bulk-cancel { border: none; background: none; color: var(--muted); font-size: 12.5px; cursor: pointer; }

/* 批量删除确认弹窗 */
.del-warn { font-size: 13px; color: var(--danger); margin: 0 0 12px; line-height: 1.6; }
.del-allnote { font-size: 12.5px; color: var(--text); background: rgba(198,40,40,0.06); border: 1px solid rgba(198,40,40,0.2); border-radius: 8px; padding: 9px 12px; margin-bottom: 12px; line-height: 1.6; }
.del-list { list-style: none; padding: 0; margin: 0 0 12px; max-height: 220px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }
.del-list li { display: flex; align-items: center; gap: 8px; padding: 7px 10px; font-size: 12.5px; border-bottom: 1px solid rgba(0,0,0,0.04); }
.del-list li:last-child { border-bottom: none; }
.del-name { font-weight: 600; color: var(--text); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.del-tip { font-size: 13px; color: var(--text); margin: 0 0 8px; }
.del-input { width: 100%; padding: 8px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 14px; box-sizing: border-box; }
.del-input:focus { border-color: var(--danger); outline: none; }
.btn-danger-solid { border: none; border-radius: 8px; padding: 8px 18px; font-size: 14px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.btn-danger-solid:disabled { opacity: .5; cursor: default; }

.row-actions { display: flex; gap: 4px; justify-content: center; }
.icon-btn {
  width: 28px; height: 28px; border-radius: 7px; border: 1px solid var(--border);
  background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center;
  color: var(--muted); cursor: pointer; transition: all 0.14s;
}
.icon-btn:hover { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.08); }
.icon-btn-danger:hover { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.07); }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; }
.page-btn { padding: 5px 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,252,250,0.7); color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.14s; }
.page-btn:hover { border-color: var(--primary); color: var(--primary); }
.page-btn:disabled { opacity: 0.35; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }

/* Modal */
.modal-subtitle { font-size: 12px; color: var(--muted); margin-top: 3px; }
.derived-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 12px 28px; background: linear-gradient(135deg, rgba(201,99,66,0.06), rgba(201,99,66,0.02));
  border-bottom: 1px solid rgba(201,99,66,0.1);
}
.derived-item { display: flex; align-items: baseline; gap: 5px; }
.derived-label { font-size: 11px; color: var(--muted); font-weight: 500; }
.derived-value { font-size: 16px; font-weight: 700; color: var(--primary); }
.filter-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.filter-hint { font-size: 11.5px; color: var(--muted); margin-left: 4px; white-space: nowrap; }
.search-box {
  position: relative; display: flex; align-items: center; flex: 1; min-width: 320px; max-width: 460px;
}
.search-ico { position: absolute; left: 11px; color: var(--muted); pointer-events: none; }
.search-input {
  width: 100%; padding: 9px 30px 9px 34px; border: 1px solid var(--border); border-radius: 10px;
  background: rgba(255,255,255,0.8); font-size: 13px; color: var(--text); transition: border-color .14s, box-shadow .14s;
}
.search-input:focus {
  outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(201,99,66,0.12);
}
.search-clear {
  position: absolute; right: 8px; width: 18px; height: 18px; border: none; border-radius: 50%;
  background: rgba(0,0,0,0.08); color: var(--muted); font-size: 10px; cursor: pointer;
  display: flex; align-items: center; justify-content: center; line-height: 1;
}
.search-clear:hover { background: rgba(198,40,40,0.12); color: #c62828; }
.filter-reset {
  padding: 8px 14px; border: 1px dashed var(--primary); border-radius: 10px; background: transparent;
  color: var(--primary); font-size: 12.5px; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.filter-reset:hover { background: rgba(201,99,66,0.08); }

/* 关联客户 / 合同 */
.link-section { margin-top: 16px; padding: 14px 28px 4px; border-top: 1px dashed var(--border); }
.link-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; }
.link-title { font-weight: 700; font-size: 13px; color: var(--text); }
.link-sub { font-size: 11.5px; color: var(--muted); }
.add-row { display: flex; gap: 8px; margin-bottom: 8px; }
.add-sel { flex: 1; padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; background: #fff; }
.link-empty { font-size: 12px; color: var(--muted); padding: 4px 0 8px; }
.link-chip { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; background: rgba(255,255,255,0.6); flex-wrap: wrap; }
.chip-name { font-weight: 600; font-size: 12.5px; }
.chip-primary { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 3px; }
.chip-x { margin-left: auto; width: 20px; height: 20px; border: none; border-radius: 50%; background: rgba(0,0,0,0.06); color: var(--muted); cursor: pointer; font-size: 11px; }
.chip-x:hover { background: rgba(198,40,40,0.12); color: #c62828; }
.ct-results { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; max-height: 180px; overflow: auto; }
.ct-result { padding: 7px 10px; font-size: 12.5px; cursor: pointer; border-bottom: 1px solid rgba(0,0,0,0.04); }
.ct-result:hover { background: rgba(201,99,66,0.06); }
.add-hint { float: right; color: var(--primary); font-weight: 600; font-size: 11.5px; }
.mono { font-family: monospace; font-size: 11.5px; }

/* 导入结果弹窗 */
.imp-ok { color: #2e7d32; }
.imp-fail { color: #c62828; }
.imp-body { max-height: calc(82vh - 130px); overflow-y: auto; padding-right: 4px; scrollbar-width: thin; }
.imp-body::-webkit-scrollbar { width: 6px; }
.imp-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.imp-section { margin-bottom: 16px; }
.imp-sec-label { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 6px; padding: 4px 10px; border-radius: 6px; background: rgba(0,0,0,0.04); }
.imp-sec-label.imp-sec-warn { background: rgba(230,81,0,0.08); color: #e65100; }
.imp-sec-list { list-style: none; margin: 0; padding: 0 0 0 10px; display: flex; flex-direction: column; gap: 4px; }
.imp-sec-list li { font-size: 12.5px; color: var(--text); line-height: 1.6; white-space: pre-wrap; word-break: break-all; border-bottom: 1px dashed rgba(0,0,0,0.06); padding-bottom: 4px; }
.imp-sec-list li:last-child { border-bottom: none; }
.imp-empty { font-size: 13px; color: var(--muted); text-align: center; padding: 12px 0; }
.lvl-hint { font-size: 10.5px; font-weight: 600; color: #7a9fd4; cursor: help; margin-left: 4px; }
.proj-st-sel { font-size: 11px; border: 1px solid rgba(180,140,110,.4); border-radius: 7px; padding: 1px 4px; cursor: pointer; background: #fff; }
.proj-st-sel.st-on { color: #2e7d32; } .proj-st-sel.st-pause { color: #e65100; } .proj-st-sel.st-end { color: #9e9e9e; }
.st-pill { display: inline-block; padding: 1px 8px; border-radius: 9px; font-size: 11px; font-weight: 600; }
.st-on { background: #e8f5e9; color: #2e7d32; } .st-pause { background: #fff3e0; color: #e65100; } .st-end { background: #f3f3f3; color: #9e9e9e; }
.stat-draft-row { display: flex; align-items: center; gap: 8px; }
.draft-clear-btn { font-size: 10.5px; padding: 1px 8px; border: 1px solid rgba(46,125,50,.4); background: rgba(46,125,50,.06); color: #2e7d32; border-radius: 9px; cursor: pointer; white-space: nowrap; }
.draft-clear-btn:hover:not(:disabled) { background: rgba(46,125,50,.14); }
.draft-clear-btn:disabled { opacity: .5; cursor: default; }
.pg-jump{display:inline-flex;align-items:center;gap:4px;font-size:13px;color:var(--muted);margin-left:8px}
.pg-jump-input{width:46px;text-align:center;padding:2px 4px;border:1px solid var(--border);border-radius:6px;font-size:13px}
</style>
