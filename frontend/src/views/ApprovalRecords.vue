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
import TransportPrecheckModal from '../components/TransportPrecheckModal.vue'
import ColumnFilter from '../components/ColumnFilter.vue'
import SkeletonRow from '../components/SkeletonRow.vue'
import SchemePicker from '../components/SchemePicker.vue'
import { useTableSchemes } from '../composables/useTableSchemes.js'
import { useToast } from '../composables/useToast.js'
import { useAsyncExport } from '../composables/useAsyncExport.js'
import { useRangeSelection } from '../composables/useRangeSelection.js'
import { createRequestLane } from '../utils/requestLane.js'
import { cachedGet } from '../api/refCache.js'
const toast = useToast()
const { exporting: bgExporting, startExport } = useAsyncExport()
// Excel 式区域选择 + 复制（忽略首列复选框）
const rangeSel = useRangeSelection({ ignoreCols: [0], onCopy: n => toast.success(`已复制 ${n} 个单元格，可粘贴进 Excel`) })

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
// 运输事业部对账单专用导入：原表 → 「已通过」审批记录（金额取绝对值、对账单号去重）
const transportFileRef = ref(null)
const importingTransport = ref(false)
const canTransport = computed(() =>
  auth.canCreate && (auth.isSuperAdmin || auth.effectiveDepts.includes('运输事业部')))
const exporting = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const editId = ref(null)        // null=新增；非空=编辑该记录（共用新增弹窗，prefill + PUT）
const showSchedule = ref(false)
const current = ref(null)
const form = reactive({ applicant:'', department:'', secondary_dept:'', project_short_name:'', approval_number:'', g7_number:'', summary:'', notes:'', amount:'', payee:'', status:'pending' })
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
  numbersFilter.value = ''; numbersText.value = ''
  page.value = 1; clearSelection(); load()
}
// 批量单号筛选
const numbersFilter = ref('')
const showNumbersBox = ref(false)
const numbersText = ref('')
const parsedNumbers = computed(() =>
  [...new Set(numbersText.value.split(/[\s,+;|，、；／/]+/).map(s => s.trim()).filter(Boolean))])
function applyNumbers() {
  numbersFilter.value = parsedNumbers.value.join(',')
  showNumbersBox.value = false
  page.value = 1; clearSelection(); load()
}
function clearNumbers() {
  numbersText.value = ''; numbersFilter.value = ''
  showNumbersBox.value = false
  page.value = 1; clearSelection(); load()
}
function buildParams() {
  const p = { page: page.value, size: size.value }
  if (q.value.trim()) p.q = q.value.trim()
  if (Object.keys(colFilters).length) p.filters = JSON.stringify(colFilters)
  if (sortField.value && sortOrder.value) { p.sort = sortField.value; p.order = sortOrder.value }
  if (numbersFilter.value) p.numbers = numbersFilter.value
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

// ── 排款管理：展开计划批次面板（点击已排金额列）────────────────────────────────
const aprSchedExpanded = ref(new Set())          // approval IDs with open sched panel
const aprSchedCache = ref({})                    // id → { loading, data, error }
const aprPlanEdit = reactive({ approval_id: null, id: null, planned_date: '', amount: '', notes: '', busy: false })

function isAprSchedExpanded(id) { return aprSchedExpanded.value.has(id) }

async function toggleAprSchedDetail(rec) {
  const s = new Set(aprSchedExpanded.value)
  if (s.has(rec.id)) {
    s.delete(rec.id)
    if (aprPlanEdit.approval_id === rec.id) cancelAprPlanEdit()
  } else {
    s.add(rec.id)
    if (!aprSchedCache.value[rec.id] || aprSchedCache.value[rec.id].error) {
      await loadAprSchedDetail(rec.id)
    }
  }
  aprSchedExpanded.value = s
}

async function loadAprSchedDetail(aprid) {
  aprSchedCache.value = { ...aprSchedCache.value, [aprid]: { loading: true, data: null, error: '' } }
  try {
    const r = await api.get(`/approvals/${aprid}/schedule-detail`)
    aprSchedCache.value = { ...aprSchedCache.value, [aprid]: { loading: false, data: r.data, error: '' } }
  } catch (e) {
    aprSchedCache.value = { ...aprSchedCache.value, [aprid]: { loading: false, data: null, error: e?.error || e?.msg || '加载失败' } }
  }
}

function cancelAprPlanEdit() { aprPlanEdit.approval_id = null; aprPlanEdit.id = null }

function startAprPlanEdit(aprid, pi) {
  aprPlanEdit.approval_id = aprid
  aprPlanEdit.id = pi.id
  aprPlanEdit.planned_date = pi.planned_date
  aprPlanEdit.amount = pi.amount
  aprPlanEdit.notes = pi.notes || ''
  aprPlanEdit.busy = false
}

async function saveAprPlanEdit(aprid) {
  const payment_id = aprSchedCache.value[aprid]?.data?.payment_id
  if (!payment_id) return
  const amt = parseFloat(aprPlanEdit.amount)
  if (!aprPlanEdit.planned_date) { toast.warn('请填写计划日期'); return }
  if (!(amt > 0)) { toast.warn('计划金额必须大于0'); return }
  aprPlanEdit.busy = true
  try {
    const body = { planned_date: aprPlanEdit.planned_date, amount: amt, notes: aprPlanEdit.notes }
    const res = await api.put(`/payments/${payment_id}/plan-items/${aprPlanEdit.id}`, body)
    toast.success(res.data?.message || '已调整排款批次')
    cancelAprPlanEdit()
    await loadAprSchedDetail(aprid)
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '调整失败') }
  finally { aprPlanEdit.busy = false }
}

async function removeAprPlanItem(aprid, pi) {
  const cache = aprSchedCache.value[aprid]?.data
  const payment_id = cache?.payment_id
  if (!payment_id) return
  const batchCount = cache?.plan_items?.length || 0
  if (batchCount <= 1) {
    toast.warn('最后一批计划不可单独撤回——如需退回全部排款，请使用「退回全部排款」')
    return
  }
  if (!confirm(`撤回第${pi.seq}批排款（${pi.planned_date} · ¥${pi.amount}）？\n来源审批已排款同步扣减，可继续补排。`)) return
  try {
    const res = await api.delete(`/payments/${payment_id}/plan-items/${pi.id}`)
    toast.success(res.data?.message || '已撤回')
    await loadAprSchedDetail(aprid)
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '撤回失败') }
}

