<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import ContextMenu from '../components/ContextMenu.vue'
import { useContextMenu } from '../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../utils/clipboard.js'
import { todayCST } from '../constants.js'
import { downloadBlob } from '../utils/download.js'
import EmptyState from '../components/EmptyState.vue'
import ProjectShortNamePicker from '../components/ProjectShortNamePicker.vue'
import ImportResultModal from '../components/ImportResultModal.vue'
import ImportPrecheckModal from '../components/ImportPrecheckModal.vue'
import ColumnFilter from '../components/ColumnFilter.vue'
import SkeletonRow from '../components/SkeletonRow.vue'
import SchemePicker from '../components/SchemePicker.vue'
import { useTableSchemes } from '../composables/useTableSchemes.js'
import { useToast } from '../composables/useToast.js'
const toast = useToast()

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const totalAmount = ref(0)
const totalScheduled = ref(0)
const totalRemaining = ref(0)
const loading = ref(false)
const depts = ref([])
const fileRef = ref(null)
const importing = ref(false)
const importResult = ref(null)
const precheckResult = ref(null)
const precheckBusy = ref(false)
const exporting = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const editId = ref(null)        // null=新增；非空=编辑该记录（共用新增弹窗，prefill + PUT）
const showSchedule = ref(false)
const current = ref(null)
const form = reactive({ applicant:'', department:'', secondary_dept:'', project_short_name:'', approval_number:'', g7_number:'', summary:'', amount:'', payee:'', status:'pending' })
const scheduleForm = reactive({ planned_date:'', total_amount:'' })
// 操作栏补录：二级部门/项目简称（历史数据默认空白，归档记录也可补录这两个字段）
const showMeta = ref(false)
const metaTarget = ref(null)
const metaForm = reactive({ secondary_dept:'', project_short_name:'' })
const metaSaving = ref(false)
function openMeta(it){
  metaTarget.value = it
  Object.assign(metaForm, { secondary_dept: it.secondary_dept || '', project_short_name: it.project_short_name || '' })
  showMeta.value = true
}
async function saveMeta(){
  metaSaving.value = true
  try{
    await api.put(`/approvals/${metaTarget.value.id}`, { ...metaForm })
    showMeta.value = false; load()
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ metaSaving.value = false }
}
// 从台账选中项目时，自动带出该项目的二级部门（台账未填二级部门则保留手填值）
function onProjPicked(p, target){
  if (p.sub_dept) target.secondary_dept = p.sub_dept
}
// ── Excel 风格列头筛选 + 排序 ───────────────────────────────────────────────
const STATUS_OPTS = [
  { value: 'pending', label: '待审批' }, { value: 'approved', label: '审批通过' },
  { value: 'rejected', label: '已拒绝' }, { value: 'canceled', label: '已撤销' },
]
const q = ref('')                  // 顶部全局关键字（跨字段模糊）
const colFilters = reactive({})    // field -> {op, value}
const sortField = ref('')
const sortOrder = ref('')          // 'asc' | 'desc' | ''
const page = ref(1)
const size = ref(50)
const activeFilterCount = computed(() => Object.keys(colFilters).length)
function setColFilter(field, val) {
  if (val == null) delete colFilters[field]
  else colFilters[field] = val
  page.value = 1; clearSelection(); load()
}
function setSort(field, order) {
  sortField.value = order ? field : ''
  sortOrder.value = order || ''
  page.value = 1; load()
}
// 通用筛选方案（表格方案基座）：保存列头筛选 + 排序为命名方案
const schemes = useTableSchemes('pk_approvals', {
  colFilters, sortField, sortOrder,
  onApply: () => { page.value = 1; clearSelection(); load() },
})
function clearAllFilters() {
  Object.keys(colFilters).forEach(k => delete colFilters[k])
  q.value = ''; sortField.value = ''; sortOrder.value = ''
  page.value = 1; clearSelection(); load()
}
function buildParams() {
  const p = { page: page.value, size: size.value }
  if (q.value.trim()) p.q = q.value.trim()
  if (Object.keys(colFilters).length) p.filters = JSON.stringify(colFilters)
  if (sortField.value && sortOrder.value) { p.sort = sortField.value; p.order = sortOrder.value }
  return p
}
let _qTimer = null
watch(() => q.value, () => {
  clearTimeout(_qTimer)
  _qTimer = setTimeout(() => { page.value = 1; clearSelection(); load() }, 350)
})
const statusUpdating = ref({})
const pendingAmountTotal = computed(() => parseFloat(totalAmount.value || 0))
const scheduledTotal = computed(() => parseFloat(totalScheduled.value || 0))
const remainingTotal = computed(() => parseFloat(totalRemaining.value || 0))

