<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { todayCST } from '../constants.js'
import { downloadBlob } from '../utils/download.js'
import EmptyState from '../components/EmptyState.vue'
import ProjectShortNamePicker from '../components/ProjectShortNamePicker.vue'
import ImportResultModal from '../components/ImportResultModal.vue'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const totalAmount = ref(0)
const loading = ref(false)
const depts = ref([])
const fileRef = ref(null)
const importing = ref(false)
const importResult = ref(null)
const exporting = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const showSchedule = ref(false)
const current = ref(null)
const form = reactive({ applicant:'', department:'', secondary_dept:'', project_short_name:'', approval_number:'', summary:'', amount:'', payee:'', status:'pending' })
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
  } catch(e){ alert(e?.msg || e?.error || '保存失败') }
  finally{ metaSaving.value = false }
}
// 从台账选中项目时，自动带出该项目的二级部门（台账未填二级部门则保留手填值）
function onProjPicked(p, target){
  if (p.sub_dept) target.secondary_dept = p.sub_dept
}
const filters = reactive({ applicant:'', approval_number:'', dept:'', page:1, size:50 })
const statusUpdating = ref({})
const pendingAmountTotal = computed(() => parseFloat(totalAmount.value || 0))

// ── 单选/多选：批量删除 + 批量排款 ─────────────────────────────────────────
const selectedIds = ref(new Set())                       // 跨页按 id 记忆选择
const remOf = (it) => parseFloat(it.remaining_amount ?? it.amount) || 0
const pageAllSelected = computed(() => items.value.length > 0 && items.value.every(r => selectedIds.value.has(r.id)))
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedIds.value.size > 0)
function toggleRow(id){ const s = new Set(selectedIds.value); s.has(id) ? s.delete(id) : s.add(id); selectedIds.value = s }
function toggleSelectPage(){ const s = new Set(selectedIds.value); if (pageAllSelected.value) items.value.forEach(r => s.delete(r.id)); else items.value.forEach(r => s.add(r.id)); selectedIds.value = s }
function clearSelection(){ selectedIds.value = new Set() }
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
    if (d.skipped?.length) alert(`${d.message}\n\n未删除明细：\n` + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n'))
  } catch(e){ alert(e?.msg || e?.error || '删除失败') }
  finally{ bulkDeleting.value = false }
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
  if (!batchSchedSummary.value.count){ alert('所选记录中没有「审批通过且未归档」的可排款记录'); return }
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
    if (d.skipped?.length) msg += '\n\n跳过明细：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0,15).join('\n')
    alert(msg)
  } catch(e){ alert(e?.msg || e?.error || '批量排款失败') }
  finally{ batchSchedBusy.value = false }
}

const deptChoices = computed(() => {
  const scope = auth.effectiveDepts
  if (auth.isAdmin && !auth.activeDepts.length) return depts.value
  return depts.value.filter(d => scope.includes(d))
})

