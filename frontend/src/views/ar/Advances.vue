<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { downloadBlob } from '../../utils/download.js'
import ImportPrecheckModal from '../../components/ImportPrecheckModal.vue'

const auth = useAuthStore()
const route = useRoute()

const direction = ref('预收')          // '预收' | '预付' | 'suppliers'
const projectFilter = ref(null)        // { id, label } or null
const items = ref([])
const total = ref(0)
const kpi = ref(null)
const loading = ref(false)
const page = ref(1)
const size = 50

const filters = reactive({ dept: '', year: '', month: '', writeoff_status: '', q: '' })

// 部门下拉数据源：优先用与系统常量匹配的事业部；若用户真实部门名不在常量内
// （历史命名/二级部门等），回退到其真实可见部门，避免下拉为空导致无法选择部门。
const accessibleDepts = computed(() => {
  const eff = auth.effectiveDepts || []
  const matched = eff.filter(d => DEPARTMENTS.includes(d))
  if (matched.length) return matched
  return eff.length ? eff : (auth.allowedDepts || [])
})
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const fmtAmt = (v) => fmtCompact(v, { dash: '0.00' })

const show = k => auth.canArView(k)
const canCreate = computed(() => auth.canArWrite)
const canDelete = computed(() => auth.canDelete)
// 操作级权限：核销按当前方向取对应动作键；收付登记独立动作
const canWoAction = computed(() => auth.canAction(direction.value === '预收' ? 'wo_receive' : 'wo_prepaid'))
const canInstAction = computed(() => auth.canAction('adv_installment'))

const isReceive = computed(() => direction.value === '预收')
const isAdvanceMode = computed(() => direction.value === '预收' || direction.value === '预付')
const dirLabel = computed(() => direction.value === '预收' ? '预收' : '预付')
const partyLabel = computed(() => direction.value === '预收' ? '客户' : '供应商')

const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)
const precheckResult = ref(null)
const precheckBusy = ref(false)
const pendingFile = ref(null)

async function load(reset = false) {
  if (!isAdvanceMode.value) return
  if (reset) page.value = 1
  loading.value = true
  try {
    const params = { direction: direction.value, ...filters, page: page.value, size }
    if (projectFilter.value) params.project_id = projectFilter.value.id
    const [res, k] = await Promise.all([
      ar.listAdvances(params),
      ar.advancesKpi({ direction: direction.value, ...filters }),
    ])
    items.value = res.data.items
    total.value = res.data.total
    kpi.value = k.data[direction.value]
  } finally { loading.value = false }
}

function switchDir(d) {
  if (d === direction.value) return
  direction.value = d
  if (d === 'suppliers') {
    loadSuppliers()
  } else if (d === 'diff') {
    loadDiff()
  } else {
    load(true)
  }
}

// ── 收付差异（预收 vs 预付，按项目简称对齐）─────────────────────────────────
const diffData = ref(null)
const diffLoading = ref(false)
const diffQ = ref('')
let diffTimer = null
const diffExpanded = ref(new Set())     // 展开的项目行
const diffAllOpen = ref(false)          // 一键展开/折叠总控

async function loadDiff() {
  diffLoading.value = true
  try {
    const res = await ar.advanceDiffSummary({ q: diffQ.value.trim() || undefined })
    diffData.value = res.data
    diffExpanded.value = new Set()
    diffAllOpen.value = false
  } catch (_) { diffData.value = null }
  finally { diffLoading.value = false }
}
function onDiffSearch() { clearTimeout(diffTimer); diffTimer = setTimeout(loadDiff, 300) }
function toggleDiffRow(name) {
  const s = new Set(diffExpanded.value)
  s.has(name) ? s.delete(name) : s.add(name)
  diffExpanded.value = s
}
function toggleDiffAll() {
  diffAllOpen.value = !diffAllOpen.value
  diffExpanded.value = diffAllOpen.value
    ? new Set((diffData.value?.rows || []).map(r => r.project))
    : new Set()
}
function onFilterChange() { load(true) }
let qTimer = null
function onQInput() { clearTimeout(qTimer); qTimer = setTimeout(() => load(true), 300) }
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size)))
function go(p) { if (p < 1 || p > totalPages.value) return; page.value = p; load() }

// ── create / edit ──────────────────────────────────────────────────────────
const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const form = reactive({
  project_id: '', delivery_dept: '', counterparty: '',
  occur_year: yearCST(), occur_month: monthCST(), occur_date: todayCST(),
  advance_amount: '', expected_writeoff_date: '', notes: '',
})

const projects = ref([])
const projectKeyword = ref('')
const showProjList = ref(false)
let projectTimer = null
async function searchProjects(kw) {
  const res = await ar.listProjects({ size: 100, q: kw || undefined })
  projects.value = res.data.items
}
function onProjectKeywordInput() {
  showProjList.value = true
  if (!projectKeyword.value.trim()) form.project_id = ''
  clearTimeout(projectTimer)
  projectTimer = setTimeout(() => searchProjects(projectKeyword.value.trim()), 220)
}
let autoCounterparty = ''
function pickProject(p) {
  if (p) {
    form.project_id = p.id
    form.delivery_dept = p.delivery_dept
    projectKeyword.value = `${p.short_name}（${p.delivery_dept}）`
    if (direction.value === '预收' && p.customer_name &&
        (!form.counterparty || form.counterparty === autoCounterparty)) {
      form.counterparty = p.customer_name
      autoCounterparty = p.customer_name
    }
  } else {
    form.project_id = ''
    projectKeyword.value = ''
  }
  showProjList.value = false
}
function onProjBlur() { setTimeout(() => { showProjList.value = false }, 160) }

function openCreate() {
  editRec.value = null
  Object.assign(form, {
    project_id: '', delivery_dept: accessibleDepts.value[0] || '', counterparty: '',
    occur_year: yearCST(), occur_month: monthCST(), occur_date: todayCST(),
    advance_amount: '', expected_writeoff_date: '', notes: '',
  })
  projectKeyword.value = ''
  autoCounterparty = ''
  searchProjects('')
  showModal.value = true
}
function openEdit(rec) {
  editRec.value = rec
  Object.assign(form, {
    project_id: rec.project_id || '', delivery_dept: rec.delivery_dept || '',
    counterparty: rec.counterparty || '',
    occur_year: rec.occur_year, occur_month: rec.occur_month, occur_date: rec.occur_date || '',
    advance_amount: rec.advance_amount, expected_writeoff_date: rec.expected_writeoff_date || '',
    notes: rec.notes || '',
  })
  projectKeyword.value = rec.short_name || ''
  autoCounterparty = ''
  searchProjects(rec.short_name || '')
  showModal.value = true
}
async function save() {
  saving.value = true
  try {
    const payload = { direction: direction.value, ...form }
    if (!payload.project_id) delete payload.project_id
    if (editRec.value) await ar.updateAdvance(editRec.value.id, payload)
    else await ar.createAdvance(payload)
    showModal.value = false
    await load()
  } catch (e) { alert(e?.msg || '保存失败') }
  finally { saving.value = false }
}
async function removeRec(rec) {
  if (!confirm(`确认删除该${dirLabel.value}记录（${rec.counterparty}）？核销记录将一并删除。`)) return
  try { await ar.deleteAdvance(rec.id); await load() }
  catch (e) { alert(e?.msg || '删除失败') }
}