async function returnFullSchedule(rec) {
  if (!confirm(`退回「${rec.payee || rec.applicant}」全部排款（¥${rec.scheduled_amount}）？\n关联付款管理记录将删除，审批已排款归零，可重新排款。`)) return
  try {
    const r = await api.post('/approvals/bulk-return-schedule', { ids: [rec.id] })
    const d = r.data || {}
    if (d.skipped?.length) {
      toast.warn(d.message + '\n' + d.skipped.map(s => s.reason).join('\n'))
    } else {
      toast.success(d.message || '已退回排款')
    }
    delete aprSchedCache.value[rec.id]
    aprSchedExpanded.value = new Set([...aprSchedExpanded.value].filter(id => id !== rec.id))
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '退回失败') }
}

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
// 有已排款的记录可「批量退回排款」（不管是否归档）
const selectedWithSchedule = computed(() => items.value.filter(i => selectedIds.value.has(i.id) && parseFloat(i.scheduled_amount) > 0))
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

// 单条删除（右键菜单）：复用批量删除端点，已排款记录后端自动跳过
async function deleteOne(rec){
  const label = [rec.payee, rec.summary || rec.applicant].filter(Boolean).join(' · ') || `#${rec.id}`
  if (!confirm(`确定删除审批记录「${label}」（¥${rec.amount}）？\n已排款（已关联付款管理）的记录将自动跳过；删除不可恢复。`)) return
  try{
    const r = await api.post('/approvals/bulk-delete', { ids: [rec.id] })
    const d = r.data || {}
    if (d.deleted > 0){ toast.success('已删除'); load() }
    else { toast.warn(d.skipped?.[0]?.reason || '未删除（可能已排款，请先在付款管理删除对应排款）') }
  } catch(e){ toast.error(e?.msg || e?.error || '删除失败') }
}

// 批量退回排款：退回所选有已排款记录的排款，已排款归零可重新排款
const bulkReturning = ref(false)
async function bulkReturnSchedule(){
  // 跨页：发送全部已选 id，后端对无已排款的记录自动跳过（单次上限 200）
  if (!selectedCount.value){ toast.warn('请先选择记录'); return }
  if (!confirm(`批量退回所选 ${selectedCount.value} 条记录的排款？\n无已排款的记录自动跳过；关联付款管理记录将删除，已排款归零，可重新排款。`)) return
  bulkReturning.value = true
  try {
    const ids = [...selectedIds.value]
    const r = await api.post('/approvals/bulk-return-schedule', { ids })
    const d = r.data || {}
    // 清除已退回审批的展开缓存
    ids.forEach(id => { delete aprSchedCache.value[id] })
    aprSchedExpanded.value = new Set([...aprSchedExpanded.value].filter(id => !selectedIds.value.has(id)))
    clearSelection(); load()
    let msg = d.message || '批量退回完成'
    if (d.skipped?.length) { msg += '\n\n跳过明细：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n'); toast.warn(msg) }
    else toast.success(msg)
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ bulkReturning.value = false }
}

// 批量审批通过：跨页发送全部已选 id，后端对非「待审批」记录自动跳过
const bulkApproving = ref(false)
async function bulkApprove(){
  if (!selectedCount.value){ toast.warn('请先选择记录'); return }
  if (!confirm(`确认将所选 ${selectedCount.value} 条记录批量审批通过？\n非「待审批」状态将自动跳过。`)) return
  bulkApproving.value = true
  try{
    const r = await api.post('/approvals/bulk-approve', { ids: [...selectedIds.value] })
    clearSelection(); load()
    const d = r.data || {}
    let msg = d.message || '批量审批完成'
    if (d.skipped?.length) { msg += '\n\n跳过明细：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n'); toast.warn(msg) }
    else toast.success(msg)
  } catch(e){ toast.error(e?.msg || e?.error || '操作失败') }
  finally{ bulkApproving.value = false }
}

// 跨页全选：拉取当前筛选口径下全部审批 ID 填入选择集（供跨页批量操作）
const selectingAll = ref(false)
// 选择集是否含当前页之外的记录（决定批量按钮是否放宽「本页可用」判定）
const isCrossPageSelection = computed(() =>
  [...selectedIds.value].some(id => !items.value.some(i => i.id === id)))
async function selectAllFiltered(){
  if (selectingAll.value) return
  selectingAll.value = true
  try{
    const p = buildParams(); delete p.page; delete p.size
    const res = await api.get('/approvals/select-ids', { params: p, timeout: 60000 })
    const ids = res.data?.ids || []
    selectedIds.value = new Set(ids)
    if (res.data?.capped) toast.warn(`已选前 ${ids.length} 条（达单次上限 ${res.data.cap}）；批量操作请分批或缩小筛选`)
    else toast.success(`已跨页选中全部 ${ids.length} 条筛选结果`)
  } catch(e){ toast.error(e?.msg || e?.error || '全选失败') }
  finally{ selectingAll.value = false }
}

// 批量排款（默认日期=今天，默认金额=各记录剩余可排=申请金额；卡片内可逐条调整金额）
const showBatchSched = ref(false)
const batchSchedForm = reactive({ planned_date: '' })
const batchSchedBusy = ref(false)
const batchSchedRows = ref([])   // [{ id, label, remaining, amount }]
const batchSchedTotal = computed(() =>
  batchSchedRows.value.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0))
const batchSchedValid = computed(() => batchSchedRows.value.length > 0 &&
  batchSchedRows.value.every(r => !schedRowError(r)))
// 行内即时校验：返回该行金额的错误文案（空 = 合法），供逐条红框 + 提示展示
function schedRowError(r) {
  if (r.amount === '' || r.amount == null) return '请填写金额'
  const a = parseFloat(r.amount)
  if (isNaN(a)) return '金额格式有误'
  if (a <= 0) return '金额需大于 0'
  if (a > r.remaining + 1e-6) return `超过剩余可排 ${r.remaining.toFixed(2)}`
  return ''
}
const batchSchedErrCount = computed(() =>
  batchSchedRows.value.filter(r => schedRowError(r)).length)