// ── 单选/多选：批量删除 + 批量排款 ─────────────────────────────────────────
const selectedIds = ref(new Set())                       // 跨页按 id 记忆选择
const remOf = (it) => parseFloat(it.remaining_amount ?? it.amount) || 0
const pageAllSelected = computed(() => items.value.length > 0 && items.value.every(r => selectedIds.value.has(r.id)))
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedIds.value.size > 0)
function toggleRow(id){ const s = new Set(selectedIds.value); s.has(id) ? s.delete(id) : s.add(id); selectedIds.value = s }
function toggleSelectPage(){ const s = new Set(selectedIds.value); if (pageAllSelected.value) items.value.forEach(r => s.delete(r.id)); else items.value.forEach(r => s.add(r.id)); selectedIds.value = s }
function clearSelection(){ selectedIds.value = new Set() }
// 仅「待审批」可批量通过；汇总只统计可审批记录
const selectedApprovable = computed(() => items.value.filter(i => selectedIds.value.has(i.id) && i.status === 'pending'))
// 仅「审批通过且未归档」可排款；批量排款汇总只统计可排记录（默认金额=剩余可排=申请金额）
const selectedSchedulable = computed(() => items.value.filter(i => selectedIds.value.has(i.id) && i.status === 'approved' && !i.archived))
const batchSchedSummary = computed(() => ({
  count: selectedSchedulable.value.length,
  total: selectedSchedulable.value.reduce((s, i) => s + remOf(i), 0),
}))

// 批量删除（含单选）
const bulkDeleting = ref(false)
const showDelConfirm = ref(false)
const delConfirmText = ref('')
const delConfirmCount = ref(0)
const delConfirmOk = computed(() => delConfirmText.value.trim() === String(delConfirmCount.value))
function bulkDelete(){ if (!selectedCount.value) return; delConfirmCount.value = selectedCount.value; delConfirmText.value = ''; showDelConfirm.value = true }
async function confirmBulkDelete(){
  if (!delConfirmOk.value) return
  bulkDeleting.value = true
  try{
    const r = await api.post('/approvals/bulk-delete', { ids: [...selectedIds.value] })
    showDelConfirm.value = false; clearSelection(); load()
    const d = r.data || {}
    if (d.skipped?.length) toast.warn(`${d.message}\n\n未删除明细：\n` + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n'))
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ bulkDeleting.value = false }
}

// 批量审批通过：仅对所选「待审批」记录生效，非待审批自动跳过
const bulkApproving = ref(false)
async function bulkApprove(){
  const n = selectedApprovable.value.length
  if (!n){ toast.warn('所选记录中没有「待审批」状态的可审批记录'); return }
  if (!confirm(`确认将所选的 ${n} 条「待审批」记录批量审批通过？`)) return
  bulkApproving.value = true
  try{
    const r = await api.post('/approvals/bulk-approve', { ids: selectedApprovable.value.map(i => i.id) })
    clearSelection(); load()
    const d = r.data || {}
    let msg = d.message || '批量审批完成'
    if (d.skipped?.length) { msg += '\n\n跳过明细：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n'); toast.warn(msg) }
    else toast.success(msg)
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ bulkApproving.value = false }
}

// 批量排款（默认日期=今天，默认金额=各记录剩余可排=申请金额；卡片内可逐条调整金额）
const showBatchSched = ref(false)
const batchSchedForm = reactive({ planned_date: '' })
const batchSchedBusy = ref(false)
const batchSchedRows = ref([])   // [{ id, label, remaining, amount }]
const batchSchedTotal = computed(() =>
  batchSchedRows.value.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0))
const batchSchedValid = computed(() => batchSchedRows.value.length > 0 &&
  batchSchedRows.value.every(r => { const a = parseFloat(r.amount); return a > 0 && a <= r.remaining + 1e-6 }))
function openBatchSchedule(){
  if (!batchSchedSummary.value.count){ toast.warn('所选记录中没有「审批通过且未归档」的可排款记录'); return }
  batchSchedForm.planned_date = todayCST()
  batchSchedRows.value = selectedSchedulable.value.map(i => {
    const rem = remOf(i)
    return { id: i.id, label: [i.payee, i.summary || i.applicant].filter(Boolean).join(' · ') || `#${i.id}`,
             remaining: rem, amount: rem }
  })
  showBatchSched.value = true
}
function batchSchedResetAll(){ batchSchedRows.value.forEach(r => { r.amount = r.remaining }) }
async function doBatchSchedule(){
  if (batchSchedBusy.value || !batchSchedValid.value) return
  batchSchedBusy.value = true
  try{
    const items = batchSchedRows.value.map(r => ({ id: r.id, amount: r.amount }))
    const r = await api.post('/approvals/bulk-schedule', { items, planned_date: batchSchedForm.planned_date })
    showBatchSched.value = false; clearSelection(); load()
    const d = r.data || {}
    let msg = d.message || '批量排款完成'
    if (d.skipped?.length) { msg += '\n\n跳过明细：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n'); toast.warn(msg) }
    else toast.success(msg)
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ batchSchedBusy.value = false }
}

const deptChoices = computed(() => {
  const scope = auth.effectiveDepts
  if (auth.isAdmin && !auth.activeDepts.length) return depts.value
  return depts.value.filter(d => scope.includes(d))
})