// ── writeoffs ───────────────────────────────────────────────────────────────
const showWoModal = ref(false)
const woRec = ref(null)
const woList = ref([])
const woForm = reactive({ amount: '', writeoff_date: todayCST(), notes: '', ar_record_id: '' })
const woSaving = ref(false)
const woOffsetRecords = ref([])
const canOffset = computed(() =>
  woRec.value?.direction === '预收' &&
  (!!woRec.value?.project_id || !!woRec.value?.counterparty) &&
  woOffsetRecords.value.length > 0)

async function openWriteoffs(rec) {
  woRec.value = rec
  Object.assign(woForm, { amount: '', writeoff_date: todayCST(), notes: '', ar_record_id: '' })
  woOffsetRecords.value = []
  showWoModal.value = true
  await Promise.all([refreshWriteoffs(), loadOffsetRecords(rec)])
}
async function loadOffsetRecords(rec) {
  if (rec.direction !== '预收') return
  const params = rec.project_id ? { project_id: rec.project_id }
    : (rec.counterparty ? { customer: rec.counterparty } : null)
  if (!params) return
  try {
    const res = await ar.advanceOffsettable(params)
    woOffsetRecords.value = res.data.items || []
  } catch (_) { woOffsetRecords.value = [] }
}
async function refreshWriteoffs() {
  const res = await ar.listWriteoffs(woRec.value.id)
  woList.value = res.data
}
async function addWriteoff() {
  if (!(parseFloat(woForm.amount) > 0)) { alert('核销金额必须大于0'); return }
  woSaving.value = true
  try {
    const payload = { ...woForm }
    if (!payload.ar_record_id) delete payload.ar_record_id
    await ar.addWriteoff(woRec.value.id, payload)
    Object.assign(woForm, { amount: '', writeoff_date: todayCST(), notes: '', ar_record_id: '' })
    await loadOffsetRecords(woRec.value)
    await refreshWriteoffs()
    await load()
    const fresh = items.value.find(r => r.id === woRec.value.id)
    if (fresh) woRec.value = fresh
  } catch (e) { alert(e?.msg || '核销失败') }
  finally { woSaving.value = false }
}
async function delWriteoff(w) {
  if (!confirm('确认删除该核销记录？')) return
  try {
    await ar.deleteWriteoff(woRec.value.id, w.id)
    await refreshWriteoffs(); await load()
    const fresh = items.value.find(r => r.id === woRec.value.id)
    if (fresh) woRec.value = fresh
  } catch (e) { alert(e?.msg || '删除失败') }
}

// ── 收付明细（多次到账/付出；总额=明细之和，派生） ───────────────────────────
const showInstModal = ref(false)
const instRec = ref(null)
const instList = ref([])
const instForm = reactive({ amount: '', occur_date: todayCST(), notes: '' })
const instBusy = ref(false)
async function openInstallments(rec) {
  instRec.value = rec
  Object.assign(instForm, { amount: '', occur_date: todayCST(), notes: '' })
  instList.value = []
  showInstModal.value = true
  try {
    const res = await ar.listAdvInstallments(rec.id)
    instList.value = res.data.items
  } catch (_) { instList.value = [] }
}
async function addInstallment() {
  if (!parseFloat(instForm.amount)) { alert('收付金额不能为0（可负=退回）'); return }
  instBusy.value = true
  try {
    const res = await ar.addAdvInstallment(instRec.value.id, { ...instForm })
    instList.value = res.data.items
    Object.assign(instForm, { amount: '', occur_date: todayCST(), notes: '' })
    await load()
    const fresh = items.value.find(r => r.id === instRec.value.id)
    if (fresh) instRec.value = fresh
  } catch (e) { alert(e?.msg || '新增收付失败') }
  finally { instBusy.value = false }
}
async function delInstallment(i) {
  if (!confirm(`删除第${i.install_no}笔收付 ${i.amount} 元？总额与未核销余额将随之回退。`)) return
  instBusy.value = true
  try {
    const res = await ar.deleteAdvInstallment(instRec.value.id, i.id)
    instList.value = res.data.items
    await load()
    const fresh = items.value.find(r => r.id === instRec.value.id)
    if (fresh) instRec.value = fresh
  } catch (e) { alert(e?.msg || '删除失败') }
  finally { instBusy.value = false }
}

// ── template / import / export ────────────────────────────────────────────────
async function downloadTemplate() {
  try {
    const res = await ar.advanceTemplate()
    downloadBlob(res, '预收预付导入模板.xlsx')
  } catch (e) { alert(e?.msg || '模板下载失败') }
}
async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  pendingFile.value = f
  precheckResult.value = null
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const pr = await ar.precheckAdvances(fd); const pd = pr.data
    if (pd.skipPrecheck) { await doImport(f); return }
    if ((pd.attention || 0) > 0) { precheckResult.value = pd; return }
    await doImport(f)
  } catch (e) { alert(e?.msg || '导入失败') }
  finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function doImport(f) {
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importAdvances(fd); const d = res.data
    if (d.rejected) {
      alert((d.message || '导入未执行，请按提示修正后重新导入') + '\n\n' + (d.errors || []).join('\n'))
    } else {
      alert(`导入完成：创建 ${d.created} 条`)
    }
    await load()
  } catch (e) { alert(e?.msg || '导入失败') }
  finally { importing.value = false }
}

async function onPrecheckApply({ mode }) {
  if (mode !== 'import') return
  precheckBusy.value = true
  try {
    await doImport(pendingFile.value)
    precheckResult.value = null
  } finally { precheckBusy.value = false; importing.value = false }
}
async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportAdvances({ direction: direction.value, ...filters })
    downloadBlob(res, `${dirLabel.value}明细.xlsx`)
  } catch (e) { alert(e?.msg || '导出失败') }
  finally { exporting.value = false }
}