async function load(){ loading.value=true; try{ const r=await api.get('/approvals',{params:filters}); items.value=r.data.items; total.value=r.data.total; totalAmount.value=r.data.total_amount || 0 }finally{loading.value=false}}
function search(){ filters.page=1; clearSelection(); load() }
function setPage(p){ filters.page=p; load() }
async function loadDepts(){ try{const r=await api.get('/departments'); depts.value=r.data}catch{}}
function openCreate(){ Object.assign(form,{ applicant:'', department:deptChoices.value[0]||'', secondary_dept:'', project_short_name:'', approval_number:'', summary:'', amount:'', payee:'', status:'pending' }); showCreate.value=true }
async function create(){ saving.value=true; try{ await api.post('/approvals', form); showCreate.value=false; load() } catch(e){ alert(e?.msg||e?.error||'保存失败') } finally{ saving.value=false } }
async function updateStatus(it, status){
  const prev = it.status
  it.status = status
  statusUpdating.value[it.id] = true
  try{
    await api.put(`/approvals/${it.id}`,{ status })
  } catch(e){
    it.status = prev
    alert(e?.error||'更新失败')
  } finally {
    statusUpdating.value[it.id] = false
  }
}
// 排款前联动：该审批关联项目有「预付」未核销余额时提示，排款后可在付款台账行内核销
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
    alert(res.data?.message || '排款成功')
  } catch(e){ alert(e?.error||'排款失败') }
  finally{ schedBusy.value = false }
}
async function downloadTemplate(){ const b=await api.get('/approvals/template',{responseType:'blob'}); dl(b,'审批管理导入模板.xlsx') }
const dl = downloadBlob
function triggerImport(){ fileRef.value.click() }
async function onImport(e){
  const f=e.target.files?.[0]; if(!f) return
  importing.value=true; const fd=new FormData(); fd.append('file',f)
  try{
    const r=await api.post('/approvals/import',fd,{headers:{'Content-Type':'multipart/form-data'}})
    const d=r.data||{}
    // 完整展示全部未通过校验的行（弹窗内可滚动），不再用 alert 截断只显示前 15 条
    importResult.value = {
      created: d.created||0, skipped: d.skipped||0, errors: d.errors||[],
      message: `新增 ${d.created||0} 条，跳过 ${d.skipped||0} 条（含错误）`,
    }
    load()
  }catch(err){ importResult.value = { error: err?.error || '导入失败，请检查文件格式或表头' } }
  finally{ importing.value=false; e.target.value='' }
}
async function doExport(){ exporting.value=true; try{ const b=await api.get('/approvals/export',{params:filters,responseType:'blob'}); dl(b,'审批管理.xlsx') } finally{ exporting.value=false } }