const jumpPage = ref(1)
function doJump() {
  const tp = Math.ceil(total.value / size.value)
  const p = Math.max(1, Math.min(tp, jumpPage.value || 1))
  page.value = p; load()
}
const loadErr = ref('')
async function load(){ loading.value=true; loadErr.value=''; try{ const r=await api.get('/approvals',{params:buildParams()}); items.value=r.data.items; total.value=r.data.total; totalAmount.value=r.data.total_amount || 0; totalScheduled.value=r.data.total_scheduled || 0; totalRemaining.value=r.data.total_remaining || 0 }catch(e){ loadErr.value = e?.error || e?.message || '加载失败，请刷新重试' }finally{loading.value=false}}
function search(){ page.value=1; clearSelection(); load() }
function setPage(p){ page.value=p; load() }
async function loadDepts(){ try{const r=await api.get('/departments'); depts.value=r.data}catch{}}
function openCreate(){ editId.value=null; Object.assign(form,{ applicant:'', department:deptChoices.value[0]||'', secondary_dept:'', project_short_name:'', approval_number:'', g7_number:'', summary:'', amount:'', payee:'', status:'pending' }); showCreate.value=true }
// 编辑：复用新增弹窗，回填后改走 PUT。已归档（已排款/已拒绝/已撤销）记录为终态不可编辑，
// 仅金额、状态等受后端口径约束（金额仅「待审批」可改、审批/拒绝须审批权限），后端会兜底校验
function openEdit(it){ editId.value=it.id; Object.assign(form,{ applicant:it.applicant||'', department:it.department||'', secondary_dept:it.secondary_dept||'', project_short_name:it.project_short_name||'', approval_number:it.approval_number||'', g7_number:it.g7_number||'', summary:it.summary||'', amount:it.amount||'', payee:it.payee||'', status:it.status||'pending' }); showCreate.value=true }
async function create(){ saving.value=true; try{ if(editId.value){ await api.put(`/approvals/${editId.value}`, form) } else { await api.post('/approvals', form) } showCreate.value=false; load(); toast.success('已保存') } catch(e){ toast.error(e?.msg||e?.error||'操作失败') } finally{ saving.value=false } }
// 双击行 → 编辑（点在勾选框/状态下拉等控件上不触发；已归档不可编辑）
function onRowDblClick(it, e){
  if (e.target.closest('input, button, select, textarea, a')) return
  if (!auth.canCreate || it.archived) return
  openEdit(it)
}
async function updateStatus(it, status){
  const prev = it.status
  it.status = status
  statusUpdating.value[it.id] = true
  try{
    await api.put(`/approvals/${it.id}`,{ status })
  } catch(e){
    it.status = prev
    toast.error(e?.msg || e?.error || '操作失败')
  } finally {
    statusUpdating.value[it.id] = false
  }
}

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const ctx = useContextMenu()
const APR_STATUSES = [
  { v: 'pending', l: '待审批' }, { v: 'approved', l: '审批通过' },
  { v: 'rejected', l: '已拒绝' }, { v: 'canceled', l: '已撤销' },
]
const ROW_COPY_COLS = [
  { key: 'applicant', label: '申请人' },
  { key: 'department', label: '部门' },
  { key: 'project_short_name', label: '项目' },
  { key: 'approval_number', label: '审批单号' },
  { key: 'g7_number', label: 'G7单号' },
  { key: 'summary', label: '摘要' },
  { key: 'amount', label: '金额' },
  { key: 'payee', label: '收款方' },
]
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}
async function copyWholeRow(it) {
  const ok = await copyRowTSV(it, ROW_COPY_COLS, { header: true })
  ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')
}
const ctxItems = computed(() => {
  const i = ctx.menu.payload
  if (!i) return []
  return [
    { key: 'sched', label: '一键排款', icon: 'payment', disabled: i.status !== 'approved', action: r => openSchedule(r) },
    {
      key: 'status', label: '改状态', icon: 'status', hidden: !auth.canCreate,
      children: APR_STATUSES.map(s => ({ key: 'st-' + s.v, label: s.l, icon: 'status', active: i.status === s.v, action: r => updateStatus(r, s.v) })),
    },
    { key: 'edit', label: '编辑审批记录', icon: 'edit', shortcut: 'E', hidden: !auth.canCreate, disabled: i.archived, action: r => openEdit(r) },
    { key: 'meta', label: '补录二级部门 / 项目', icon: 'cell', action: r => openMeta(r) },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: r => copyWholeRow(r) },
        { divider: true },
        { key: 'copy-no', label: '审批单号', icon: 'invoice', hidden: !i.approval_number, action: r => copyField(r.approval_number, r.approval_number) },
        { key: 'copy-g7', label: 'G7 单号', icon: 'invoice', hidden: !i.g7_number, action: r => copyField(r.g7_number, r.g7_number) },
        { key: 'copy-payee', label: '收款方', icon: 'customer', hidden: !i.payee, action: r => copyField(r.payee, r.payee) },
      ],
    },
  ]
})
// 排款前联动：该审批关联项目有「预付」未核销余额时提示，排款后可在付款管理行内核销
const schedPrepaid = ref(null)
function openSchedule(it){
  current.value=it
  // 分批排款：默认带出剩余可排（首次=申请金额），可改小分批流转
  const remaining = parseFloat(it.remaining_amount ?? it.amount) || 0
  Object.assign(scheduleForm,{ planned_date: todayCST(), total_amount: remaining })
  schedPrepaid.value = null
  showSchedule.value=true
  if (it.project_short_name) {
    api.get('/payments/prepaid-balance', { params: { short_name: it.project_short_name } })
      .then(r => { if (r.data?.matched && r.data.count > 0) schedPrepaid.value = r.data })
      .catch(() => {})
  }
}
const schedBusy = ref(false)
async function doSchedule(){
  if (schedBusy.value) return
  schedBusy.value = true
  try{
    const res = await api.post(`/approvals/${current.value.id}/schedule`, scheduleForm)
    showSchedule.value=false; load()
    toast.success(res.data?.message || '排款成功')
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ schedBusy.value = false }
}
async function downloadTemplate(){ const b=await api.get('/approvals/template',{responseType:'blob'}); dl(b,'审批管理导入模板.xlsx') }
const dl = downloadBlob
function triggerImport(){ importResult.value=null; precheckResult.value=null; fileRef.value.click() }

