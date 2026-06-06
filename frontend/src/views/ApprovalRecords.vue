<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { todayCST } from '../constants.js'
import { downloadBlob } from '../utils/download.js'
import EmptyState from '../components/EmptyState.vue'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const totalAmount = ref(0)
const loading = ref(false)
const depts = ref([])
const fileRef = ref(null)
const importing = ref(false)
const exporting = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const showSchedule = ref(false)
const current = ref(null)
const form = reactive({ applicant:'', department:'', approval_number:'', summary:'', amount:'', payee:'', status:'pending' })
const scheduleForm = reactive({ planned_date:'', total_amount:'' })
const filters = reactive({ applicant:'', approval_number:'', dept:'', page:1, size:50 })
const statusUpdating = ref({})
const pendingAmountTotal = computed(() => parseFloat(totalAmount.value || 0))

const deptChoices = computed(() => {
  const scope = auth.effectiveDepts
  if (auth.isAdmin && !auth.activeDepts.length) return depts.value
  return depts.value.filter(d => scope.includes(d))
})

async function load(){ loading.value=true; try{ const r=await api.get('/approvals',{params:filters}); items.value=r.data.items; total.value=r.data.total; totalAmount.value=r.data.total_amount || 0 }finally{loading.value=false}}
function search(){ filters.page=1; load() }
function setPage(p){ filters.page=p; load() }
async function loadDepts(){ try{const r=await api.get('/departments'); depts.value=r.data}catch{}}
function openCreate(){ Object.assign(form,{ applicant:'', department:deptChoices.value[0]||'', approval_number:'', summary:'', amount:'', payee:'', status:'pending' }); showCreate.value=true }
async function create(){ saving.value=true; try{ await api.post('/approvals', form); showCreate.value=false; load() } catch(e){ alert(e?.error||'保存失败') } finally{ saving.value=false } }
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
function openSchedule(it){ current.value=it; Object.assign(scheduleForm,{ planned_date: todayCST(), total_amount:it.amount }); showSchedule.value=true }
async function doSchedule(){ try{ await api.post(`/approvals/${current.value.id}/schedule`, scheduleForm); showSchedule.value=false; load(); alert('排款成功并已归档') } catch(e){ alert(e?.error||'排款失败') } }
async function downloadTemplate(){ const b=await api.get('/approvals/template',{responseType:'blob'}); dl(b,'审批记录导入模板.xlsx') }
const dl = downloadBlob
function triggerImport(){ fileRef.value.click() }
async function onImport(e){
  const f=e.target.files?.[0]; if(!f) return
  importing.value=true; const fd=new FormData(); fd.append('file',f)
  try{
    const r=await api.post('/approvals/import',fd,{headers:{'Content-Type':'multipart/form-data'}})
    const d=r.data||{}; const errs=d.errors||[]
    let msg=`导入完成：新增 ${d.created||0} 条，跳过 ${d.skipped||0} 条`
    if(errs.length){
      const show=errs.slice(0,15)
      msg+='\n\n未导入明细（含原因）：\n'+show.join('\n')
      if(errs.length>show.length) msg+=`\n…等共 ${errs.length} 条`
    }
    alert(msg); load()
  }catch(err){ alert(err?.error||'导入失败，请检查文件格式或表头') }
  finally{ importing.value=false; e.target.value='' }
}
async function doExport(){ exporting.value=true; try{ const b=await api.get('/approvals/export',{params:filters,responseType:'blob'}); dl(b,'审批记录.xlsx') } finally{ exporting.value=false } }

