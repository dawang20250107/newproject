<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'

const auth = useAuthStore()
const route = useRoute()

const direction = ref('预收')          // 预收 / 预付
// 来自应收回款页的联动跳转：?project_id=&direction= → 预筛某项目的预收/预付
const projectFilter = ref(null)        // { id, label } or null
const items = ref([])
const total = ref(0)
const kpi = ref(null)
const loading = ref(false)
const page = ref(1)
const size = 50

const filters = reactive({ dept: '', year: '', month: '', writeoff_status: '', q: '' })

const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const fmtAmt = (v) => fmtCompact(v, { dash: '0.00' })

const show = k => auth.canArView(k)
const canCreate = computed(() => auth.canCreate)
const canDelete = computed(() => auth.canDelete)

const isReceive = computed(() => direction.value === '预收')
const dirLabel = computed(() => isReceive.value ? '预收' : '预付')
const partyLabel = computed(() => isReceive.value ? '客户' : '供应商')

const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)

async function load(reset = false) {
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
  load(true)
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
  if (!projectKeyword.value.trim()) form.project_id = ''  // cleared text → unlink
  clearTimeout(projectTimer)
  projectTimer = setTimeout(() => searchProjects(projectKeyword.value.trim()), 220)
}
let autoCounterparty = ''   // 上次按项目自动带出的客户名，用于判断可否覆盖
function pickProject(p) {
  if (p) {
    form.project_id = p.id
    form.delivery_dept = p.delivery_dept
    projectKeyword.value = `${p.short_name}（${p.delivery_dept}）`
    // 预收：往来单位 = 客户，自动带出项目客户名（未手填或仍是上次自动值时才覆盖）
    if (isReceive.value && p.customer_name &&
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
// 预收核销可选「冲抵某条应收明细」→ 自动生成预收抵扣回款
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
  // 挂项目→按项目；散单→按客户名匹配应收明细
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
    // refresh the in-modal record balance
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

// ── template / import / export ────────────────────────────────────────────────
async function downloadTemplate() {
  const res = await ar.advanceTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '预收预付导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}
async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importAdvances(fd); const d = res.data
    let parts = [`导入完成：创建 ${d.created}，跳过 ${d.skipped}`]
    if (d.errors?.length) parts.push(`\n以下行未通过校验：\n` + d.errors.join('\n'))
    alert(parts.join('\n'))
    await load()
  } catch (e) { alert(e?.msg || '导入失败') }
  finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}
async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportAdvances({ direction: direction.value, ...filters })
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = `${dirLabel.value}明细.xlsx`; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.msg || '导出失败') }
  finally { exporting.value = false }
}

function woStatusClass(s) {
  return s === '已核销' ? 'pill-ok' : s === '部分核销' ? 'pill-blue' : 'pill-muted'
}