// 智能导入：先规则+AI 预检；发现「需关注」的行才让 AI 介入弹窗协助修正，否则直接导入
async function onImport(e){
  const f=e.target.files?.[0]; if(!f){ return }
  e.target.value=''
  importing.value=true; importResult.value=null; precheckResult.value=null
  try{
    const fd=new FormData(); fd.append('file',f)
    const report=(await api.post('/approvals/import/precheck',fd,{
      headers:{'Content-Type':'multipart/form-data'}, timeout:120000,
    })).data
    if(report && !report.skipPrecheck && report.attention>0){
      precheckResult.value=report; return
    }
    // 全部通过（或超大文件跳过预检）→ 直接导入
    const fd2=new FormData(); fd2.append('file',f)
    const d=(await api.post('/approvals/import',fd2,{
      headers:{'Content-Type':'multipart/form-data'}, timeout:60000,
    })).data||{}
    importResult.value={
      created:d.created||0, skipped:d.skipped||0, errors:d.errors||[],
      message:`新增 ${d.created||0} 条，跳过 ${d.skipped||0} 条（含错误）`,
    }
    load()
  }catch(err){ importResult.value={ error: err?.msg || err?.error || '导入失败，请检查文件格式或表头' } }
  finally{ importing.value=false }
}

async function onPrecheckApply({ mode, rows, okRows }){
  precheckBusy.value=true
  try{
    if(mode==='download'){
      const b=await api.post('/approvals/import/apply',{rows,okRows,mode:'download'},{responseType:'blob',timeout:90000})
      dl(b,'审批记录_修正版.xlsx')
    }else{
      const d=(await api.post('/approvals/import/apply',{rows,okRows,mode:'import'},{timeout:90000})).data||{}
      precheckResult.value=null
      importResult.value={ created:d.created||0, skipped:d.skipped||0, errors:d.errors||[], message:d.message }
      if(d.created>0) load()
    }
  }catch(err){ toast.error(err?.msg||err?.error||'操作失败') }
  finally{ precheckBusy.value=false }
}
async function doExport(){ exporting.value=true; try{ const b=await api.get('/approvals/export',{params:buildParams(),responseType:'blob'}); dl(b,'审批管理.xlsx') } finally{ exporting.value=false } }