const onScopeChange = () => {
  if (filters.dept && !auth.effectiveDepts.includes(filters.dept)) filters.dept = ''
  filters.page = 1
  load()
}
onMounted(()=>{ load(); loadDepts(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(()=>window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template><div>
  <div class="topbar"><h1>审批管理</h1><div style="display:flex;gap:8px">
    <button class="btn btn-ghost btn-sm" @click="downloadTemplate">模板</button>
    <button class="btn btn-ghost btn-sm" @click="triggerImport">{{ importing?'导入中…':'导入' }}</button>
    <button class="btn btn-ghost btn-sm" @click="doExport">{{ exporting?'导出中…':'导出' }}</button>
    <button v-if="auth.canCreate" class="btn btn-primary" @click="openCreate">+ 新增审批记录</button>
  </div></div>
  <input ref="fileRef" type="file" accept=".xlsx,.xls,.csv" style="display:none" @change="onImport" />
  <div class="card approval-card"><div class="filter-row">
    <div class="filter-bar">
    <input v-model="filters.applicant" placeholder="申请人(模糊)" @keyup.enter="search"/>
    <input v-model="filters.approval_number" placeholder="审批编号(模糊)" @keyup.enter="search"/>
    <select v-model="filters.dept" @change="search"><option value="">全部事业部</option><option v-for="d in deptChoices" :key="d" :value="d">{{d}}</option></select>
    <button class="btn btn-ghost btn-sm" @click="search">筛选</button>
    </div>
  </div>
  <EmptyState v-if="loading" loading />
  <EmptyState v-else-if="!items.length" empty text="暂无审批记录" />
  <table v-else class="approval-table"><thead><tr>
      <th class="sel-col"><input type="checkbox" :checked="pageAllSelected" :indeterminate.prop="hasSelection && !pageAllSelected" title="全选本页" @change="toggleSelectPage" /></th>
      <th>申请人</th><th>所属事业部</th><th>二级部门</th><th>项目简称</th><th>审批编号</th><th>摘要</th><th>申请金额</th><th>收款主体</th><th>审批状态</th><th>操作</th></tr></thead>
    <tbody><tr v-for="i in items" :key="i.id" :class="{ 'row-sel': selectedIds.has(i.id) }">
      <td class="sel-col"><input type="checkbox" :checked="selectedIds.has(i.id)" @change="toggleRow(i.id)" /></td>
      <td>{{i.applicant}}</td><td>{{i.department}}</td>
      <td class="meta-cell">{{ i.secondary_dept || '—' }}</td>
      <td class="meta-cell" :title="i.project_short_name">{{ i.project_short_name || '—' }}</td>
      <td class="mono">{{i.approval_number}}</td><td class="summary">{{i.summary}}</td><td class="amt">{{i.amount}}<div v-if="parseFloat(i.scheduled_amount) > 0 && !i.archived" class="sched-sub">已排 {{i.scheduled_amount}}</div></td><td class="payee">{{i.payee}}</td>
      <td>
        <select :value="i.status" :disabled="statusUpdating[i.id]" @change="updateStatus(i, $event.target.value)">
          <option value="pending">待审批</option><option value="approved">审批通过</option><option value="rejected">已拒绝</option><option value="canceled">已撤销</option>
        </select>
      </td>
      <td class="ops-cell">
        <div class="ops-btns">
          <button class="btn btn-ghost btn-sm" :disabled="i.status!=='approved'" @click="openSchedule(i)">一键排款</button>
          <button class="btn btn-ghost btn-sm" title="补录/修改二级部门与项目简称" @click="openMeta(i)">补录</button>
        </div>
      </td></tr></tbody>
  </table>

  <!-- 浮动批量操作条：Teleport 到 body 固定在视口底部，全选后无需下拉即可操作 -->
  <Teleport to="body">
    <div v-if="!loading && items.length && hasSelection && !showBatchSched && !showDelConfirm && (auth.canDelete || auth.canCreate)" class="bulk-bar">
      <span class="bulk-n">已选 <strong>{{ selectedCount }}</strong> 条</span>
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
        <span class="bb-item warn"><i>申请金额合计</i><b>{{ pendingAmountTotal.toFixed(2) }}</b> 元</span>
      </div>
      <div v-if="total > filters.size" class="bb-pager">
        <button :disabled="filters.page <= 1" class="page-btn" @click="setPage(filters.page - 1)">‹ 上一页</button>
        <span class="page-info">{{ filters.page }} / {{ Math.ceil(total / filters.size) || 1 }} 页 · 共 {{ total }} 条</span>
        <button :disabled="filters.page * filters.size >= total" class="page-btn" @click="setPage(filters.page + 1)">下一页 ›</button>
      </div>
    </div>
  </Teleport>
  </div>

  <Teleport to="body"><div v-if="showCreate" class="modal-overlay"><div class="modal-box"><div class="modal-header"><h3>新增审批记录</h3></div><div class="modal-body"><div class="form-grid">
    <label class="form-field"><span>申请人*</span><input v-model="form.applicant"/></label>
    <label class="form-field"><span>所属事业部*</span><select v-model="form.department"><option v-for="d in deptChoices" :key="d" :value="d">{{d}}</option></select></label>
    <label class="form-field"><span>二级部门</span><input v-model="form.secondary_dept" placeholder="选填，如：华东项目部"/></label>
    <label class="form-field"><span>项目简称</span><ProjectShortNamePicker v-model="form.project_short_name" @picked="p => onProjPicked(p, form)"/></label>
    <label class="form-field"><span>审批编号</span><input v-model="form.approval_number" placeholder="21位数字；留空自动填21个0占位"/></label>
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
      本次金额小于剩余可排时为分批排款：本次先流转付款台账，记录留在审批管理可继续排；排满申请金额自动归档。
    </p>
    <div v-if="schedPrepaid" class="sched-prepaid-hint">
      💡 项目「{{ schedPrepaid.short_name }}」尚有 <b>{{ schedPrepaid.count }}</b> 笔预付未核销，
      余额合计 <b>{{ schedPrepaid.total_balance }}</b> 元。建议排款后到付款台账该行点「核销」，
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
      默认按各记录「剩余可排（首次=申请金额）」各排一笔流转付款台账，可逐条调小做分批排款（不得超过剩余可排）；所选中非「审批通过/已归档」的记录已自动排除。
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
    <p class="del-warn">⚠ 删除后不可恢复；已排款（已关联付款台账）的记录将自动跳过。</p>
    <p class="del-tip">请输入待删条数 <strong>{{ delConfirmCount }}</strong> 以确认：</p>
    <input v-model="delConfirmText" class="del-input" :placeholder="`输入 ${delConfirmCount}`" @keyup.enter="confirmBulkDelete"/>
  </div><div class="modal-footer"><button class="btn btn-ghost" @click="showDelConfirm=false">取消</button><button class="btn-danger-solid" :disabled="!delConfirmOk || bulkDeleting" @click="confirmBulkDelete">{{ bulkDeleting ? '删除中…' : '确认删除' }}</button></div></div></div></Teleport>

  <ImportResultModal :result="importResult" @close="importResult = null" />
</div></template>

<style scoped>
.approval-card { padding: 12px; }
.filter-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }

/* .bottom-bar, .bb-*, .page-btn, .page-info → global styles in style.css */
.approval-table { width: 100%; table-layout: fixed; }
/* 行高/内边距对齐全局表格（付款台账），保证两个页面观感一致 */
.approval-table th, .approval-table td { padding: 11px 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.approval-table th.sel-col, .approval-table td.sel-col { width: 34px; text-align: center; overflow: visible; padding: 11px 4px; }
.approval-table th.sel-col input, .approval-table td.sel-col input { cursor: pointer; }
.approval-table th:nth-child(2), .approval-table td:nth-child(2) { width: 7%; }
.approval-table th:nth-child(3), .approval-table td:nth-child(3) { width: 8%; }
.approval-table th:nth-child(4), .approval-table td:nth-child(4) { width: 7%; }
.approval-table th:nth-child(5), .approval-table td:nth-child(5) { width: 9%; }
.approval-table th:nth-child(6), .approval-table td:nth-child(6) { width: 12%; }
.approval-table th:nth-child(7), .approval-table td:nth-child(7) { width: 12%; }
.approval-table th:nth-child(8), .approval-table td:nth-child(8) { width: 7%; }
.approval-table th:nth-child(9), .approval-table td:nth-child(9) { width: 10%; }
.approval-table th:nth-child(10), .approval-table td:nth-child(10) { width: 12%; }
.approval-table th:nth-child(11), .approval-table td:nth-child(11) { width: 16%; }
/* 状态/操作两列内容（下拉、按钮）不裁切；下拉以本列宽为限，不再压到操作列 */
.approval-table th:nth-child(10), .approval-table td:nth-child(10),
.approval-table th:nth-child(11), .approval-table td:nth-child(11) {
  overflow: visible; text-overflow: clip; white-space: normal;
}
.approval-table tr.row-sel td { background: rgba(201,99,66,0.06); }
/* 批量操作条：固定浮动在视口底部居中，全选后无需下拉即可操作 */
.bulk-bar { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); z-index: 1200;
  display: flex; align-items: center; gap: 12px; padding: 10px 18px;
  border-radius: 12px; background: var(--card); border: 1px solid rgba(198,40,40,0.35);
  box-shadow: 0 8px 28px rgba(0,0,0,0.18); }
.bulk-n { font-size: 13px; color: var(--text); }
.bulk-act { margin-left: auto; border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--primary); color: #fff; }
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
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.amt { text-align: right; font-variant-numeric: tabular-nums; }
.summary, .payee { max-width: 100%; }
.approval-table select { width: 100%; min-width: 0; max-width: 100%; height: 32px; font-size: 12.5px; padding: 0 22px 0 6px; background-position: right 6px center; }
</style>