function woStatusClass(s) {
  return s === '已核销' ? 'pill-ok' : s === '部分核销' ? 'pill-blue' : 'pill-muted'
}

function clearProjectFilter() { projectFilter.value = null; load(true) }

// ── Supplier management ───────────────────────────────────────────────────────
const supplierItems = ref([])
const supplierTotal = ref(0)
const supplierLoading = ref(false)
const supplierFilters = reactive({ type: '', dept: '', q: '' })

const showSupplierModal = ref(false)
const editSupplier = ref(null)
const supplierSaving = ref(false)
const supplierForm = reactive({
  name: '', supplier_type: 'public', project_id: '', delivery_dept: '',
  contact: '', notes: '',
})
const supplierProjKeyword = ref('')
const supplierProjects = ref([])
const showSupplierProjList = ref(false)
let supplierProjTimer = null

async function loadSuppliers() {
  supplierLoading.value = true
  try {
    const res = await ar.listSuppliers({ ...supplierFilters })
    supplierItems.value = res.data.items
    supplierTotal.value = res.data.total
  } finally { supplierLoading.value = false }
}

let supplierQTimer = null
function onSupplierQInput() {
  clearTimeout(supplierQTimer)
  supplierQTimer = setTimeout(loadSuppliers, 300)
}

async function searchSupplierProjects(kw) {
  try {
    const res = await ar.listProjects({ size: 100, q: kw || undefined })
    supplierProjects.value = res.data.items
  } catch (e) {
    supplierProjects.value = []
  }
}

// 切到「私有」时确保项目列表已加载（覆盖打开弹窗时异步竞态/失败的情况）
watch(() => supplierForm.supplier_type, (t) => {
  if (t === 'private' && !supplierProjects.value.length) {
    searchSupplierProjects(supplierProjKeyword.value.trim())
  }
})
function onSupplierProjKeywordInput() {
  showSupplierProjList.value = true
  if (!supplierProjKeyword.value.trim()) supplierForm.project_id = ''
  clearTimeout(supplierProjTimer)
  supplierProjTimer = setTimeout(() => searchSupplierProjects(supplierProjKeyword.value.trim()), 220)
}
function pickSupplierProject(p) {
  if (p) {
    supplierForm.project_id = p.id
    supplierForm.delivery_dept = p.delivery_dept
    supplierProjKeyword.value = `${p.short_name}（${p.delivery_dept}）`
  } else {
    supplierForm.project_id = ''
    supplierProjKeyword.value = ''
  }
  showSupplierProjList.value = false
}
function onSupplierProjBlur() { setTimeout(() => { showSupplierProjList.value = false }, 160) }

function openCreateSupplier() {
  editSupplier.value = null
  Object.assign(supplierForm, {
    name: '', supplier_type: 'public', project_id: '',
    delivery_dept: accessibleDepts.value[0] || '',
    contact: '', notes: '',
  })
  supplierProjKeyword.value = ''
  searchSupplierProjects('')
  showSupplierModal.value = true
}
function openEditSupplier(s) {
  editSupplier.value = s
  Object.assign(supplierForm, {
    name: s.name, supplier_type: s.supplier_type,
    project_id: s.project_id || '', delivery_dept: s.delivery_dept || '',
    contact: s.contact || '', notes: s.notes || '',
  })
  supplierProjKeyword.value = s.project_short_name
    ? `${s.project_short_name}（${s.delivery_dept}）` : ''
  if (s.project_short_name) searchSupplierProjects(s.project_short_name)
  showSupplierModal.value = true
}
async function saveSupplier() {
  supplierSaving.value = true
  try {
    const payload = { ...supplierForm }
    if (!payload.project_id) delete payload.project_id
    if (editSupplier.value) await ar.updateSupplier(editSupplier.value.id, payload)
    else await ar.createSupplier(payload)
    showSupplierModal.value = false
    await loadSuppliers()
  } catch (e) { alert(e?.msg || '保存失败') }
  finally { supplierSaving.value = false }
}
async function removeSupplier(s) {
  if (!confirm(`确认删除供应商「${s.name}」？`)) return
  try { await ar.deleteSupplier(s.id); await loadSuppliers() }
  catch (e) { alert(e?.msg || '删除失败') }
}