const onScopeChange = () => {
  if (filters.dept && !auth.effectiveDepts.includes(filters.dept)) filters.dept = ''
  filters.page = 1
  load()
}
onMounted(()=>{ load(); loadDepts(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(()=>window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template><div>
  <div class="topbar"><h1>审批记录</h1><div style="display:flex;gap:8px">
    <button class="btn btn-ghost btn-sm" @click="downloadTemplate">模板</button>
    <button class="btn btn-ghost btn-sm" @click="triggerImport">{{ importing?'导入中…':'导入' }}</button>
    <button class="btn btn-ghost btn-sm" @click="doExport">{{ exporting?'导出中…':'导出' }}</button>
    <button v-if="auth.canCreate" class="btn btn-primary" @click="openCreate">+ 新增审批记录</button>
  </div></div>
  <input ref="fileRef" type="file" accept=".xlsx,.xls" style="display:none" @change="onImport" />
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
  <table v-else class="approval-table"><thead><tr><th>申请人</th><th>所属事业部</th><th>审批编号</th><th>摘要</th><th>申请金额</th><th>收款主体</th><th>审批状态</th><th>操作</th></tr></thead>
    <tbody><tr v-for="i in items" :key="i.id"><td>{{i.applicant}}</td><td>{{i.department}}</td><td class="mono">{{i.approval_number}}</td><td class="summary">{{i.summary}}</td><td class="amt">{{i.amount}}</td><td class="payee">{{i.payee}}</td>
      <td>
        <select :value="i.status" :disabled="statusUpdating[i.id]" @change="updateStatus(i, $event.target.value)">
          <option value="pending">待审批</option><option value="approved">审批通过</option><option value="rejected">已拒绝</option><option value="canceled">已撤销</option>
        </select>
      </td>
      <td><button class="btn btn-ghost btn-sm" :disabled="i.status!=='approved'" @click="openSchedule(i)">一键排款</button></td></tr></tbody>
  </table>

  <!-- 吸底合计 + 翻页：Teleport 到 body 以逃脱 .card transform 产生的 fixed 包含块 -->
  <Teleport to="body">
    <div v-if="!loading && items.length" class="bottom-bar">
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

  <Teleport to="body"><div v-if="showCreate" class="modal-overlay" @click.self="showCreate=false"><div class="modal-box"><div class="modal-header"><h3>新增审批记录</h3></div><div class="modal-body"><div class="form-grid">
    <label class="form-field"><span>申请人*</span><input v-model="form.applicant"/></label>
    <label class="form-field"><span>所属事业部*</span><select v-model="form.department"><option v-for="d in deptChoices" :key="d" :value="d">{{d}}</option></select></label>
    <label class="form-field"><span>审批编号</span><input v-model="form.approval_number" placeholder="21位数字；留空自动填21个0占位"/></label>
    <label class="form-field"><span>摘要</span><input v-model="form.summary"/></label>
    <label class="form-field"><span>申请金额*</span><input v-model="form.amount" type="number" step="0.01"/></label>
    <label class="form-field"><span>收款主体</span><input v-model="form.payee"/></label>
    <label class="form-field"><span>审批状态</span><select v-model="form.status"><option value="pending">待审批</option><option value="approved">审批通过</option><option value="rejected">已拒绝</option><option value="canceled">已撤销</option></select></label>
  </div></div><div class="modal-footer"><button class="btn btn-ghost" @click="showCreate=false">取消</button><button class="btn btn-primary" :disabled="saving" @click="create">保存</button></div></div></div></Teleport>

  <Teleport to="body"><div v-if="showSchedule" class="modal-overlay" @click.self="showSchedule=false"><div class="modal-box"><div class="modal-header"><h3>一键排款</h3></div><div class="modal-body"><div class="form-grid">
    <label class="form-field"><span>计划日期*</span><input v-model="scheduleForm.planned_date" type="date"/></label>
    <label class="form-field"><span>计划金额*</span><input v-model="scheduleForm.total_amount" type="number" step="0.01"/></label>
  </div></div><div class="modal-footer"><button class="btn btn-ghost" @click="showSchedule=false">取消</button><button class="btn btn-primary" @click="doSchedule">保存并排款</button></div></div></div></Teleport>

</div></template>

<style scoped>
.approval-card { padding: 12px; }
.filter-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }

/* .bottom-bar, .bb-*, .page-btn, .page-info → global styles in style.css */
.approval-table { width: 100%; table-layout: fixed; }
/* 行高/内边距对齐全局表格（付款台账），保证两个页面观感一致 */
.approval-table th, .approval-table td { padding: 11px 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.approval-table th:nth-child(1), .approval-table td:nth-child(1) { width: 8%; }
.approval-table th:nth-child(2), .approval-table td:nth-child(2) { width: 11%; }
.approval-table th:nth-child(3), .approval-table td:nth-child(3) { width: 16%; }
.approval-table th:nth-child(4), .approval-table td:nth-child(4) { width: 17%; }
.approval-table th:nth-child(5), .approval-table td:nth-child(5) { width: 10%; }
.approval-table th:nth-child(6), .approval-table td:nth-child(6) { width: 14%; }
.approval-table th:nth-child(7), .approval-table td:nth-child(7) { width: 14%; }
.approval-table th:nth-child(8), .approval-table td:nth-child(8) { width: 10%; }
.approval-table th:nth-child(7), .approval-table td:nth-child(7) { overflow: visible; text-overflow: clip; white-space: normal; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.amt { text-align: right; font-variant-numeric: tabular-nums; }
.summary, .payee { max-width: 100%; }
.approval-table select { width: 100%; min-width: 130px; height: 32px; font-size: 13px; padding: 0 24px 0 8px; background-position: right 6px center; }
</style>