const onScopeChange = () => {
  // 事业部范围切换：若列头筛了已超出范围的事业部，清掉该列筛选
  const sel = colFilters.department
  if (sel && Array.isArray(sel.value) && sel.value.some(d => !auth.effectiveDepts.includes(d))) {
    delete colFilters.department
  }
  page.value = 1
  load()
}
onMounted(async ()=>{
  loadDepts()
  // 有默认方案则套用并由其触发加载；否则常规加载
  const applied = await schemes.loadAndApplyDefault()
  if (!applied) load()
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(()=>window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template><div>
  <div class="topbar"><h1>审批管理</h1><div style="display:flex;gap:8px">
    <button class="btn btn-ghost btn-sm" @click="downloadTemplate">模板</button>
    <button class="btn btn-ghost btn-sm" :disabled="importing" @click="triggerImport"
            title="导入会自动做规则校验 + AI 智能复核；发现问题时 AI 会介入，协助你就地修正后再导入">{{ importing?'导入中…':'导入' }}</button>
    <button class="btn btn-ghost btn-sm" @click="doExport">{{ exporting?'导出中…':'导出' }}</button>
    <button v-if="auth.canCreate" class="btn btn-primary" @click="openCreate">+ 新增审批记录</button>
  </div></div>
  <input ref="fileRef" type="file" accept=".xlsx,.xls,.csv" style="display:none" @change="onImport" />
  <div class="card approval-card"><div class="filter-row">
    <div class="filter-bar">
    <input v-model="q" class="global-search" placeholder="🔍 全局搜索：申请人 / 编号 / 项目 / 摘要 / 收款方…" @keyup.enter="search"/>
    <button class="btn btn-ghost btn-sm" @click="search">搜索</button>
    <button v-if="activeFilterCount || q || sortField" class="btn btn-ghost btn-sm clear-all" @click="clearAllFilters">清除全部筛选<span v-if="activeFilterCount">（{{ activeFilterCount }}）</span></button>
    <SchemePicker :ctl="schemes" :can-public="auth.canCreate" :is-super-admin="auth.isSuperAdmin" />
    </div>
  </div>
  <div v-if="loadErr" class="err-banner">⚠️ {{ loadErr }} <button class="btn-link" @click="load()">重试</button></div>
  <EmptyState v-else-if="!loading && !items.length" empty :text="activeFilterCount || q ? '暂无匹配记录' : '暂无审批记录，点击「新增」创建第一条记录'" />
  <div v-if="!loadErr" class="table-wrap page-scroll"><table class="approval-table">
    <colgroup>
      <col class="cg-sel" /><!-- 选择 -->
      <col style="width:7%" /><!-- 申请人 -->
      <col style="width:8%" /><!-- 所属事业部 -->
      <col style="width:8%" /><!-- 二级部门 -->
      <col style="width:11%" /><!-- 项目简称 -->
      <col style="width:11%" /><!-- 审批编号 -->
      <col style="width:9%" /><!-- G7编号 -->
      <col style="width:15%" /><!-- 摘要 -->
      <col style="width:9%" /><!-- 申请金额 -->
      <col style="width:12%" /><!-- 收款主体 -->
      <col style="width:10%" /><!-- 审批状态 -->
    </colgroup>
    <thead><tr>
      <th class="sel-col"><input type="checkbox" :checked="pageAllSelected" :indeterminate.prop="hasSelection && !pageAllSelected" title="全选本页" @change="toggleSelectPage" /></th>
      <th><ColumnFilter label="申请人" field="applicant" type="text" :model-value="colFilters.applicant" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('applicant',v)" @sort="o=>setSort('applicant',o)" /></th>
      <th><ColumnFilter label="所属事业部" field="department" type="enum" :options="deptChoices" :model-value="colFilters.department" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('department',v)" @sort="o=>setSort('department',o)" /></th>
      <th><ColumnFilter label="二级部门" field="secondary_dept" type="text" :model-value="colFilters.secondary_dept" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('secondary_dept',v)" @sort="o=>setSort('secondary_dept',o)" /></th>
      <th><ColumnFilter label="项目简称" field="project_short_name" type="text" :model-value="colFilters.project_short_name" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('project_short_name',v)" @sort="o=>setSort('project_short_name',o)" /></th>
      <th><ColumnFilter label="审批编号" field="approval_number" type="text" :model-value="colFilters.approval_number" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('approval_number',v)" @sort="o=>setSort('approval_number',o)" /></th>
      <th><ColumnFilter label="G7编号" field="g7_number" type="text" :model-value="colFilters.g7_number" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('g7_number',v)" @sort="o=>setSort('g7_number',o)" /></th>
      <th><ColumnFilter label="摘要" field="summary" type="text" :model-value="colFilters.summary" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('summary',v)" @sort="o=>setSort('summary',o)" /></th>
      <th><ColumnFilter label="申请金额" field="amount" type="number" :model-value="colFilters.amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('amount',v)" @sort="o=>setSort('amount',o)" /></th>
      <th class="amt-h"><ColumnFilter label="已排金额" field="scheduled_amount" type="number" :model-value="colFilters.scheduled_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('scheduled_amount',v)" @sort="o=>setSort('scheduled_amount',o)" /></th>
      <th class="amt-h"><ColumnFilter label="未排金额" field="remaining_amount" type="number" :model-value="colFilters.remaining_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('remaining_amount',v)" @sort="o=>setSort('remaining_amount',o)" /></th>
      <th><ColumnFilter label="收款主体" field="payee" type="text" :model-value="colFilters.payee" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('payee',v)" @sort="o=>setSort('payee',o)" /></th>
      <th><ColumnFilter label="审批状态" field="status" type="enum" :options="STATUS_OPTS" :model-value="colFilters.status" :sortable="false" @update:model-value="v=>setColFilter('status',v)" /></th>
      </tr></thead>
    <tbody>
      <template v-if="loading">
        <SkeletonRow v-for="n in 8" :key="n" :cols="13" />
      </template>
      <template v-else>
      <tr v-for="i in items" :key="i.id" :class="{ 'row-sel': selectedIds.has(i.id) }" @contextmenu.prevent="ctx.open($event, i)" @dblclick="onRowDblClick(i, $event)">
      <td class="sel-col"><input type="checkbox" :checked="selectedIds.has(i.id)" @change="toggleRow(i.id)" /></td>
      <td>{{i.applicant}}</td><td>{{i.department}}</td>
      <td class="meta-cell">{{ i.secondary_dept || '—' }}</td>
      <td class="meta-cell" :title="i.project_short_name">{{ i.project_short_name || '—' }}</td>
      <td class="mono">{{i.approval_number}}</td><td class="mono g7-cell">{{i.g7_number || '—'}}</td><td class="summary">{{i.summary}}</td><td class="amt">{{i.amount}}</td>
      <td class="amt sched-c">{{ parseFloat(i.scheduled_amount) > 0 ? i.scheduled_amount : '—' }}</td>
      <td class="amt remain-c" :class="{ 'remain-zero': parseFloat(i.remaining_amount) <= 0 }">{{ parseFloat(i.remaining_amount) > 0 ? i.remaining_amount : '—' }}</td>
      <td class="payee">{{i.payee}}</td>
      <td>
        <select :value="i.status" :disabled="statusUpdating[i.id]" @change="updateStatus(i, $event.target.value)">
          <option value="pending">待审批</option><option value="approved">审批通过</option><option value="rejected">已拒绝</option><option value="canceled">已撤销</option>
        </select>
      </td>
      </tr>
      </template>
    </tbody>
  </table></div>

  <!-- 浮动批量操作条：Teleport 到 body 固定在视口底部，全选后无需下拉即可操作 -->
  <Teleport to="body">
    <div v-if="!loading && items.length && hasSelection && !showBatchSched && !showDelConfirm && (auth.canDelete || auth.canCreate)" class="bulk-bar">
      <span class="bulk-n">已选 <strong>{{ selectedCount }}</strong> 条</span>
      <button v-if="auth.canCreate" class="bulk-approve" :disabled="bulkApproving || !selectedApprovable.length" @click="bulkApprove">{{ bulkApproving ? '审批中…' : `批量通过（待审 ${selectedApprovable.length} 条）` }}</button>
      <button v-if="auth.canCreate" class="bulk-act" :disabled="!batchSchedSummary.count" @click="openBatchSchedule">批量排款（可排 {{ batchSchedSummary.count }} 条）</button>
      <button v-if="auth.canDelete" class="bulk-del" :disabled="bulkDeleting" @click="bulkDelete">{{ bulkDeleting ? '删除中…' : `批量删除(${selectedCount})` }}</button>
      <button class="bulk-cancel" @click="clearSelection">取消</button>
    </div>
  </Teleport>

  <!-- 吸底合计 + 翻页：Teleport 到 body 以逃脱 .card transform 产生的 fixed 包含块 -->
  <Teleport to="body">
    <div v-if="!loading && items.length && !hasSelection && !showCreate && !showSchedule && !showBatchSched && !showDelConfirm" class="bottom-bar">
      <div class="bb-summary">
        <span class="bb-item"><i>合计</i><b>{{ total }}</b> 条</span>
        <span class="bb-item"><i>总申请</i><b>{{ pendingAmountTotal.toFixed(2) }}</b> 元</span>
        <span class="bb-item ok"><i>已排合计</i><b>{{ scheduledTotal.toFixed(2) }}</b> 元</span>
        <span class="bb-item warn"><i>未排合计</i><b>{{ remainingTotal.toFixed(2) }}</b> 元</span>
      </div>
      <div v-if="total > size" class="bb-pager">
        <button :disabled="page <= 1" class="page-btn" @click="setPage(page - 1)">‹ 上一页</button>
        <span class="page-info">{{ page }} / {{ Math.ceil(total / size) || 1 }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="setPage(page + 1)">下一页 ›</button>
        <span class="pg-jump">到第<input type="number" v-model.number="jumpPage" :min="1" class="pg-jump-input" :placeholder="`1-${Math.ceil(total / size) || 1}`" @keyup.enter="doJump" />页</span>
      </div>
    </div>
  </Teleport>
  </div>

  <Teleport to="body"><div v-if="showCreate" class="modal-overlay" tabindex="-1" @keyup.escape.capture="showCreate = false"><div class="modal-box"><div class="modal-header"><h3>{{ editId ? '编辑审批记录' : '新增审批记录' }}</h3></div><div class="modal-body">
    <p v-if="editId" style="font-size:12px;color:var(--muted);margin:0 0 12px">
      申请金额仅「待审批」状态可改（已审批请先退回待审批）；设为「审批通过/已拒绝」需审批权限；已排款/已归档记录不可在此编辑。
    </p>
    <div class="form-grid">
    <label class="form-field"><span>申请人*</span><input v-model="form.applicant"/></label>
    <label class="form-field"><span>所属事业部*</span><select v-model="form.department"><option v-for="d in deptChoices" :key="d" :value="d">{{d}}</option></select></label>
    <label class="form-field"><span>二级部门</span><input v-model="form.secondary_dept" placeholder="选填，如：华东项目部"/></label>
    <label class="form-field"><span>项目简称</span><ProjectShortNamePicker v-model="form.project_short_name" @picked="p => onProjPicked(p, form)"/></label>
    <label class="form-field"><span>审批编号</span><input v-model="form.approval_number" placeholder="21位数字；留空自动填21个0占位"/></label>
    <label class="form-field"><span>G7编号</span><input v-model="form.g7_number" placeholder="选填，最多21位数字" maxlength="21"/></label>
    <label class="form-field"><span>摘要</span><input v-model="form.summary"/></label>
    <label class="form-field"><span>申请金额*</span><input v-model="form.amount" type="number" step="0.01"/></label>
    <label class="form-field"><span>收款主体</span><input v-model="form.payee"/></label>
    <label class="form-field"><span>审批状态</span><select v-model="form.status"><option value="pending">待审批</option><option value="approved">审批通过</option><option value="rejected">已拒绝</option><option value="canceled">已撤销</option></select></label>
  </div></div><div class="modal-footer"><button class="btn btn-ghost" @click="showCreate=false">取消</button><button class="btn btn-primary" :disabled="saving" @click="create">保存</button></div></div></div></Teleport>

  <Teleport to="body"><div v-if="showSchedule" class="modal-overlay"><div class="modal-box"><div class="modal-header"><h3>排款（支持分批）</h3></div><div class="modal-body">
    <div class="sched-progress">
      <span>申请金额 <b>{{ current?.amount }}</b></span>
      <span>已排款 <b style="color:#2e7d32">{{ current?.scheduled_amount || 0 }}</b></span>
      <span>剩余可排 <b style="color:#e65100">{{ current?.remaining_amount ?? current?.amount }}</b></span>
    </div>
    <p style="font-size:12px;color:var(--muted);margin:0 0 10px">
      本次金额小于剩余可排时为分批排款：本次先流转付款管理，记录留在审批管理可继续排；排满申请金额自动归档。
    </p>
    <div v-if="schedPrepaid" class="sched-prepaid-hint">
      💡 项目「{{ schedPrepaid.short_name }}」尚有 <b>{{ schedPrepaid.count }}</b> 笔预付未核销，
      余额合计 <b>{{ schedPrepaid.total_balance }}</b> 元。建议排款后到付款管理该行点「核销」，
      用预付冲抵以减少重复付现。
    </div>
    <div class="form-grid">
    <label class="form-field"><span>计划日期*</span><input v-model="scheduleForm.planned_date" type="date"/></label>
    <label class="form-field"><span>计划金额*</span><input v-model="scheduleForm.total_amount" type="number" step="0.01"/></label>
  </div></div><div class="modal-footer"><button class="btn btn-ghost" @click="showSchedule=false">取消</button><button class="btn btn-primary" :disabled="schedBusy" @click="doSchedule">{{ schedBusy ? '排款中…' : '保存并排款' }}</button></div></div></div></Teleport>

  <Teleport to="body"><div v-if="showMeta" class="modal-overlay"><div class="modal-box"><div class="modal-header"><h3>补录：二级部门 / 项目简称</h3></div><div class="modal-body">
    <p style="font-size:12px;color:var(--muted);margin:0 0 12px">
      {{ metaTarget?.applicant }} · {{ metaTarget?.department }} · ¥{{ metaTarget?.amount }}（{{ metaTarget?.summary || '无摘要' }}）<br/>
      项目简称须与项目台账匹配；填写后该审批/后续排款即可按项目维度打通应收、现金流与分析。
    </p>
    <div class="form-grid">
      <label class="form-field"><span>二级部门</span><input v-model="metaForm.secondary_dept" placeholder="选填，如：华东项目部"/></label>
      <label class="form-field"><span>项目简称</span><ProjectShortNamePicker v-model="metaForm.project_short_name" @picked="p => onProjPicked(p, metaForm)"/></label>
    </div>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showMeta=false">取消</button><button class="btn btn-primary" :disabled="metaSaving" @click="saveMeta">保存</button></div></div></div></Teleport>

  <!-- 批量排款 -->
  <Teleport to="body"><div v-if="showBatchSched" class="modal-overlay"><div class="modal-box batch-box"><div class="modal-header"><h3>批量排款</h3></div><div class="modal-body">
    <div class="sched-progress">
      <span>可排记录 <b>{{ batchSchedRows.length }}</b> 条</span>
      <span>合计金额 <b style="color:#2e7d32">{{ batchSchedTotal.toFixed(2) }}</b> 元</span>
    </div>
    <p style="font-size:12px;color:var(--muted);margin:0 0 10px">
      默认按各记录「剩余可排（首次=申请金额）」各排一笔流转付款管理，可逐条调小做分批排款（不得超过剩余可排）；所选中非「审批通过/已归档」的记录已自动排除。
    </p>
    <div class="form-grid" style="margin-bottom:10px">
      <label class="form-field"><span>计划日期*</span><input v-model="batchSchedForm.planned_date" type="date"/></label>
    </div>
    <div class="batch-rows-head">
      <span>本次排款金额（共 {{ batchSchedRows.length }} 条）</span>
      <button type="button" class="batch-reset" @click="batchSchedResetAll">全部设为剩余可排</button>
    </div>
    <div class="batch-rows">
      <div v-for="r in batchSchedRows" :key="r.id" class="batch-row">
        <span class="batch-row-label" :title="r.label">{{ r.label }}</span>
        <span class="batch-row-rem">剩余 {{ r.remaining.toFixed(2) }}</span>
        <input v-model="r.amount" type="number" step="0.01" min="0" :max="r.remaining"
               class="batch-row-amt" :class="{ bad: !(parseFloat(r.amount) > 0 && parseFloat(r.amount) <= r.remaining + 1e-6) }"/>
      </div>
    </div>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showBatchSched=false">取消</button><button class="btn btn-primary" :disabled="batchSchedBusy || !batchSchedValid" @click="doBatchSchedule">{{ batchSchedBusy ? '排款中…' : `确认排款 ${batchSchedRows.length} 条` }}</button></div></div></div></Teleport>

  <!-- 批量删除二次确认 -->
  <Teleport to="body"><div v-if="showDelConfirm" class="modal-overlay"><div class="modal-box" style="max-width:420px"><div class="modal-header"><h3>确认删除 {{ delConfirmCount }} 条审批记录</h3></div><div class="modal-body">
    <p class="del-warn">⚠ 删除后不可恢复；已排款（已关联付款管理）的记录将自动跳过。</p>
    <p class="del-tip">请输入待删条数 <strong>{{ delConfirmCount }}</strong> 以确认：</p>
    <input v-model="delConfirmText" class="del-input" :placeholder="`输入 ${delConfirmCount}`" @keyup.enter="confirmBulkDelete"/>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showDelConfirm=false">取消</button><button class="btn-danger-solid" :disabled="!delConfirmOk || bulkDeleting" @click="confirmBulkDelete">{{ bulkDeleting ? '删除中…' : '确认删除' }}</button></div></div></div></Teleport>

  <ImportResultModal :result="importResult" @close="importResult = null" />
  <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy"
    @close="precheckResult = null" @apply="onPrecheckApply" />

  <!-- 右键上下文菜单 -->
  <ContextMenu :ctx="ctx" :items="ctxItems" />
</div></template>

<style scoped>
.err-banner { background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; color: #856404; display: flex; align-items: center; gap: 8px; }
.approval-card { padding: 12px; }
/* 固定视口布局：卡片底部为吸底合计条预留空间 */
/* 吸底 bottom-bar(36px) 占位：滚动区底部留白，最后一行不被遮挡 */
.table-wrap.page-scroll { padding-bottom: 40px; }
.filter-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; flex-shrink: 0; }
.filter-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.global-search { min-width: 340px; flex: 0 1 420px; }
.clear-all { color: var(--primary); }
/* 列头允许漏斗按钮溢出展示，不被裁切 */
.approval-table thead th { overflow: visible; }
/* 表头随表体滚动吸顶（不透明背景，避免行透出） */
.table-wrap.page-scroll thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }

/* .bottom-bar, .bb-*, .page-btn, .page-info → global styles in style.css */
.approval-table { width: 100%; table-layout: fixed; }
/* 列宽由 <colgroup> 统一声明（11 列）；选择列固定窄宽，其余按百分比分配 */
.approval-table col.cg-sel { width: 34px; }
/* 行高/内边距对齐全局表格（付款管理），保证两个页面观感一致 */
.approval-table th, .approval-table td { padding: 11px 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.approval-table th.sel-col, .approval-table td.sel-col { text-align: center; overflow: visible; padding: 11px 4px; }
.approval-table th.sel-col input, .approval-table td.sel-col input { cursor: pointer; }
/* 审批状态列（末列）内容（下拉）不裁切，以本列宽为限 */
.approval-table th:last-child, .approval-table td:last-child {
  overflow: visible; text-overflow: clip; white-space: normal;
}
.g7-cell { color: var(--muted); font-size: 11.5px; }
.approval-table tr.row-sel td { background: rgba(201,99,66,0.06); }
/* 批量操作条：固定浮动在视口底部居中，全选后无需下拉即可操作 */
.bulk-bar { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); z-index: 1200;
  display: flex; align-items: center; gap: 12px; padding: 10px 18px;
  border-radius: 12px; background: var(--card); border: 1px solid rgba(198,40,40,0.35);
  box-shadow: 0 8px 28px rgba(0,0,0,0.18); }
.bulk-n { font-size: 13px; color: var(--text); }
.bulk-approve { margin-left: auto; border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: #2e7d32; color: #fff; }
.bulk-approve:disabled { opacity: .5; cursor: default; }
.bulk-act { border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--primary); color: #fff; }
.bulk-act:disabled { opacity: .5; cursor: default; }
.bulk-del { border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.bulk-del:disabled { opacity: .6; cursor: default; }
.bulk-cancel { border: none; background: none; color: var(--muted); font-size: 12.5px; cursor: pointer; }
.del-warn { font-size: 13px; color: var(--danger); margin: 0 0 12px; line-height: 1.6; }
.del-tip { font-size: 13px; color: var(--text); margin: 0 0 8px; }
.del-input { width: 100%; padding: 8px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 14px; box-sizing: border-box; }
.del-input:focus { border-color: var(--danger); outline: none; }
.btn-danger-solid { border: none; border-radius: 8px; padding: 8px 18px; font-size: 14px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.btn-danger-solid:disabled { opacity: .5; cursor: default; }
.meta-cell { color: var(--muted); font-size: 12.5px; }
.sched-prepaid-hint { font-size: 12.5px; color: #8a6d1a; background: rgba(255,213,79,0.14);
  border: 1px solid rgba(255,193,7,0.35); border-radius: 9px; padding: 9px 12px; margin-bottom: 12px; line-height: 1.7; }
.sched-prepaid-hint b { color: #6d4c00; }
.sched-progress { display: flex; gap: 18px; font-size: 13px; color: var(--muted);
  background: rgba(201,99,66,.05); border-radius: 9px; padding: 9px 12px; margin-bottom: 10px; }
.sched-progress b { font-variant-numeric: tabular-nums; color: var(--text); }
.batch-box { max-width: 560px; }
.batch-rows-head { display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; color: var(--muted); margin: 0 0 6px; }
.batch-reset { border: none; background: none; color: var(--primary); font-size: 12px; cursor: pointer; padding: 0; }
.batch-rows { max-height: 42vh; overflow-y: auto; border: 1px solid var(--border); border-radius: 9px; }
.batch-row { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-bottom: 1px solid var(--border); }
.batch-row:last-child { border-bottom: none; }
.batch-row-label { flex: 1; min-width: 0; font-size: 12.5px; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.batch-row-rem { font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.batch-row-amt { width: 120px; height: 30px; padding: 0 8px; border: 1.5px solid var(--border);
  border-radius: 7px; font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; box-sizing: border-box; }
.batch-row-amt:focus { border-color: var(--primary); outline: none; }
.batch-row-amt.bad { border-color: var(--danger); background: rgba(198,40,40,0.05); }
.sched-sub { font-size: 10.5px; color: #2e7d32; font-weight: 600; margin-top: 1px; }
.ops-btns { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.ops-btns .btn { padding: 4px 8px; font-size: 12px; white-space: nowrap; }
/* 编辑图标按钮：与同行操作按钮等高，emoji 居中 */
.ops-btns .icon-btn { padding: 4px 7px; line-height: 1; }
.ops-btns .icon-btn:disabled { opacity: .4; cursor: default; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.amt { text-align: right; font-variant-numeric: tabular-nums; }
.amt-h { text-align: right; }
.sched-c { color: #2e7d32; font-weight: 600; }
.remain-c { color: #e65100; font-weight: 600; }
.remain-c.remain-zero { color: var(--muted); font-weight: 400; }
.summary, .payee { max-width: 100%; }
.approval-table select { width: 100%; min-width: 0; max-width: 100%; height: 32px; font-size: 12.5px; padding: 0 22px 0 6px; background-position: right 6px center; }
.pg-jump { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); margin-left: 8px; }
.pg-jump-input { width: 46px; text-align: center; padding: 2px 4px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
</style>