function clearProjectFilter() { projectFilter.value = null; load(true) }

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
      <select v-if="accessibleDepts.length > 1" v-model="filters.dept" class="sel" @change="onFilterChange">
        <option value="">全部部门</option>
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
    </div>

    <!-- direction tabs -->
    <div class="dir-tabs">
      <button :class="['dir-tab', { active: direction === '预收' }]" @click="switchDir('预收')">预收（客户预付款）</button>
      <button :class="['dir-tab', { active: direction === '预付' }]" @click="switchDir('预付')">预付（付供应商）</button>
    </div>

    <!-- KPI -->
    <div v-if="kpi" class="kpi-row">
      <div class="kpi"><div class="kpi-k">{{ dirLabel }}笔数</div><div class="kpi-v">{{ kpi.count }} 笔</div></div>
      <div v-if="show('adv_amount')" class="kpi"><div class="kpi-k">{{ dirLabel }}金额</div><div class="kpi-v">{{ fmtAmt(kpi.advance_amount) }}</div></div>
      <div v-if="show('adv_writeoff')" class="kpi"><div class="kpi-k">已核销</div><div class="kpi-v">{{ fmtAmt(kpi.written_off) }}<span class="kpi-sub">{{ kpi.writeoff_rate }}%</span></div></div>
      <div v-if="show('adv_writeoff')" class="kpi accent"><div class="kpi-k">未核销余额</div><div class="kpi-v">{{ fmtAmt(kpi.balance) }}</div></div>
      <div v-if="show('adv_writeoff')" class="kpi warn"><div class="kpi-k">逾期挂账</div><div class="kpi-v">{{ fmtAmt(kpi.overdue_balance) }}<span class="kpi-sub">{{ kpi.overdue_count }} 笔</span></div></div>
    </div>

    <!-- filters + toolbar -->
    <div class="card">
      <div class="filter-row">
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
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!loading && !items.length"><td colspan="10" class="empty">暂无{{ dirLabel }}记录</td></tr>
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
              <td class="ctr nowrap">
                <button v-if="show('adv_writeoff') && canCreate" class="lnk" @click="openWriteoffs(r)">核销</button>
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

    <!-- create / edit modal -->
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

    <!-- writeoff modal -->
    <div v-if="showWoModal" class="modal-mask" @click.self="showWoModal = false">
      <div class="modal">
        <h3>核销 · {{ woRec.counterparty }}</h3>
        <div class="wo-summary">
          <span>{{ dirLabel }}金额 <b>{{ fmtAmt(woRec.advance_amount) }}</b></span>
          <span>已核销 <b>{{ fmtAmt(woRec.written_off_amount) }}</b></span>
          <span class="hl">未核销余额 <b>{{ fmtAmt(woRec.balance_amount) }}</b></span>
        </div>
        <table class="data-table compact">
          <thead><tr><th>#</th><th class="amt">核销金额</th><th>核销日期</th><th>冲抵应收</th><th>备注</th><th v-if="canDelete"></th></tr></thead>
          <tbody>
            <tr v-if="!woList.length"><td :colspan="canDelete ? 6 : 5" class="empty">暂无核销记录</td></tr>
            <tr v-for="w in woList" :key="w.id">
              <td>{{ w.writeoff_no }}</td>
              <td class="amt">{{ fmtAmt(w.amount) }}</td>
              <td>{{ w.writeoff_date }}</td>
              <td><span v-if="w.ar_record_id" class="offset-badge" :title="`已生成预收抵扣回款 · ${w.ar_project_no || ''}`">↳ 转回款</span><span v-else>—</span></td>
              <td>{{ w.notes || '—' }}</td>
              <td v-if="canDelete"><button class="lnk danger" @click="delWriteoff(w)">删除</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="canCreate" class="wo-add">
          <input v-model="woForm.amount" type="number" step="0.01" class="inp" placeholder="核销金额(元)" />
          <input v-model="woForm.writeoff_date" type="date" class="inp" />
          <input v-model="woForm.notes" class="inp" placeholder="备注" />
          <button class="btn btn-primary btn-sm" :disabled="woSaving" @click="addWriteoff">{{ woSaving ? '…' : '新增核销' }}</button>
        </div>
        <div v-if="canCreate && canOffset" class="wo-offset">
          <label class="wo-offset-lbl">以本次核销冲抵应收（生成「预收抵扣」回款，自动冲减未收）：</label>
          <select v-model="woForm.ar_record_id" class="inp">
            <option value="">不冲抵（仅登记核销）</option>
            <option v-for="o in woOffsetRecords" :key="o.id" :value="o.id">{{ o.label }}</option>
          </select>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showWoModal = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.topbar { display: flex; justify-content: space-between; margin-bottom: 10px; }
.dir-tabs { display: flex; gap: 8px; margin-bottom: 10px; }
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
/* override global `input,select{width:100%}` so filters are small boxes, not full-width bars */
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
.wo-add { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); }
.wo-offset { margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }
.wo-offset-lbl { font-size: 12px; color: var(--muted); }
.wo-offset .inp { width: 100%; }
.offset-badge { display: inline-block; padding: 1px 7px; border-radius: 999px; background: rgba(27,110,53,0.1); color: #1b6e35; font-size: 11px; font-weight: 600; }
</style>