function openBatchSchedule(){
  batchSchedForm.planned_date = todayCST()
  if (isCrossPageSelection.value) {
    // 跨页模式：不展示逐条金额，后端各取剩余可排
    batchSchedRows.value = []
  } else {
    if (!batchSchedSummary.value.count){ toast.warn('所选记录中没有「审批通过且未归档」的可排款记录'); return }
    batchSchedRows.value = selectedSchedulable.value.map(i => {
      const rem = remOf(i)
      return { id: i.id, label: [i.payee, i.summary || i.applicant].filter(Boolean).join(' · ') || `#${i.id}`,
               remaining: rem, amount: rem }
    })
  }
  showBatchSched.value = true
}
function batchSchedResetAll(){ batchSchedRows.value.forEach(r => { r.amount = r.remaining }) }
async function doBatchSchedule(){
  if (batchSchedBusy.value) return
  if (!isCrossPageSelection.value && !batchSchedValid.value) return
  batchSchedBusy.value = true
  try{
    let body
    if (isCrossPageSelection.value) {
      body = { ids: [...selectedIds.value], planned_date: batchSchedForm.planned_date }
    } else {
      const items = batchSchedRows.value.map(r => ({ id: r.id, amount: r.amount }))
      body = { items, planned_date: batchSchedForm.planned_date }
    }
    const r = await api.post('/approvals/bulk-schedule', body)
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
const listLane = createRequestLane()   // 列表请求竞态车道：新请求自动取消旧请求
async function load(){
  loading.value=true; loadErr.value=''
  const sig = listLane.signal()
  try{
    const r=await api.get('/approvals',{params:buildParams(), signal: sig})
    items.value=r.data.items; total.value=r.data.total
    totalAmount.value=r.data.total_amount || 0; totalScheduled.value=r.data.total_scheduled || 0
    totalRemaining.value=r.data.total_remaining || 0
    loading.value=false
  }catch(e){
    // 被新请求取消：保持 loading，交由接管的新请求收尾，避免闪烁/旧数据覆盖
    if (e?.__canceled || sig.aborted) return
    loadErr.value = e?.error || e?.msg || e?.message || '加载失败，请刷新重试'
    loading.value=false
  }
}
function search(){ page.value=1; clearSelection(); load() }
function setPage(p){ page.value=p; load() }
async function loadDepts(){ try{const r=await cachedGet('/departments'); depts.value=r.data}catch{}}
function openCreate(){ editId.value=null; Object.assign(form,{ applicant:'', department:deptChoices.value[0]||'', secondary_dept:'', project_short_name:'', approval_number:'', g7_number:'', summary:'', notes:'', amount:'', payee:'', status:'pending' }); showCreate.value=true }
// 编辑：复用新增弹窗，回填后改走 PUT。已归档（已排款/已拒绝/已撤销）记录为终态不可编辑，
// 仅金额、状态等受后端口径约束（金额仅「待审批」可改、审批/拒绝须审批权限），后端会兜底校验
function openEdit(it){ editId.value=it.id; Object.assign(form,{ applicant:it.applicant||'', department:it.department||'', secondary_dept:it.secondary_dept||'', project_short_name:it.project_short_name||'', approval_number:it.approval_number||'', g7_number:it.g7_number||'', summary:it.summary||'', notes:it.notes||'', amount:it.amount||'', payee:it.payee||'', status:it.status||'pending' }); showCreate.value=true }
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
  { key: 'notes', label: '备注' },
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
    { key: 'del', label: '删除审批记录', icon: 'trash', danger: true, hidden: !auth.canDelete, action: r => deleteOne(r) },
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
// 预算预警
const schedBudget = ref(null) // null | { has_budget, budget, scheduled, remaining, remaining_after, over, over_by }
function fetchBudgetCheck() {
  if (!current.value) return
  const dept = current.value.department
  const date = scheduleForm.planned_date
  const amount = scheduleForm.total_amount
  if (!dept || !date || !amount) { schedBudget.value = null; return }
  const month = date.slice(0, 7) // yyyy-mm
  api.get('/approvals/budget-check', { params: { dept, month, amount } })
    .then(r => { schedBudget.value = r.data })
    .catch(() => { schedBudget.value = null })
}
function openSchedule(it){
  current.value=it
  // 分批排款：默认带出剩余可排（首次=申请金额），可改小分批流转
  const remaining = parseFloat(it.remaining_amount ?? it.amount) || 0
  Object.assign(scheduleForm,{ planned_date: todayCST(), total_amount: remaining })
  schedPrepaid.value = null
  schedBudget.value = null
  showSchedule.value=true
  if (it.project_short_name) {
    api.get('/payments/prepaid-balance', { params: { short_name: it.project_short_name } })
      .then(r => { if (r.data?.matched && r.data.count > 0) schedPrepaid.value = r.data })
      .catch(() => {})
  }
  fetchBudgetCheck()
}
watch(() => scheduleForm.planned_date, fetchBudgetCheck)
watch(() => scheduleForm.total_amount, fetchBudgetCheck)
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

// 运输事业部对账单导入：先预检（逐类详列将导入/各类跳过/列漂移）→ 用户确认 → 落库
const transportPrecheck = ref(null)   // 预检报告（非空时弹出预检弹窗）
const transportFile = ref(null)       // 暂存待导入文件，确认后提交
function triggerTransportImport(){ importResult.value=null; precheckResult.value=null; transportPrecheck.value=null; transportFileRef.value.click() }
async function onTransportImport(e){
  const f=e.target.files?.[0]; if(!f){ return }
  e.target.value=''
  importingTransport.value=true; importResult.value=null; precheckResult.value=null
  try{
    const fd=new FormData(); fd.append('file',f)
    const d=(await api.post('/approvals/transport/import/precheck',fd,{
      headers:{'Content-Type':'multipart/form-data'}, timeout:120000,
    })).data||{}
    transportFile.value=f
    transportPrecheck.value=d
  }catch(err){ importResult.value={ error: err?.msg || err?.error || '运输对账单预检失败，请确认上传的是运输系统导出的原始表' } }
  finally{ importingTransport.value=false }
}
function cancelTransportPrecheck(){ transportPrecheck.value=null; transportFile.value=null }
async function confirmTransportImport(){
  if(!transportFile.value) return
  importingTransport.value=true
  try{
    const fd=new FormData(); fd.append('file',transportFile.value)
    const d=(await api.post('/approvals/transport/import',fd,{
      headers:{'Content-Type':'multipart/form-data'}, timeout:120000,
    })).data||{}
    transportPrecheck.value=null; transportFile.value=null
    importResult.value={ created:d.created||0, skipped:d.skipped||0, errors:d.errors||[], message:d.message }
    if(d.created>0) load()
  }catch(err){
    transportPrecheck.value=null; transportFile.value=null
    importResult.value={ error: err?.msg || err?.error || '运输对账单导入失败，请重试' }
  }
  finally{ importingTransport.value=false }
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
async function doExport(){
  exporting.value=true
  try{
    const b=await api.get('/approvals/export',{params:buildParams(),responseType:'blob'})
    dl(b,'审批管理.xlsx')
  } catch(e){
    // 同步导出超出上限（>5000 行）→ 自动转后台异步导出
    const msg = e?.msg || e?.error || ''
    if (/导出超过|后台导出|超出导出上限/.test(msg)) {
      startExport('approvals', buildParams())
    } else {
      toast.error(msg || '导出失败')
    }
  } finally{ exporting.value=false }
}
// 显式后台导出（无视同步上限，直接走异步任务）
function doBgExport(){ startExport('approvals', buildParams()) }

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
  // 有默认方案则套用并由其触发加载；否则套用「默认只看待审批 + 审批通过」状态筛选后加载。
  // （已拒绝/已撤销仍在库可查，清除状态筛选即可查看全部）
  const applied = await schemes.loadAndApplyDefault()
  if (!applied) {
    colFilters.status = { op: 'in', value: ['pending', 'approved'] }
    load()
  }
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(()=>window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template><div>
  <div class="topbar"><h1>审批管理</h1><div class="topbar-tools">
    <input v-model="q" class="global-search" placeholder="🔍 申请人 / 编号 / 项目 / 摘要 / 收款方…" @keyup.enter="search"/>
    <button class="btn btn-ghost btn-sm" @click="search">搜索</button>
    <div class="numfilter-wrap">
      <button class="btn btn-ghost btn-sm" :class="{ on: !!numbersFilter }" @click="showNumbersBox = !showNumbersBox"
              title="粘贴多个单号（空格/换行/+/逗号等任意分隔）批量筛选">
        🔖 批量单号{{ numbersFilter ? `（${numbersFilter.split(',').length}）` : '' }}
      </button>
      <div v-if="showNumbersBox" class="numfilter-pop">
        <div class="nf-title">粘贴单号批量筛选 <span>G7/对账单号/审批编号，任意分隔符</span></div>
        <textarea v-model="numbersText" class="nf-area" rows="6"
                  placeholder="例如：&#10;ZD202606260055 ZD202606260133&#10;单号+单号，逗号、空格、换行都行"></textarea>
        <div class="nf-foot">
          <span class="nf-count">识别 {{ parsedNumbers.length }} 个</span>
          <div style="display:flex;gap:6px">
            <button class="btn btn-sm" @click="clearNumbers">清除</button>
            <button class="btn btn-sm btn-primary" :disabled="!parsedNumbers.length" @click="applyNumbers">应用筛选</button>
          </div>
        </div>
      </div>
    </div>
    <button v-if="activeFilterCount || q || sortField || numbersFilter" class="btn btn-ghost btn-sm clear-all" @click="clearAllFilters" title="清除全部列筛选 / 搜索 / 排序 / 单号">清除筛选<span v-if="activeFilterCount">（{{ activeFilterCount }}）</span></button>
    <SchemePicker :ctl="schemes" :can-public="auth.canCreate" :is-super-admin="auth.isSuperAdmin" />
    <span class="tb-sep"></span>
    <button class="btn btn-ghost btn-sm" @click="downloadTemplate">模板</button>
    <button class="btn btn-ghost btn-sm" :disabled="importing" @click="triggerImport"
            title="导入会自动做规则校验 + AI 智能复核；发现问题时 AI 会介入，协助你就地修正后再导入">{{ importing?'导入中…':'导入' }}</button>
    <button class="btn btn-ghost btn-sm" @click="doExport" :disabled="exporting || bgExporting"
            title="导出当前筛选结果；超过 5000 行自动转后台导出，完成后自动下载">{{ exporting?'导出中…':(bgExporting?'后台导出中…':'导出') }}</button>
    <button v-if="canTransport" class="btn btn-ghost btn-sm tp-btn" :disabled="importingTransport" @click="triggerTransportImport"
            title="运输事业部专用：上传运输系统导出的对账单原始表 → 金额自动取绝对值、对账单号去重，建为「已通过」审批记录，再排款进付款管理">
      <span style="margin-right:3px">🚚</span>{{ importingTransport?'导入中…':'运输导入' }}</button>
    <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增</button>
  </div></div>
  <input ref="fileRef" type="file" accept=".xlsx,.xls,.csv" style="display:none" @change="onImport" />
  <input ref="transportFileRef" type="file" accept=".xlsx,.xls,.csv" style="display:none" @change="onTransportImport" />
  <div class="card approval-card fh-fill">
  <div v-if="loadErr" class="err-banner">⚠️ {{ loadErr }} <button class="btn-link" @click="load()">重试</button></div>
  <EmptyState v-else-if="!loading && !items.length" :variant="activeFilterCount || q ? 'search' : 'empty'" :text="activeFilterCount || q ? '没有符合当前筛选条件的审批记录' : '暂无审批记录，点击「新增」创建第一条记录'" />
  <div v-if="!loadErr" class="table-wrap page-scroll" :ref="rangeSel.setRoot"><table class="approval-table">
    <colgroup>
      <col class="cg-sel" /><!-- 选择 -->
      <col style="width:6%" /><!-- 申请人 -->
      <col style="width:7%" /><!-- 所属事业部 -->
      <col style="width:7%" /><!-- 二级部门 -->
      <col style="width:8%" /><!-- 项目简称 -->
      <col style="width:9%" /><!-- 审批编号 -->
      <col style="width:9%" /><!-- G7编号 -->
      <col style="width:12%" /><!-- 摘要 -->
      <col class="cg-status" /><!-- 审批状态（缩小） -->
      <col style="width:7%" /><!-- 申请金额 -->
      <col style="width:7%" /><!-- 已排金额 -->
      <col style="width:7%" /><!-- 未排金额 -->
      <col style="width:10%" /><!-- 收款主体 -->
      <col style="width:11%" /><!-- 备注（末列） -->
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
      <th class="status-h"><ColumnFilter label="审批状态" field="status" type="enum" :options="STATUS_OPTS" :model-value="colFilters.status" :sortable="false" @update:model-value="v=>setColFilter('status',v)" /></th>
      <th class="amt-h"><ColumnFilter label="申请金额" field="amount" type="number" :model-value="colFilters.amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('amount',v)" @sort="o=>setSort('amount',o)" /></th>
      <th class="amt-h"><ColumnFilter label="已排金额" field="scheduled_amount" type="number" :model-value="colFilters.scheduled_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('scheduled_amount',v)" @sort="o=>setSort('scheduled_amount',o)" /></th>
      <th class="amt-h"><ColumnFilter label="未排金额" field="remaining_amount" type="number" :model-value="colFilters.remaining_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('remaining_amount',v)" @sort="o=>setSort('remaining_amount',o)" /></th>
      <th><ColumnFilter label="收款主体" field="payee" type="text" :model-value="colFilters.payee" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('payee',v)" @sort="o=>setSort('payee',o)" /></th>
      <th><ColumnFilter label="备注" field="notes" type="text" :model-value="colFilters.notes" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('notes',v)" @sort="o=>setSort('notes',o)" /></th>
      </tr></thead>
    <tbody>
      <template v-if="loading">
        <SkeletonRow v-for="n in 8" :key="n" :cols="14" />
      </template>
      <template v-else>
      <template v-for="i in items" :key="i.id">
      <tr :class="{ 'row-sel': selectedIds.has(i.id) }" @contextmenu.prevent="ctx.open($event, i)" @dblclick="onRowDblClick(i, $event)">
      <td class="sel-col"><input type="checkbox" :checked="selectedIds.has(i.id)" @change="toggleRow(i.id)" /></td>
      <td :title="i.applicant">{{i.applicant}}</td><td :title="i.department">{{i.department}}</td>
      <td class="meta-cell" :title="i.secondary_dept">{{ i.secondary_dept || '—' }}</td>
      <td class="meta-cell" :title="i.project_short_name">{{ i.project_short_name || '—' }}</td>
      <td class="mono" :title="i.approval_number">{{i.approval_number || '—'}}</td><td class="mono g7-cell" :title="i.g7_number">{{i.g7_number || '—'}}</td><td class="summary" :title="i.summary">{{i.summary}}</td>
      <td :class="['status-cell', 'st-' + i.status]" :title="i.status === 'approved' ? '审批通过，可排款' : (i.status === 'pending' ? '待审批，通过后方可排款' : '')">
        <div class="status-wrap">
          <span class="status-badge">{{ {pending:'待审批',approved:'审批通过',rejected:'已拒绝',canceled:'已撤销'}[i.status] || i.status }}</span>
          <select class="status-overlay" :value="i.status" :disabled="statusUpdating[i.id]" @change="updateStatus(i, $event.target.value)" title="点击更改审批状态">
            <option value="pending">待审批</option><option value="approved">审批通过</option><option value="rejected">已拒绝</option><option value="canceled">已撤销</option>
          </select>
        </div>
      </td>
      <td class="amt" :title="i.amount">{{i.amount}}</td>
      <td class="amt sched-c plan-cell" :title="parseFloat(i.scheduled_amount) > 0 ? '点击展开排款批次明细（排款管理）' : ''"
          @click="parseFloat(i.scheduled_amount) > 0 && toggleAprSchedDetail(i)">
        <template v-if="parseFloat(i.scheduled_amount) > 0">
          {{ i.scheduled_amount }}
          <span class="plan-caret">{{ isAprSchedExpanded(i.id) ? '▲' : '▼' }}</span>
        </template>
        <span v-else>—</span>
      </td>
      <td class="amt remain-c" :class="{ 'remain-zero': parseFloat(i.remaining_amount) <= 0 }">{{ parseFloat(i.remaining_amount) > 0 ? i.remaining_amount : '—' }}</td>
      <td class="payee" :title="i.payee">{{i.payee}}</td>
      <td class="notes-cell" :title="i.notes">{{ i.notes || '—' }}</td>
      </tr>
      <!-- 排款批次明细面板 -->
      <tr v-if="isAprSchedExpanded(i.id)" class="apr-plan-detail-row" data-skiprange>
        <td colspan="14">
          <div class="apr-plan-detail">
            <div v-if="aprSchedCache[i.id]?.loading" class="apd-loading">加载中…</div>
            <div v-else-if="aprSchedCache[i.id]?.error" class="apd-error">{{ aprSchedCache[i.id].error }}</div>
            <template v-else-if="aprSchedCache[i.id]?.data">
              <div class="apd-head">
                排款批次明细（付款管理 #{{ aprSchedCache[i.id].data.payment_id }} · 计划合计 ¥{{ aprSchedCache[i.id].data.total_amount }} · 已付 ¥{{ aprSchedCache[i.id].data.total_paid }}）
                <i>编辑/撤回均与审批已排款双向同步；审批记录状态不受影响</i>
                <button v-if="auth.canCreate" class="apd-return-all"
                  title="退回全部排款（删除付款管理记录，审批已排款归零，可重新排款）"
                  @click="returnFullSchedule(i)">退回全部排款</button>
              </div>
              <div v-for="pi in aprSchedCache[i.id].data.plan_items" :key="pi.id" class="apd-item">
                <!-- 编辑态 -->
                <template v-if="aprPlanEdit.id === pi.id && aprPlanEdit.approval_id === i.id">
                  <span class="apd-seq">第{{ pi.seq }}批</span>
                  <input v-model="aprPlanEdit.planned_date" type="date" class="apd-edit-date" />
                  <input v-model="aprPlanEdit.amount" type="number" step="0.01" class="apd-edit-amt" placeholder="金额" />
                  <input v-model="aprPlanEdit.notes" type="text" class="apd-edit-note" placeholder="备注" />
                  <button class="apd-save" :disabled="aprPlanEdit.busy" @click="saveAprPlanEdit(i.id)">保存</button>
                  <button class="apd-cancel" :disabled="aprPlanEdit.busy" @click="cancelAprPlanEdit">取消</button>
                </template>
                <!-- 展示态 -->
                <template v-else>
                  <span class="apd-seq">第{{ pi.seq }}批</span>
                  <span class="apd-date">{{ pi.planned_date }}</span>
                  <b class="apd-amt">¥{{ pi.amount }}</b>
                  <span class="apd-note">{{ pi.notes }}</span>
                  <template v-if="auth.canCreate && !aprPlanEdit.id">
                    <button class="apd-edit" title="编辑该批次日期/金额/备注" @click="startAprPlanEdit(i.id, pi)">编辑</button>
                    <button v-if="aprSchedCache[i.id].data.plan_items.length > 1" class="apd-del"
                      title="撤回该批次（审批已排款同步扣减，可继续排）"
                      @click="removeAprPlanItem(i.id, pi)">撤回</button>
                  </template>
                </template>
              </div>
              <div v-if="!aprSchedCache[i.id].data.plan_items.length" class="apd-empty">暂无计划批次</div>
            </template>
          </div>
        </td>
      </tr>
      </template>
      </template>
    </tbody>
  </table></div>

  <!-- 浮动批量操作条：Teleport 到 body 固定在视口底部，全选后无需下拉即可操作 -->
  <Teleport to="body">
    <div v-if="!loading && items.length && hasSelection && !showBatchSched && !showDelConfirm && (auth.canDelete || auth.canCreate)" class="bulk-bar">
      <span class="bulk-n">已选 <strong>{{ selectedCount }}</strong> 条</span>
      <button v-if="selectedCount < total" class="bulk-selall" :disabled="selectingAll" @click="selectAllFiltered"
              :title="`跨页选中当前筛选下全部 ${total} 条（上限 1000，供批量操作）`">{{ selectingAll ? '全选中…' : `选择全部 ${total} 条` }}</button>
      <button v-if="auth.canCreate" class="bulk-approve" :disabled="bulkApproving || (!isCrossPageSelection && !selectedApprovable.length)" @click="bulkApprove">{{ bulkApproving ? '审批中…' : (isCrossPageSelection ? '批量通过' : `批量通过（待审 ${selectedApprovable.length} 条）`) }}</button>
      <button v-if="auth.canCreate" class="bulk-act" :disabled="!isCrossPageSelection && !batchSchedSummary.count" @click="openBatchSchedule">{{ isCrossPageSelection ? `批量排款（${selectedCount} 条）` : `批量排款（可排 ${batchSchedSummary.count} 条）` }}</button>
      <button v-if="auth.canCreate && (isCrossPageSelection || selectedWithSchedule.length)" class="bulk-return" :disabled="bulkReturning" @click="bulkReturnSchedule">{{ bulkReturning ? '退回中…' : (isCrossPageSelection ? '批量退回排款' : `批量退回排款（${selectedWithSchedule.length} 条）`) }}</button>
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
        <span class="bb-hint" title="按住鼠标拖选单元格区域，Ctrl/⌘+C 复制，可粘贴进 Excel">💡 拖选 + Ctrl C 复制区域</span>
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
    <label class="form-field"><span>备注</span><input v-model="form.notes" placeholder="选填"/></label>
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
  </div>
  <div v-if="schedBudget?.has_budget" class="sched-budget-bar" :class="{ 'over-budget': schedBudget.over }">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">
      <path v-if="schedBudget.over" d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line v-if="schedBudget.over" x1="12" y1="9" x2="12" y2="13"/><line v-if="schedBudget.over" x1="12" y1="17" x2="12.01" y2="17"/>
      <circle v-if="!schedBudget.over" cx="12" cy="12" r="10"/><path v-if="!schedBudget.over" d="M12 16v-4M12 8h.01"/>
    </svg>
    <div style="flex:1;min-width:0">
      <div v-if="schedBudget.over" style="font-weight:700">
        ⚠ 超预算预警：本次排款将超出 {{ current?.department }} {{ scheduleForm.planned_date?.slice(0,7) }} 预算 <b>¥{{ schedBudget.over_by }}</b>
      </div>
      <div v-else>
        本月预算尚余 <b>¥{{ schedBudget.remaining }}</b>，排款后余 <b>¥{{ schedBudget.remaining_after }}</b>
      </div>
      <div style="font-size:11px;opacity:0.7;margin-top:2px">
        预算 ¥{{ schedBudget.budget }} · 已排 ¥{{ schedBudget.scheduled }} · 本次 ¥{{ schedBudget.proposed }}
      </div>
    </div>
  </div>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showSchedule=false">取消</button><button class="btn btn-primary" :disabled="schedBusy" @click="doSchedule">{{ schedBusy ? '排款中…' : '保存并排款' }}</button></div></div></div></Teleport>

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
    <template v-if="isCrossPageSelection">
      <div class="sched-progress">
        <span>已选记录 <b>{{ selectedCount }}</b> 条（非「审批通过且未归档」的自动跳过）</span>
      </div>
      <p style="font-size:12px;color:var(--muted);margin:0 0 10px">
        跨页批量排款：各记录按各自「剩余可排金额（首次 = 申请金额）」排款，非「审批通过」或已归档记录自动跳过。
      </p>
    </template>
    <template v-else>
      <div class="sched-progress">
        <span>可排记录 <b>{{ batchSchedRows.length }}</b> 条</span>
        <span>合计金额 <b style="color:#2e7d32">{{ batchSchedTotal.toFixed(2) }}</b> 元</span>
      </div>
      <p style="font-size:12px;color:var(--muted);margin:0 0 10px">
        默认按各记录「剩余可排（首次=申请金额）」各排一笔流转付款管理，可逐条调小做分批排款（不得超过剩余可排）；所选中非「审批通过/已归档」的记录已自动排除。
      </p>
    </template>
    <div class="form-grid" style="margin-bottom:10px">
      <label class="form-field"><span>计划日期*</span><input v-model="batchSchedForm.planned_date" type="date"/></label>
    </div>
    <template v-if="!isCrossPageSelection">
      <div class="batch-rows-head">
        <span>本次排款金额（共 {{ batchSchedRows.length }} 条）</span>
        <button type="button" class="batch-reset" @click="batchSchedResetAll">全部设为剩余可排</button>
      </div>
      <div v-if="batchSchedErrCount" class="batch-err-banner">
        ⚠ {{ batchSchedErrCount }} 行金额有误，请修正后再提交
      </div>
      <div class="batch-rows">
        <div v-for="r in batchSchedRows" :key="r.id" class="batch-row" :class="{ 'row-bad': schedRowError(r) }">
          <span class="batch-row-label" :title="r.label">{{ r.label }}</span>
          <span class="batch-row-rem">剩余 {{ r.remaining.toFixed(2) }}</span>
          <div class="batch-amt-wrap">
            <input v-model="r.amount" type="number" step="0.01" min="0" :max="r.remaining"
                   class="batch-row-amt" :class="{ bad: !!schedRowError(r) }"/>
            <span v-if="schedRowError(r)" class="batch-row-err">{{ schedRowError(r) }}</span>
          </div>
        </div>
      </div>
    </template>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showBatchSched=false">取消</button><button class="btn btn-primary" :disabled="batchSchedBusy || (!isCrossPageSelection && !batchSchedValid)" @click="doBatchSchedule">{{ batchSchedBusy ? '排款中…' : (isCrossPageSelection ? `确认排款 ${selectedCount} 条` : `确认排款 ${batchSchedRows.length} 条`) }}</button></div></div></div></Teleport>

  <!-- 批量删除二次确认 -->
  <Teleport to="body"><div v-if="showDelConfirm" class="modal-overlay"><div class="modal-box" style="max-width:420px"><div class="modal-header"><h3>确认删除 {{ delConfirmCount }} 条审批记录</h3></div><div class="modal-body">
    <p class="del-warn">⚠ 删除后不可恢复；已排款（已关联付款管理）的记录将自动跳过。</p>
    <p class="del-tip">请输入待删条数 <strong>{{ delConfirmCount }}</strong> 以确认：</p>
    <input v-model="delConfirmText" class="del-input" :placeholder="`输入 ${delConfirmCount}`" @keyup.enter="confirmBulkDelete"/>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showDelConfirm=false">取消</button><button class="btn-danger-solid" :disabled="!delConfirmOk || bulkDeleting" @click="confirmBulkDelete">{{ bulkDeleting ? '删除中…' : '确认删除' }}</button></div></div></div></Teleport>

  <ImportResultModal :result="importResult" @close="importResult = null" />
  <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy"
    @close="precheckResult = null" @apply="onPrecheckApply" />
  <TransportPrecheckModal :report="transportPrecheck" :busy="importingTransport"
    @confirm="confirmTransportImport" @cancel="cancelTransportPrecheck" />

  <!-- 右键上下文菜单 -->
  <ContextMenu :ctx="ctx" :items="ctxItems" />
</div></template>

<style scoped>
/* 运输事业部专用导入按钮：强调色与普通导入区分 */
.tp-btn { border-color: rgba(201,99,66,0.4); color: var(--primary); }
.tp-btn:hover:not(:disabled) { background: rgba(201,99,66,0.08); border-color: var(--primary); }
.err-banner { background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; color: #856404; display: flex; align-items: center; gap: 8px; }
.approval-card { padding: 12px; }
/* 固定视口布局：卡片底部为吸底合计条预留空间 */
/* 吸底 bottom-bar(36px) 占位：滚动区底部留白，最后一行不被遮挡 */
.table-wrap.page-scroll { padding-bottom: 40px; }
/* 搜索 + 方案 + 导入导出 收纳进页头右侧，腾出整行垂直空间给表格 */
.topbar-tools { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.topbar-tools .global-search { min-width: 180px; flex: 0 1 240px; height: 30px; }
.tb-sep { width: 1px; align-self: stretch; min-height: 20px; background: var(--border); margin: 0 2px; }
.clear-all { color: var(--primary); }
/* 批量单号筛选弹层 */
.numfilter-wrap { position: relative; }
.numfilter-wrap .on { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.07); }
.numfilter-pop { position: absolute; top: calc(100% + 6px); right: 0; z-index: 60; width: 320px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-lg); padding: 12px; text-align: left; }
.nf-title { font-size: 12.5px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.nf-title span { font-weight: 400; color: var(--muted); font-size: 11px; }
.nf-area { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 8px; padding: 8px;
  font-size: 12.5px; font-family: ui-monospace, Menlo, monospace; resize: vertical; }
.nf-area:focus { outline: none; border-color: var(--primary); }
.nf-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; }
.nf-count { font-size: 12px; color: var(--muted); }
/* 列头：字段名完整展示，空间不足时换行成两行（不挤压、不截断），漏斗不裁切 */
.approval-table thead th {
  overflow: visible; white-space: normal; vertical-align: middle;
  line-height: 1.25; height: auto; padding-top: 5px; padding-bottom: 5px;
  font-size: 12px; letter-spacing: -0.2px;
}
.approval-table thead :deep(.colf) { align-items: center; }
/* 换行时两行字数尽量均衡（text-wrap:balance），避免 4+1 这种头重脚轻 */
.approval-table thead :deep(.colf-label) { white-space: normal; text-wrap: balance; }
/* 表头随表体滚动吸顶（不透明背景，避免行透出） */
.table-wrap.page-scroll thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }

/* .bottom-bar, .bb-*, .page-btn, .page-info → global styles in style.css */
.bb-hint { font-size: 11px; color: var(--muted); margin-left: 8px; opacity: 0.8; white-space: nowrap; cursor: help; }
@media (max-width: 900px) { .bb-hint { display: none; } }
/* width:100% 充满；min-width 保证窄屏下横向滚动而非把列名/数据挤扁 */
.approval-table { width: 100%; min-width: 1120px; table-layout: fixed; }
/* 列宽由 <colgroup> 统一声明；选择列固定窄宽、审批状态列缩小，其余按百分比分配 */
.approval-table col.cg-sel { width: 34px; }
/* 审批状态列：宽度够放下「审批通过」整词 + 下拉箭头，不再截断成「审批」 */
.approval-table col.cg-status { width: 88px; }
/* 行高/内边距对齐全局表格（付款管理），保证两个页面观感一致 */
/* 紧凑排版：数据量大，行间距固定收紧（固定行高 + 单行省略，超出鼠标悬停 title 展示） */
.approval-table th, .approval-table td { padding: var(--td-py) var(--td-px); height: var(--td-h); box-sizing: border-box; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: var(--td-fs); line-height: 1.4; }
.approval-table th.sel-col, .approval-table td.sel-col { text-align: center; overflow: visible; padding: 4px 4px; }
.approval-table th.sel-col input, .approval-table td.sel-col input { cursor: pointer; }
/* 审批状态色码徽章：badge 显示颜色，transparent overlay select 捕获交互 */
.status-wrap { position: relative; display: inline-block; width: 100%; }
.status-badge {
  display: block; border-radius: 999px; padding: 2px 8px;
  font-size: 11.5px; font-weight: 700; border: 1px solid transparent;
  text-align: center; white-space: nowrap; pointer-events: none;
}
.status-overlay {
  position: absolute; inset: 0; opacity: 0; cursor: pointer;
  width: 100%; height: 100%; border: none; background: none;
}
.status-overlay:disabled { cursor: default; }
.status-cell.st-pending  .status-badge { color: #8a6d1a; background: rgba(255,213,79,0.25); border-color: rgba(255,193,7,0.6); }
.status-cell.st-approved .status-badge { color: #1b5e20; background: rgba(46,125,50,0.18); border-color: rgba(46,125,50,0.6); }
.status-cell.st-rejected .status-badge { color: #b71c1c; background: rgba(198,40,40,0.14); border-color: rgba(198,40,40,0.55); }
.status-cell.st-canceled .status-badge { color: #5f5f5f; background: rgba(120,120,120,0.15); border-color: rgba(120,120,120,0.5); }
.g7-cell { color: var(--muted); font-size: 11.5px; }
/* 行悬停高亮：宽表跨 14 列时帮助视线锁定整行（明细行/选中行不参与/不被覆盖） */
.approval-table tbody tr:not(.apr-plan-detail-row):hover td { background: rgba(201,99,66,0.045); }
.approval-table tr.row-sel td,
.approval-table tbody tr.row-sel:hover td { background: rgba(201,99,66,0.09); }
/* Excel 式区域选择高亮（直接由 useRangeSelection 给 td 加类，不逐格绑定） */
.approval-table td.cell-range-sel { background: rgba(21,101,192,0.14) !important; box-shadow: inset 0 0 0 1px rgba(21,101,192,0.28); }
/* 拖拽选区时禁用原生文本选择（电子表格式交互）；行内 input 仍可正常编辑 */
.approval-table tbody { user-select: none; }
/* 批量操作条：固定浮动在视口底部居中，全选后无需下拉即可操作 */
.bulk-bar { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); z-index: 1200;
  display: flex; align-items: center; gap: 12px; padding: 10px 18px;
  border-radius: 12px; background: var(--card); border: 1px solid rgba(198,40,40,0.35);
  box-shadow: 0 8px 28px rgba(0,0,0,0.18); }
.bulk-n { font-size: 13px; color: var(--text); }
.bulk-selall { border: 1px solid var(--primary); background: rgba(201,99,66,0.08); color: var(--primary); border-radius: 8px; padding: 5px 12px; font-size: 12.5px; font-weight: 700; cursor: pointer; }
.bulk-selall:disabled { opacity: .5; cursor: default; }
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
.sched-budget-bar {
  display: flex; align-items: flex-start; gap: 8px; padding: 9px 12px; border-radius: 9px;
  font-size: 12.5px; line-height: 1.6; margin-top: 10px;
  background: var(--c-info-bg); border: 1px solid var(--c-info-bdr); color: var(--c-info);
}
.sched-budget-bar.over-budget {
  background: rgba(230,81,0,0.10); border-color: rgba(230,81,0,0.32); color: var(--c-warn);
}
.sched-budget-bar.over-budget b { color: var(--c-danger); }
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
.batch-row.row-bad { background: rgba(198,40,40,0.035); }
.batch-amt-wrap { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
.batch-row-err { font-size: 10.5px; color: var(--danger); white-space: nowrap; line-height: 1.2; }
.batch-err-banner { font-size: 12px; color: var(--danger); background: rgba(198,40,40,0.07);
  border: 1px solid rgba(198,40,40,0.22); border-radius: 7px; padding: 6px 10px; margin-bottom: 8px; }
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
.notes-cell { color: var(--muted); font-size: 12px; }
.approval-table select { width: 100%; min-width: 0; max-width: 100%; height: 26px; font-size: 12px; padding: 0 20px 0 6px; background-position: right 6px center; }
.pg-jump { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); margin-left: 8px; }
.pg-jump-input { width: 46px; text-align: center; padding: 2px 4px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
/* 已排金额列：可点击展开排款明细 */
.approval-table td.plan-cell { cursor: pointer; user-select: none; }
.plan-caret { font-size: 9px; color: var(--muted); margin-left: 3px; }
/* 批量退回按钮 */
.bulk-return { border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: #e65100; color: #fff; }
.bulk-return:disabled { opacity: .5; cursor: default; }
/* 排款批次明细展开行 */
.apr-plan-detail-row td { padding: 0; }
.apr-plan-detail { background: #faf8f6; border-top: 1px solid var(--border); padding: 10px 16px 12px; }
.apd-head { font-size: 12px; color: var(--muted); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.apd-head i { font-style: normal; color: #1565c0; font-size: 11px; }
.apd-loading, .apd-error, .apd-empty { font-size: 12.5px; color: var(--muted); padding: 6px 0; }
.apd-error { color: var(--danger); }
.apd-item { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid rgba(0,0,0,0.05); }
.apd-item:last-child { border-bottom: none; }
.apd-seq { font-size: 11.5px; color: var(--muted); min-width: 40px; }
.apd-date { font-size: 13px; min-width: 90px; font-variant-numeric: tabular-nums; }
.apd-amt { font-size: 13px; min-width: 90px; color: #2e7d32; font-variant-numeric: tabular-nums; }
.apd-note { font-size: 12px; color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.apd-edit, .apd-del { border: 1px solid var(--border); background: var(--card); border-radius: 6px; padding: 3px 9px; font-size: 12px; cursor: pointer; }
.apd-edit:hover { border-color: var(--primary); color: var(--primary); }
.apd-del { color: var(--danger); }
.apd-del:hover { border-color: var(--danger); background: rgba(198,40,40,0.06); }
.apd-edit-date { width: 120px; height: 28px; padding: 0 6px; border: 1.5px solid var(--border); border-radius: 6px; font-size: 12.5px; }
.apd-edit-amt { width: 100px; height: 28px; padding: 0 6px; border: 1.5px solid var(--border); border-radius: 6px; font-size: 12.5px; text-align: right; }
.apd-edit-note { flex: 1; height: 28px; padding: 0 6px; border: 1.5px solid var(--border); border-radius: 6px; font-size: 12.5px; min-width: 80px; }
.apd-save { border: none; background: var(--primary); color: #fff; border-radius: 6px; padding: 3px 12px; font-size: 12px; cursor: pointer; }
.apd-save:disabled { opacity: .5; cursor: default; }
.apd-cancel { border: 1px solid var(--border); background: none; border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; color: var(--muted); }
.apd-return-all { margin-left: auto; border: 1px solid #e65100; background: rgba(230,81,0,0.08); color: #e65100; border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; font-weight: 600; }
.apd-return-all:hover { background: #e65100; color: #fff; }
</style>