onMounted(() => {
  const q = route.query || {}
  if (q.direction === '预收' || q.direction === '预付') direction.value = q.direction
  if (q.project_id) {
    projectFilter.value = { id: Number(q.project_id), label: q.project_no || `项目#${q.project_id}` }
  }
  load()
})
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <div>
        <h1>预收预付</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          围绕项目台账登记预收/预付款，跟踪核销进度与挂账账龄，并打通现金流
        </div>
      </div>
    </div>

    <!-- direction / mode tabs -->
    <div class="dir-tabs">
      <button :class="['dir-tab', { active: direction === '预收' }]" @click="switchDir('预收')">预收（客户预付款）</button>
      <button :class="['dir-tab', { active: direction === '预付' }]" @click="switchDir('预付')">预付（付供应商）</button>
      <button :class="['dir-tab', { active: direction === 'diff' }]" @click="switchDir('diff')">收付差异</button>
      <div class="dir-tab-sep"></div>
      <button :class="['dir-tab', { active: direction === 'suppliers' }]" @click="switchDir('suppliers')">供应商池</button>
    </div>

    <!-- KPI (advances only) -->
    <div v-if="isAdvanceMode && kpi" class="kpi-row">
      <div class="kpi"><div class="kpi-k">{{ dirLabel }}笔数</div><div class="kpi-v">{{ kpi.count }} 笔</div></div>
      <div v-if="show('adv_amount')" class="kpi"><div class="kpi-k">{{ dirLabel }}金额</div><div class="kpi-v">{{ fmtAmt(kpi.advance_amount) }}</div></div>
      <div v-if="show('adv_writeoff')" class="kpi"><div class="kpi-k">已核销</div><div class="kpi-v">{{ fmtAmt(kpi.written_off) }}<span class="kpi-sub">{{ kpi.writeoff_rate }}%</span></div></div>
      <div v-if="show('adv_writeoff')" class="kpi accent"><div class="kpi-k">未核销余额</div><div class="kpi-v">{{ fmtAmt(kpi.balance) }}</div></div>
      <div v-if="show('adv_writeoff')" class="kpi warn"><div class="kpi-k">逾期挂账</div><div class="kpi-v">{{ fmtAmt(kpi.overdue_balance) }}<span class="kpi-sub">{{ kpi.overdue_count }} 笔</span></div></div>
    </div>

    <!-- ── Advance list (预收/预付) ── -->
    <template v-if="isAdvanceMode">
      <div class="card">
        <div class="filter-row">
          <select v-if="accessibleDepts.length > 1" v-model="filters.dept" class="sel sm" @change="onFilterChange">
            <option value="">全部部门</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <select v-model="filters.year" class="sel sm" @change="onFilterChange">
            <option value="">年</option>
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>
          <select v-model="filters.month" class="sel sm" @change="onFilterChange">
            <option value="">月</option>
            <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
          </select>
          <select v-model="filters.writeoff_status" class="sel sm" @change="onFilterChange">
            <option value="">核销状态</option>
            <option value="未核销">未核销</option>
            <option value="部分核销">部分核销</option>
            <option value="已核销">已核销</option>
          </select>
          <input v-model="filters.q" class="inp sm" placeholder="🔍 搜索往来单位 / 项目 / 备注" @input="onQInput" />
          <button v-if="projectFilter" class="proj-chip" @click="clearProjectFilter">
            项目：{{ projectFilter.label }} ✕
          </button>
          <div class="spacer"></div>
          <button class="btn btn-ghost btn-sm" @click="downloadTemplate">下载模板</button>
          <label v-if="canCreate" class="btn btn-ghost btn-sm" :class="{ disabled: importing }">
            {{ importing ? '导入中…' : '导入' }}
            <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" />
          </label>
          <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">{{ exporting ? '导出中…' : '导出' }}</button>
          <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增{{ dirLabel }}</button>
        </div>

        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th v-if="show('adv_counterparty')">往来单位</th>
                <th>项目/部门</th>
                <th>发生年月</th>
                <th>款项日期</th>
                <th v-if="show('adv_amount')" class="amt">{{ dirLabel }}金额</th>
                <th v-if="show('adv_writeoff')" class="amt">已核销</th>
                <th v-if="show('adv_writeoff')" class="amt">未核销余额</th>
                <th v-if="show('adv_writeoff')" class="ctr">核销状态</th>
                <th v-if="show('adv_expected_date')" class="ctr">挂账账龄</th>
                <th class="adv-notes-col">备注</th>
                <th class="ctr">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!loading && !items.length"><td colspan="11" class="empty">暂无{{ dirLabel }}记录</td></tr>
              <tr v-for="r in items" :key="r.id">
                <td v-if="show('adv_counterparty')">{{ r.counterparty || '—' }}</td>
                <td>
                  <div v-if="r.short_name" class="proj-name">{{ r.short_name }}</div>
                  <div class="dept-tag">{{ r.delivery_dept }}</div>
                </td>
                <td>{{ r.occur_year }}-{{ String(r.occur_month).padStart(2, '0') }}</td>
                <td>{{ r.occur_date || '—' }}</td>
                <td v-if="show('adv_amount')" class="amt num-strong">{{ fmtAmt(r.advance_amount) }}</td>
                <td v-if="show('adv_writeoff')" class="amt">{{ fmtAmt(r.written_off_amount) }}</td>
                <td v-if="show('adv_writeoff')" class="amt num-strong">{{ fmtAmt(r.balance_amount) }}</td>
                <td v-if="show('adv_writeoff')" class="ctr">
                  <span class="status-pill" :class="woStatusClass(r.writeoff_status)">{{ r.writeoff_status }}</span>
                </td>
                <td v-if="show('adv_expected_date')" class="ctr">
                  <span v-if="r.is_overdue" class="status-pill pill-danger">逾期{{ r.overdue_days }}天</span>
                  <span v-else-if="r.balance_amount > 0" class="status-pill pill-muted">挂账{{ r.pending_days }}天</span>
                  <span v-else>—</span>
                </td>
                <td class="adv-notes-cell" :title="r.notes">{{ r.notes || '—' }}</td>
                <td class="ctr nowrap">
                  <button v-if="show('adv_amount') && (canCreate || canInstAction)" class="lnk" title="多次到账/付出明细（总额=明细之和）" @click="openInstallments(r)">收付</button>
                  <button v-if="show('adv_writeoff') && (canCreate || canWoAction)" class="lnk" @click="openWriteoffs(r)">核销</button>
                  <button v-if="canCreate" class="lnk" @click="openEdit(r)">编辑</button>
                  <button v-if="canDelete" class="lnk danger" @click="removeRec(r)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="pager" v-if="totalPages > 1">
          <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
          <span>{{ page }} / {{ totalPages }}（共 {{ total }} 条）</span>
          <button class="btn btn-ghost btn-sm" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
        </div>
      </div>
    </template>

    <!-- ── 收付差异：预收 vs 预付，按项目简称对齐 ── -->
    <template v-else-if="direction === 'diff'">
      <!-- 汇总条 -->
      <div v-if="diffData?.summary" class="kpi-row">
        <div class="kpi"><div class="kpi-k">涉及项目</div><div class="kpi-v">{{ diffData.summary.count }} 个</div></div>
        <div class="kpi"><div class="kpi-k">预收合计</div><div class="kpi-v" style="color:#2e7d32">{{ fmtAmt(diffData.summary.in_total) }}</div></div>
        <div class="kpi"><div class="kpi-k">预付合计</div><div class="kpi-v" style="color:#ef6c00">{{ fmtAmt(diffData.summary.out_total) }}</div></div>
        <div class="kpi accent"><div class="kpi-k">差异（预收−预付）</div>
          <div class="kpi-v" :style="{ color: parseFloat(diffData.summary.diff) >= 0 ? '#2e7d32' : '#c62828' }">{{ fmtAmt(diffData.summary.diff) }}</div></div>
      </div>

      <div class="card">
        <div class="filter-row">
          <input v-model="diffQ" class="inp sm" style="width:220px" placeholder="搜项目简称" @input="onDiffSearch" />
          <div style="flex:1"></div>
          <button class="btn btn-ghost btn-sm" @click="toggleDiffAll">
            {{ diffAllOpen ? '▲ 一键折叠' : '▼ 一键展开' }}
          </button>
        </div>
        <div v-if="diffLoading" class="empty" style="padding:30px;text-align:center">⏳ 加载中…</div>
        <div v-else-if="!diffData?.rows?.length" class="empty" style="padding:30px;text-align:center">
          暂无数据——只有挂了项目台账的预收/预付才参与差异对照
        </div>
        <div v-else class="table-wrap">
          <table class="diff-table">
            <thead>
              <tr>
                <th class="dt-proj">项目简称 / 部门</th>
                <th class="dt-amt">预收金额</th>
                <th class="dt-amt">预付金额</th>
                <th class="dt-amt">差异（预收−预付）</th>
                <th class="dt-notes">备注</th>
                <th class="dt-caret"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in diffData.rows" :key="r.project">
                <tr class="diff-row" @click="toggleDiffRow(r.project)">
                  <td class="dt-proj">
                    <span class="dt-name" :title="r.project">{{ r.project }}</span>
                    <span class="dt-dept">{{ (r.dept || '—').replace('事业部', '') }}</span>
                  </td>
                  <td class="dt-amt" style="color:#2e7d32">{{ parseFloat(r.in_total) ? fmtAmt(r.in_total) : '—' }}</td>
                  <td class="dt-amt" style="color:#ef6c00">{{ parseFloat(r.out_total) ? fmtAmt(r.out_total) : '—' }}</td>
                  <td class="dt-amt fw" :style="{ color: parseFloat(r.diff) >= 0 ? '#2e7d32' : '#c62828' }">{{ fmtAmt(r.diff) }}</td>
                  <td class="dt-notes" :title="r.notes">{{ r.notes || '—' }}</td>
                  <td class="dt-caret">{{ diffExpanded.has(r.project) ? '▲' : '▼' }}</td>
                </tr>
                <tr v-if="diffExpanded.has(r.project)" class="diff-detail-row">
                  <td colspan="6">
                    <div class="diff-detail">
                      <div class="dd-col">
                        <div class="dd-head in">预收明细 · {{ r.in_items.length }} 笔</div>
                        <div v-if="!r.in_items.length" class="dd-empty">无预收记录</div>
                        <div v-for="i in r.in_items" :key="'i' + i.id" class="dd-item">
                          <span class="dd-date">{{ i.occur_date }}</span>
                          <b class="dd-amt in">{{ fmtAmt(i.amount) }}</b>
                          <span class="dd-party" :title="i.counterparty">{{ i.counterparty }}</span>
                          <em v-if="parseFloat(i.balance) > 0" class="dd-bal">余 {{ fmtAmt(i.balance) }}</em>
                        </div>
                      </div>
                      <div class="dd-col">
                        <div class="dd-head out">预付明细 · {{ r.out_items.length }} 笔</div>
                        <div v-if="!r.out_items.length" class="dd-empty">无预付记录</div>
                        <div v-for="i in r.out_items" :key="'o' + i.id" class="dd-item">
                          <span class="dd-date">{{ i.occur_date }}</span>
                          <b class="dd-amt out">{{ fmtAmt(i.amount) }}</b>
                          <span class="dd-party" :title="i.counterparty">{{ i.counterparty }}</span>
                          <em v-if="parseFloat(i.balance) > 0" class="dd-bal">余 {{ fmtAmt(i.balance) }}</em>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ── Supplier pool ── -->
    <template v-else>
      <div class="card">
        <div class="filter-row">
          <select v-model="supplierFilters.type" class="sel sm" @change="loadSuppliers">
            <option value="">全部类型</option>
            <option value="private">私有（绑项目）</option>
            <option value="public">公共（绑事业部）</option>
          </select>
          <select v-if="accessibleDepts.length > 1" v-model="supplierFilters.dept" class="sel sm" @change="loadSuppliers">
            <option value="">全部部门</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <input v-model="supplierFilters.q" class="inp sm" placeholder="🔍 搜索供应商名称 / 联系人" @input="onSupplierQInput" />
          <div class="spacer"></div>
          <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openCreateSupplier">+ 新增供应商</button>
        </div>

        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>供应商名称</th>
                <th class="ctr">类型</th>
                <th>关联项目 / 部门</th>
                <th>联系人</th>
                <th class="amt">预付余额</th>
                <th class="ctr">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!supplierLoading && !supplierItems.length">
                <td colspan="6" class="empty">暂无供应商，点击「新增供应商」添加</td>
              </tr>
              <tr v-for="s in supplierItems" :key="s.id">
                <td><b>{{ s.name }}</b><div v-if="s.notes" class="dept-tag">{{ s.notes }}</div></td>
                <td class="ctr">
                  <span class="status-pill" :class="s.supplier_type === 'private' ? 'pill-blue' : 'pill-muted'">
                    {{ s.supplier_type === 'private' ? '私有' : '公共' }}
                  </span>
                </td>
                <td>
                  <div v-if="s.project_short_name" class="proj-name">{{ s.project_short_name }}</div>
                  <div class="dept-tag">{{ s.delivery_dept }}</div>
                </td>
                <td>{{ s.contact || '—' }}</td>
                <td class="amt">
                  <span :class="{ 'num-strong': parseFloat(s.prepaid_balance) > 0, 'bal-positive': parseFloat(s.prepaid_balance) > 0 }">
                    {{ parseFloat(s.prepaid_balance) > 0 ? fmtAmt(s.prepaid_balance) : '—' }}
                  </span>
                  <span v-if="s.prepaid_count > 0" class="kpi-sub"> {{ s.prepaid_count }}笔</span>
                </td>
                <td class="ctr nowrap">
                  <button v-if="canCreate" class="lnk" @click="openEditSupplier(s)">编辑</button>
                  <button v-if="canDelete" class="lnk danger" @click="removeSupplier(s)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="supplierLoading" style="text-align:center;padding:20px;color:var(--muted)">加载中…</div>
      </div>
    </template>

    <!-- ── create / edit advance modal ── -->
    <div v-if="showModal" class="modal-mask" @click.self="showModal = false">
      <div class="modal">
        <h3>{{ editRec ? '编辑' : '新增' }}{{ dirLabel }}</h3>
        <div class="form-grid">
          <label class="fld full">
            <span>关联项目（可选，搜索选择；留空则仅填往来单位）</span>
            <div class="combo">
              <input v-model="projectKeyword" class="inp" placeholder="搜索项目简称 / 编号…"
                     @focus="showProjList = true" @input="onProjectKeywordInput" @blur="onProjBlur" />
              <button v-if="form.project_id || projectKeyword" type="button" class="combo-clear"
                      @mousedown.prevent="pickProject(null)">×</button>
              <ul v-if="showProjList" class="combo-list">
                <li class="combo-opt muted" @mousedown.prevent="pickProject(null)">不关联项目（仅填往来单位）</li>
                <li v-for="p in projects" :key="p.id" class="combo-opt"
                    :class="{ on: form.project_id === p.id }" @mousedown.prevent="pickProject(p)">
                  <span>{{ p.short_name }}</span><span class="combo-dept">{{ p.delivery_dept }}</span>
                </li>
                <li v-if="!projects.length" class="combo-opt muted">无匹配项目</li>
              </ul>
            </div>
          </label>
          <label class="fld" v-if="!form.project_id">
            <span>交付部门 <em>*</em></span>
            <select v-model="form.delivery_dept" class="sel">
              <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
            </select>
          </label>
          <label class="fld"><span>{{ partyLabel }}（往来单位） <em>*</em></span>
            <input v-model="form.counterparty" class="inp" :placeholder="`${partyLabel}名称`" /></label>
          <label class="fld"><span>发生年 <em>*</em></span>
            <select v-model.number="form.occur_year" class="sel"><option v-for="y in years" :key="y" :value="y">{{ y }}</option></select></label>
          <label class="fld"><span>发生月 <em>*</em></span>
            <select v-model.number="form.occur_month" class="sel"><option v-for="m in months" :key="m" :value="m">{{ m }}</option></select></label>
          <label class="fld"><span>款项日期</span><input v-model="form.occur_date" type="date" class="inp" /></label>
          <label class="fld"><span>{{ dirLabel }}金额（元）</span><input v-model="form.advance_amount" type="number" step="0.01" class="inp" /></label>
          <label class="fld"><span>预计核销日期</span><input v-model="form.expected_writeoff_date" type="date" class="inp" /></label>
          <label class="fld full"><span>备注</span><input v-model="form.notes" class="inp" /></label>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showModal = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- ── writeoff modal ── -->
    <div v-if="showWoModal" class="modal-mask" @click.self="showWoModal = false">
      <div class="modal">
        <h3>核销 · {{ woRec.counterparty }}</h3>
        <div class="wo-summary">
          <span>{{ dirLabel }}金额 <b>{{ fmtAmt(woRec.advance_amount) }}</b></span>
          <span>已核销 <b>{{ fmtAmt(woRec.written_off_amount) }}</b></span>
          <span class="hl">未核销余额 <b>{{ fmtAmt(woRec.balance_amount) }}</b></span>
        </div>
        <table class="data-table compact">
          <thead>
            <tr>
              <th>#</th><th class="amt">核销金额</th><th>核销日期</th>
              <th>冲抵明细</th><th>备注</th><th v-if="canDelete || canWoAction"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!woList.length"><td :colspan="(canDelete || canWoAction) ? 6 : 5" class="empty">暂无核销记录</td></tr>
            <tr v-for="w in woList" :key="w.id">
              <td>{{ w.writeoff_no }}</td>
              <td class="amt">{{ fmtAmt(w.amount) }}</td>
              <td>{{ w.writeoff_date }}</td>
              <td>
                <span v-if="w.ar_record_id" class="offset-badge" :title="`已生成预收抵扣回款 · ${w.ar_project_no || ''}`">↳ 转回款</span>
                <span v-else-if="w.payment_id" class="offset-badge pay-badge" :title="`关联排款: ${w.payment_payee || ''}`">↳ 排款#{{ w.payment_id }}</span>
                <span v-else>—</span>
              </td>
              <td>{{ w.notes || '—' }}</td>
              <td v-if="canDelete || canWoAction"><button class="lnk danger" @click="delWriteoff(w)">删除</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="canCreate || canWoAction" class="wo-add">
          <div v-if="canOffset" class="wo-offset-row">
            <span class="wo-offset-lbl">冲抵应收：</span>
            <select v-model="woForm.ar_record_id" class="inp wo-offset-sel">
              <option value="">不冲抵（仅登记核销）</option>
              <option v-for="o in woOffsetRecords" :key="o.id" :value="o.id">{{ o.label }}</option>
            </select>
            <span v-if="woForm.ar_record_id" class="wo-offset-tip">↳ 核销后自动生成「预收抵扣」回款，冲减应收未收余额（不计现金）</span>
          </div>
          <div class="wo-inputs">
            <input v-model="woForm.amount" type="number" step="0.01" class="inp" placeholder="核销金额(元)" />
            <input v-model="woForm.writeoff_date" type="date" class="inp" />
            <input v-model="woForm.notes" class="inp" placeholder="备注" />
            <button class="btn btn-primary btn-sm" :disabled="woSaving" @click="addWriteoff">{{ woSaving ? '…' : '新增核销' }}</button>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showWoModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- ── installment modal（收付明细：一条记录多次到账/付出）── -->
    <div v-if="showInstModal" class="modal-mask" @click.self="showInstModal = false">
      <div class="modal">
        <h3>收付明细 · {{ instRec.counterparty }}</h3>
        <div class="wo-summary">
          <span>{{ dirLabel }}总额 <b>{{ fmtAmt(instRec.advance_amount) }}</b><i style="font-style:normal;font-size:11px;color:var(--muted)">（=明细之和）</i></span>
          <span>已核销 <b>{{ fmtAmt(instRec.written_off_amount) }}</b></span>
          <span class="hl">未核销余额 <b>{{ fmtAmt(instRec.balance_amount) }}</b></span>
        </div>
        <table class="data-table compact">
          <thead><tr><th>#</th><th class="amt">收付金额</th><th>收付日期</th><th>备注</th><th v-if="canCreate || canInstAction"></th></tr></thead>
          <tbody>
            <tr v-if="!instList.length"><td :colspan="(canCreate || canInstAction) ? 5 : 4" class="empty">暂无收付明细</td></tr>
            <tr v-for="i in instList" :key="i.id">
              <td>{{ i.install_no }}</td>
              <td class="amt" :style="{ color: parseFloat(i.amount) < 0 ? '#c62828' : 'inherit' }">{{ fmtAmt(i.amount) }}</td>
              <td>{{ i.occur_date }}</td>
              <td>{{ i.notes || '—' }}</td>
              <td v-if="canCreate || canInstAction"><button class="lnk danger" :disabled="instBusy" @click="delInstallment(i)">删除</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="canCreate || canInstAction" class="wo-add">
          <div class="wo-inputs">
            <input v-model="instForm.amount" type="number" step="0.01" class="inp" placeholder="收付金额(元，可负=退回)" />
            <input v-model="instForm.occur_date" type="date" class="inp" />
            <input v-model="instForm.notes" class="inp" placeholder="备注（如：第二笔预付款）" />
            <button class="btn btn-primary btn-sm" :disabled="instBusy" @click="addInstallment">{{ instBusy ? '…' : `＋ 新增${dirLabel}` }}</button>
          </div>
          <p style="font-size:11px;color:var(--muted);margin:6px 0 0">
            与应收的多次回款同构：同一笔{{ dirLabel }}业务可分多次到账/付出，总额与未核销余额自动派生；删除某笔会回退总额（低于已核销时拒绝，须先删核销）。
          </p>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showInstModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- ── create / edit supplier modal ── -->
    <div v-if="showSupplierModal" class="modal-mask" @click.self="showSupplierModal = false">
      <div class="modal sup-modal">
        <h3>{{ editSupplier ? '编辑' : '新增' }}供应商</h3>

        <!-- 名称 -->
        <div class="sf-row">
          <label class="sf-fld">
            <span class="sf-lbl">供应商名称 <em>*</em></span>
            <input v-model="supplierForm.name" class="inp" placeholder="应与预付往来单位名称完全一致" />
            <span class="sf-hint">系统按此名称精确匹配预付余额，请确保与账单一致</span>
          </label>
        </div>

        <!-- 类型 -->
        <div class="sf-row">
          <span class="sf-lbl">类型 <em>*</em></span>
          <div class="sup-type-row">
            <label class="sup-type-btn" :class="{ active: supplierForm.supplier_type === 'public' }">
              <input type="radio" v-model="supplierForm.supplier_type" value="public" />
              公共供应商
              <span class="sup-type-desc">归属某事业部</span>
            </label>
            <label class="sup-type-btn" :class="{ active: supplierForm.supplier_type === 'private' }">
              <input type="radio" v-model="supplierForm.supplier_type" value="private" />
              私有供应商
              <span class="sup-type-desc">绑定特定项目</span>
            </label>
          </div>
        </div>

        <!-- 归属（私有选项目，公共选事业部）+ 联系人 两列 -->
        <div class="sf-row sf-two">
          <label v-if="supplierForm.supplier_type === 'private'" class="sf-fld">
            <span class="sf-lbl">关联项目 <em>*</em></span>
            <div class="combo">
              <input v-model="supplierProjKeyword" class="inp" placeholder="搜索项目简称 / 编号…"
                     @focus="showSupplierProjList = true"
                     @input="onSupplierProjKeywordInput" @blur="onSupplierProjBlur" />
              <button v-if="supplierForm.project_id || supplierProjKeyword" type="button" class="combo-clear"
                      @mousedown.prevent="pickSupplierProject(null)">×</button>
              <ul v-if="showSupplierProjList" class="combo-list">
                <li v-for="p in supplierProjects" :key="p.id" class="combo-opt"
                    :class="{ on: supplierForm.project_id === p.id }"
                    @mousedown.prevent="pickSupplierProject(p)">
                  <span>{{ p.short_name }}</span><span class="combo-dept">{{ p.delivery_dept }}</span>
                </li>
                <li v-if="!supplierProjects.length" class="combo-opt muted">无匹配项目</li>
              </ul>
            </div>
          </label>
          <label v-else class="sf-fld">
            <span class="sf-lbl">归属事业部 <em>*</em></span>
            <select v-model="supplierForm.delivery_dept" class="sel">
              <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
            </select>
          </label>
          <label class="sf-fld">
            <span class="sf-lbl">联系人</span>
            <input v-model="supplierForm.contact" class="inp" placeholder="选填" />
          </label>
        </div>

        <!-- 备注 -->
        <div class="sf-row">
          <label class="sf-fld">
            <span class="sf-lbl">备注</span>
            <input v-model="supplierForm.notes" class="inp" placeholder="选填" />
          </label>
        </div>

        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showSupplierModal = false">取消</button>
          <button class="btn btn-primary" :disabled="supplierSaving" @click="saveSupplier">
            {{ supplierSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 导入预检弹窗 -->
  <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy" :readonly="true"
    @close="precheckResult = null" @apply="onPrecheckApply" />
</template>

<style scoped>
.topbar { display: flex; justify-content: space-between; margin-bottom: 10px; }
.dir-tabs { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; }
.dir-tab-sep { width: 1px; height: 24px; background: var(--border); margin: 0 4px; }
.dir-tab {
  padding: 7px 16px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--card); color: var(--muted); font-weight: 600; cursor: pointer; font-size: 13.5px;
}
.dir-tab.active { background: var(--primary); color: #fff; border-color: var(--primary); }

.kpi-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.kpi { flex: 1; min-width: 108px; background: var(--card); border: 1px solid var(--border); border-radius: 9px; padding: 8px 11px; }
.kpi-k { font-size: 11px; color: var(--muted); }
.kpi-v { font-size: 16px; font-weight: 800; color: var(--text); margin-top: 2px; line-height: 1.2; }
.kpi-sub { font-size: 11px; font-weight: 600; color: var(--muted); margin-left: 5px; }
.kpi.accent { background: rgba(201,99,66,.06); }
.kpi.accent .kpi-v { color: var(--primary); }
.kpi.warn .kpi-v { color: #c62828; }

.filter-row { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
.spacer { flex: 1; min-width: 8px; }
.proj-chip { padding: 5px 10px; border: 1px solid var(--primary); border-radius: 999px; background: rgba(var(--primary-rgb,255,138,76),0.1); color: var(--primary); font-size: 12px; cursor: pointer; white-space: nowrap; }
.proj-chip:hover { background: rgba(var(--primary-rgb,255,138,76),0.18); }
.sel, .inp { padding: 6px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--card); color: var(--text); font-size: 13px; }
.filter-row .sel, .filter-row .inp { width: auto; font-size: 12.5px; }
.sel.sm { padding: 5px 8px; font-size: 12.5px; }
.inp.sm { padding: 5px 9px; font-size: 12.5px; width: 240px; max-width: 100%; }
.btn.disabled { opacity: .6; pointer-events: none; }

.table-scroll { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 760px; }
.data-table.compact { min-width: 0; }
.data-table th, .data-table td { padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
.data-table thead th { color: var(--muted); font-weight: 700; font-size: 12px; background: rgba(180,140,110,.06); }
.data-table th.amt, .data-table td.amt { text-align: right; }
.data-table th.ctr, .data-table td.ctr { text-align: center; }
.num-strong { font-weight: 700; }
.bal-positive { color: var(--primary); }
.proj-name { font-weight: 600; }
.dept-tag { font-size: 11px; color: var(--muted); }
.empty { text-align: center; color: var(--muted); padding: 28px 0; }
.nowrap { white-space: nowrap; }

.status-pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 700; }
.pill-ok { background: rgba(46,125,50,.12); color: #2e7d32; }
.pill-blue { background: rgba(21,101,192,.12); color: #1565c0; }
.pill-muted { background: rgba(120,120,120,.1); color: var(--muted); }
.pill-danger { background: rgba(198,40,40,.12); color: #c62828; }

.lnk { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 13px; padding: 2px 6px; }
.lnk.danger { color: #c62828; }

.pager { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 14px; font-size: 13px; color: var(--muted); }

.modal-mask { position: fixed; inset: 0; background: rgba(20,10,5,0.42); backdrop-filter: blur(8px); display: flex; align-items: center; justify-content: center; z-index: 200; padding: 20px; }
.modal {
  background: rgba(255,252,248,0.97);
  border: 1px solid var(--glass-border);
  border-radius: 18px; padding: 22px 24px; width: 100%; max-width: 640px; max-height: 90vh; overflow-y: auto;
  box-shadow: 0 24px 80px rgba(100,60,30,0.28), 0 1px 0 rgba(255,255,255,0.8) inset;
}
.modal h3 { margin: 0 0 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.fld { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.fld.full { grid-column: 1 / -1; }
.fld span { color: var(--muted); }
.fld em { color: #c62828; font-style: normal; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }

/* project combobox */
.combo { position: relative; }
.combo .inp { width: 100%; padding-right: 28px; }
.combo-clear { position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  border: none; background: none; color: var(--muted); font-size: 18px; line-height: 1; cursor: pointer; padding: 0 4px; }
.combo-list {
  position: absolute; z-index: 10; top: calc(100% + 4px); left: 0; right: 0;
  background: #fff; border: 1px solid var(--border); border-radius: 9px;
  box-shadow: 0 10px 30px rgba(100,60,30,0.18); max-height: 220px; overflow-y: auto;
  list-style: none; margin: 0; padding: 4px;
}
.combo-opt { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 7px 9px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.combo-opt:hover { background: rgba(201,99,66,.08); }
.combo-opt.on { background: rgba(201,99,66,.12); font-weight: 600; }
.combo-opt.muted { color: var(--muted); }
.combo-dept { font-size: 11px; color: var(--muted); }

.wo-summary { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 12px; }
.wo-summary b { color: var(--text); }
.wo-summary .hl b { color: var(--primary); }
.wo-add { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); }
.wo-offset-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; background: rgba(201,99,66,0.05); border: 1px solid rgba(201,99,66,0.2); border-radius: 8px; padding: 7px 10px; }
.wo-offset-lbl { font-size: 12px; font-weight: 700; color: var(--primary); white-space: nowrap; }
.wo-offset-sel { flex: 1; min-width: 220px; }
.wo-offset-tip { font-size: 11px; color: var(--primary); opacity: 0.8; width: 100%; padding-left: 2px; }
.wo-inputs { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.offset-badge { display: inline-block; padding: 1px 7px; border-radius: 999px; background: rgba(27,110,53,0.1); color: #1b6e35; font-size: 11px; font-weight: 600; }
.offset-badge.pay-badge { background: rgba(21,101,192,0.1); color: #1565c0; }

/* supplier modal */
.sup-modal { max-width: 460px; }
.sf-row { margin-bottom: 14px; }
.sf-two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.sf-fld { display: flex; flex-direction: column; gap: 4px; }
.sf-lbl { font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.sf-lbl em { color: #c62828; font-style: normal; }
.sf-hint { font-size: 11px; color: var(--muted); }
.sup-type-row { display: flex; gap: 10px; margin-top: 6px; }
.sup-type-btn {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px;
  padding: 10px 8px; border: 1.5px solid var(--border); border-radius: 10px;
  cursor: pointer; font-size: 13px; font-weight: 600; text-align: center;
  transition: border-color 0.15s, background 0.15s;
}
.sup-type-btn input[type=radio] { display: none; }
.sup-type-btn.active { border-color: var(--primary); background: rgba(201,99,66,0.06); color: var(--primary); }
.sup-type-desc { font-size: 11px; font-weight: 400; color: var(--muted); }
.sup-type-btn.active .sup-type-desc { color: var(--primary); opacity: 0.75; }

/* ══ 预收/预付列表备注列：限宽省略，整表保持一页宽 ══ */
.adv-notes-col { width: 130px; }
.adv-notes-cell { max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted); font-size: 12px; }

/* ══ 收付差异（紧凑排版）══ */
.diff-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12.5px; }
.diff-table th { padding: 7px 10px; text-align: left; font-size: 11px; font-weight: 700; color: var(--muted);
  background: rgba(201,99,66,.05); border-bottom: 1px solid rgba(180,140,110,.15); white-space: nowrap; }
.diff-table td { padding: 6px 10px; border-bottom: 1px solid rgba(180,140,110,.08); vertical-align: middle; }
.dt-proj { width: 23%; }
.dt-amt { width: 14%; text-align: right !important; font-variant-numeric: tabular-nums; }
.dt-notes { width: 31%; }
.dt-caret { width: 4%; text-align: center; font-size: 10px; color: var(--muted); }
td.dt-proj { overflow: hidden; white-space: nowrap; }
.dt-name { font-weight: 700; color: var(--text); }
.dt-dept { font-size: 10.5px; color: var(--muted); background: rgba(120,120,120,.08);
  border-radius: 5px; padding: 1px 6px; margin-left: 6px; white-space: nowrap; }
td.dt-notes { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted); font-size: 11.5px; }
.diff-row { cursor: pointer; }
.diff-row:hover td { background: rgba(201,99,66,.04); }
.diff-row .fw { font-weight: 700; }
.diff-detail-row td { background: rgba(250,246,241,.7); padding: 6px 10px; }
.diff-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 760px) { .diff-detail { grid-template-columns: 1fr; } }
.dd-col { background: #fff; border: 1px solid rgba(180,140,110,.14); border-radius: 8px; padding: 5px 10px; }
.dd-head { font-size: 11px; font-weight: 700; margin-bottom: 2px; }
.dd-head.in { color: #2e7d32; } .dd-head.out { color: #ef6c00; }
.dd-empty { font-size: 11.5px; color: var(--muted); padding: 2px 0; }
.dd-item { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 2.5px 0;
  border-top: 1px dashed rgba(180,140,110,.12); line-height: 1.5; }
.dd-item:first-of-type { border-top: none; }
.dd-date { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 74px; }
.dd-amt { font-variant-numeric: tabular-nums; min-width: 78px; text-align: right; }
.dd-amt.in { color: #2e7d32; } .dd-amt.out { color: #ef6c00; }
.dd-party { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.dd-bal { font-style: normal; font-size: 10.5px; color: #1565c0; background: rgba(21,101,192,.07);
  border-radius: 5px; padding: 0 6px; white-space: nowrap; }
</style>
