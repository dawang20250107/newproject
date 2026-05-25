<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = 50
const activeTab = ref('reconciliation')
const filters = reactive({ dept: '', year: new Date().getFullYear(), month: '', status: '', q: '' })

const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const recForm = reactive({
  project_id: '', operation_year: new Date().getFullYear(), operation_month: new Date().getMonth() + 1,
  estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
  invoice_date: '', reconciliation_time: '', notes: '',
})

const projects = ref([])
const showPayModal = ref(false)
const payRec = ref(null)
const payForm = reactive({ amount: '', payment_date: '', notes: '' })
const paySaving = ref(false)
const expandedPayments = ref({})
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)

const accessibleDepts = computed(() =>
  auth.isSuperAdmin ? DEPARTMENTS : (auth.user?.departments || []).filter(d => DEPARTMENTS.includes(d)))
const years = Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const kpi = computed(() => {
  const overdue = items.value.filter(r => r.is_overdue).length
  const outstanding = items.value.reduce((s, r) => s + (parseFloat(r.outstanding_amount) || 0), 0)
  const invoiced = items.value.filter(r => r.invoice_date).length
  const settled = items.value.filter(r => r.invoice_status === '已结清').length
  return { overdue, outstanding, invoiced, settled }
})

function fmtAmt(v) {
  const n = parseFloat(v) || 0
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(2)
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const res = await ar.listRecords({ ...filters, include_payments: 1, page: page.value, size })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

async function loadProjects() {
  const res = await ar.listProjects({ size: 200 })
  projects.value = res.data.items
}

function openCreate() {
  editRec.value = null
  Object.assign(recForm, {
    project_id: projects.value[0]?.id || '',
    operation_year: new Date().getFullYear(), operation_month: new Date().getMonth() + 1,
    estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
    invoice_date: '', reconciliation_time: '', notes: '',
  })
  showModal.value = true
}

function openEdit(rec) {
  editRec.value = rec
  Object.assign(recForm, {
    project_id: rec.project_id, operation_year: rec.operation_year, operation_month: rec.operation_month,
    estimated_amount: rec.estimated_amount, actual_invoice_amount: rec.actual_invoice_amount || '',
    tax_amount: rec.tax_amount || '', invoice_date: rec.invoice_date || '',
    reconciliation_time: rec.reconciliation_time ? rec.reconciliation_time.slice(0, 16) : '',
    notes: rec.notes,
  })
  showModal.value = true
}

async function saveRec() {
  if (!recForm.project_id) { alert('请选择项目'); return }
  saving.value = true
  try {
    const payload = {
      project_id: recForm.project_id, operation_year: recForm.operation_year,
      operation_month: recForm.operation_month, estimated_amount: recForm.estimated_amount || 0,
      actual_invoice_amount: recForm.actual_invoice_amount || null,
      tax_amount: recForm.tax_amount || null, invoice_date: recForm.invoice_date || null,
      reconciliation_time: recForm.reconciliation_time || null, notes: recForm.notes,
    }
    if (editRec.value) await ar.updateRecord(editRec.value.id, payload)
    else await ar.createRecord(payload)
    showModal.value = false; await load()
  } catch (e) { alert(e?.response?.data?.msg || '保存失败')
  } finally { saving.value = false }
}

async function deleteRec(rec) {
  if (!confirm(`确定删除「${rec.short_name}」${rec.operation_year}年${rec.operation_month}月的应收记录？`)) return
  try { await ar.deleteRecord(rec.id); await load() }
  catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

function togglePayments(id) { expandedPayments.value[id] = !expandedPayments.value[id] }

function openAddPayment(rec) {
  payRec.value = rec
  Object.assign(payForm, { amount: '', payment_date: new Date().toISOString().slice(0, 10), notes: '' })
  showPayModal.value = true
}

async function savePayment() {
  if (!payForm.amount || !payForm.payment_date) { alert('金额和日期必填'); return }
  paySaving.value = true
  try {
    await ar.addPayment(payRec.value.id, payForm)
    showPayModal.value = false; await load()
  } catch (e) { alert(e?.response?.data?.msg || '保存失败')
  } finally { paySaving.value = false }
}

async function deletePayment(rec, pay) {
  if (!confirm(`确定删除第${pay.payment_no}次回款 ${pay.amount} 元？`)) return
  try { await ar.deletePayment(rec.id, pay.id); await load() }
  catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

async function downloadTemplate() {
  const res = await ar.recordTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '应收账款明细导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importRecords(fd); const d = res.data
    alert(`导入完成：创建 ${d.created}，更新 ${d.updated}，跳过 ${d.skipped}`)
    await load()
  } catch (e) { alert(e?.response?.data?.msg || '导入失败')
  } finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportRecords(filters)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '应收账款明细.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.response?.data?.msg || '导出失败')
  } finally { exporting.value = false }
}

onMounted(() => { load(); loadProjects() })
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>应收明细</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">对账跟踪 · 开票跟踪 · 回款跟踪</div>
      </div>
      <div class="ctrl-row" style="flex-wrap:wrap">
        <select v-model="filters.dept" class="sel-bu" @change="load(true)">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.year" class="sel-yr" @change="load(true)">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <select v-model="filters.month" class="sel-mo" @change="load(true)">
          <option value="">全月</option>
          <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
        </select>
        <select v-model="filters.status" class="sel-mo" @change="load(true)">
          <option value="">全部状态</option>
          <option value="overdue">逾期</option>
          <option value="current">当期</option>
          <option value="not_due">未到期</option>
          <option value="settled">已结清</option>
        </select>
        <input v-model="filters.q" placeholder="搜索项目" class="search-input" @input="load(true)" />
      </div>
    </div>

    <!-- KPI strip -->
    <div class="kpi-strip">
      <div class="kpi-pill kpi-danger">
        <div class="kpi-num">{{ kpi.overdue }}</div>
        <div class="kpi-label">逾期</div>
      </div>
      <div class="kpi-pill kpi-warn">
        <div class="kpi-num">{{ fmtAmt(kpi.outstanding) }}</div>
        <div class="kpi-label">未回款</div>
      </div>
      <div class="kpi-pill kpi-ok">
        <div class="kpi-num">{{ kpi.settled }}</div>
        <div class="kpi-label">已结清</div>
      </div>
      <div class="strip-actions">
        <button class="act-btn" @click="downloadTemplate">↓ 模板</button>
        <label class="act-btn" style="cursor:pointer">
          {{ importing ? '导入中…' : '↑ 导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" />
        </label>
        <button class="act-btn" :disabled="exporting" @click="exportData">{{ exporting ? '…' : '↓ 导出' }}</button>
        <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增</button>
      </div>
    </div>

    <!-- Tab + table card -->
    <div class="card">
      <!-- Segment tab control -->
      <div class="segment-ctrl">
        <button :class="['seg-btn', activeTab === 'reconciliation' ? 'active' : '']" @click="activeTab = 'reconciliation'">
          <span class="seg-dot"></span>对账跟踪
        </button>
        <button :class="['seg-btn', activeTab === 'invoice' ? 'active' : '']" @click="activeTab = 'invoice'">
          <span class="seg-dot"></span>开票跟踪
        </button>
        <button :class="['seg-btn', activeTab === 'collection' ? 'active' : '']" @click="activeTab = 'collection'">
          <span class="seg-dot"></span>回款跟踪
        </button>
      </div>

      <div class="table-wrap" style="margin-top:0">
        <table class="rec-table">
          <thead>
            <tr>
              <th>项目</th>
              <th class="ctr">年月</th>
              <template v-if="activeTab === 'reconciliation'">
                <th class="amt">预估金额</th>
                <th class="ctr">对账状态</th>
                <th class="ctr">对账时间</th>
                <th class="ctr">应收到期</th>
                <th class="amt">未收金额</th>
                <th class="ctr">状态</th>
              </template>
              <template v-else-if="activeTab === 'invoice'">
                <th class="amt">预估金额</th>
                <th class="amt">实际开票额</th>
                <th class="amt">税额</th>
                <th class="ctr">开票日期</th>
                <th class="ctr">开票模式</th>
                <th class="amt">账实差额</th>
                <th class="ctr">开票状态</th>
              </template>
              <template v-else>
                <th class="amt">应收基础</th>
                <th>回款记录</th>
                <th class="amt">未收金额</th>
                <th class="ctr">回款状态</th>
              </template>
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td :colspan="activeTab === 'invoice' ? 10 : 9" class="empty-cell">⏳ 加载中…</td>
            </tr>
            <tr v-else-if="!items.length">
              <td :colspan="activeTab === 'invoice' ? 10 : 9" class="empty-cell">暂无数据</td>
            </tr>
            <template v-for="rec in items" :key="rec.id">
              <tr :class="['data-row', rec.is_overdue ? 'row-overdue' : '']">
                <td>
                  <div class="proj-name">{{ rec.short_name || rec.contract_name }}</div>
                  <div class="proj-no">{{ rec.project_no }}</div>
                </td>
                <td class="ctr">
                  <span class="ym-chip">{{ rec.operation_year }}/{{ String(rec.operation_month).padStart(2,'0') }}</span>
                </td>

                <!-- Reconciliation -->
                <template v-if="activeTab === 'reconciliation'">
                  <td class="amt fw">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td class="ctr">
                    <span :class="['status-pill', rec.reconciliation_status === '已对账' ? 'pill-ok' : 'pill-warn']">
                      {{ rec.reconciliation_status }}
                    </span>
                  </td>
                  <td class="ctr text-sm-muted">{{ rec.reconciliation_time ? rec.reconciliation_time.slice(0,10) : '—' }}</td>
                  <td class="ctr text-sm-muted">{{ rec.due_date || '—' }}</td>
                  <td class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">
                    {{ parseFloat(rec.outstanding_amount) > 0 ? fmtAmt(rec.outstanding_amount) : '—' }}
                  </td>
                  <td class="ctr">
                    <span v-if="rec.is_overdue" class="status-pill pill-danger">逾期 {{ rec.overdue_days }}天</span>
                    <span v-else-if="rec.is_current" class="status-pill pill-blue">当期</span>
                    <span v-else-if="rec.invoice_status === '已结清'" class="status-pill pill-ok">已结清</span>
                    <span v-else class="status-pill pill-muted">未到期</span>
                  </td>
                </template>

                <!-- Invoice -->
                <template v-else-if="activeTab === 'invoice'">
                  <td class="amt text-muted">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td class="amt fw">{{ rec.actual_invoice_amount ? fmtAmt(rec.actual_invoice_amount) : '—' }}</td>
                  <td class="amt text-muted">{{ rec.tax_amount ? fmtAmt(rec.tax_amount) : '—' }}</td>
                  <td class="ctr text-sm-muted">{{ rec.invoice_date || '—' }}</td>
                  <td class="ctr">
                    <span class="mode-tag">{{ rec.invoice_mode }}</span>
                  </td>
                  <td class="amt" :class="parseFloat(rec.account_diff_adjustment) !== 0 ? 'amt-warn' : 'amt-zero'">
                    {{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtAmt(rec.account_diff_adjustment) : '—' }}
                  </td>
                  <td class="ctr">
                    <span :class="['status-pill',
                      rec.invoice_status === '已结清' ? 'pill-ok' :
                      rec.invoice_status === '部分回款' ? 'pill-blue' :
                      rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">
                      {{ rec.invoice_status }}
                    </span>
                  </td>
                </template>

                <!-- Collection -->
                <template v-else>
                  <td class="amt fw">{{ fmtAmt(rec.actual_invoice_amount || rec.estimated_amount) }}</td>
                  <td>
                    <button class="pay-toggle" @click="togglePayments(rec.id)">
                      <span class="pay-count" :class="rec.payments?.length ? 'count-has' : 'count-none'">{{ rec.payments?.length || 0 }}</span>
                      <span style="font-size:12px;color:var(--muted)">{{ rec.payments?.length ? '笔回款' : '无回款' }}</span>
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="margin-left:3px;color:var(--muted)" :style="expandedPayments[rec.id] ? 'transform:rotate(180deg)' : ''"><path d="M6 9l6 6 6-6"/></svg>
                    </button>
                    <button v-if="auth.canCreate" class="add-pay-btn" @click="openAddPayment(rec)">+ 回款</button>
                  </td>
                  <td class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">
                    {{ parseFloat(rec.outstanding_amount) > 0 ? fmtAmt(rec.outstanding_amount) : '—' }}
                  </td>
                  <td class="ctr">
                    <span :class="['status-pill',
                      rec.invoice_status === '已结清' ? 'pill-ok' :
                      rec.invoice_status === '部分回款' ? 'pill-blue' :
                      rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">
                      {{ rec.invoice_status }}
                    </span>
                  </td>
                </template>

                <td class="ctr">
                  <div class="row-acts">
                    <button class="icon-btn" @click="openEdit(rec)" title="编辑">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4z"/></svg>
                    </button>
                    <button v-if="auth.canDelete" class="icon-btn icon-btn-del" @click="deleteRec(rec)" title="删除">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- Payment detail rows -->
              <template v-if="activeTab === 'collection' && expandedPayments[rec.id]">
                <tr v-if="!rec.payments?.length" class="pay-row">
                  <td colspan="6" class="pay-empty">暂无回款记录</td>
                </tr>
                <tr v-else v-for="pay in rec.payments" :key="pay.id" class="pay-row">
                  <td colspan="2"></td>
                  <td colspan="2">
                    <div class="pay-detail">
                      <span class="pay-no">第{{ pay.payment_no }}次</span>
                      <span class="pay-amt">{{ fmtAmt(pay.amount) }}</span>
                      <span class="pay-date">{{ pay.payment_date }}</span>
                      <span v-if="pay.notes" class="pay-notes">{{ pay.notes }}</span>
                    </div>
                  </td>
                  <td colspan="2" class="ctr">
                    <button v-if="auth.canDelete" class="icon-btn icon-btn-del" @click="deletePayment(rec, pay)" title="删除回款">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </td>
                </tr>
              </template>
            </template>
          </tbody>
        </table>
      </div>

      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">{{ page }} / {{ Math.ceil(total / size) }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
      </div>
    </div>

    <!-- AR Record Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:560px">
          <div class="modal-header">
            <h3>{{ editRec ? '编辑应收记录' : '新增应收记录' }}</h3>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2">
                <span>关联项目 <em>*</em></span>
                <select v-model="recForm.project_id" :disabled="!!editRec">
                  <option value="" disabled>请选择项目</option>
                  <option v-for="p in projects" :key="p.id" :value="p.id">
                    {{ p.project_no }} · {{ p.short_name || p.contract_name }}
                  </option>
                </select>
              </label>
              <label class="form-field">
                <span>运作年 <em>*</em></span>
                <select v-model.number="recForm.operation_year" :disabled="!!editRec">
                  <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>运作月 <em>*</em></span>
                <select v-model.number="recForm.operation_month" :disabled="!!editRec">
                  <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
                </select>
              </label>
              <label class="form-field">
                <span>预估上账金额</span>
                <input v-model="recForm.estimated_amount" type="number" step="0.01" />
              </label>
              <label class="form-field">
                <span>实际开票金额</span>
                <input v-model="recForm.actual_invoice_amount" type="number" step="0.01" placeholder="开票后填写" />
              </label>
              <label class="form-field">
                <span>税额（差额模式手填）</span>
                <input v-model="recForm.tax_amount" type="number" step="0.01" placeholder="全额模式自动计算" />
              </label>
              <label class="form-field">
                <span>开票日期</span>
                <input v-model="recForm.invoice_date" type="date" />
              </label>
              <label class="form-field">
                <span>对账时间</span>
                <input v-model="recForm.reconciliation_time" type="datetime-local" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="recForm.notes" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="saveRec">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>

      <!-- Payment Modal -->
      <div v-if="showPayModal" class="modal-overlay" @click.self="showPayModal = false">
        <div class="modal-box" style="max-width:400px">
          <div class="modal-header">
            <div>
              <h3>录入回款</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">{{ payRec?.short_name || payRec?.contract_name }}</div>
            </div>
            <button class="modal-close" @click="showPayModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2">
                <span>回款金额 <em>*</em></span>
                <input v-model="payForm.amount" type="number" step="0.01" autofocus />
              </label>
              <label class="form-field span2">
                <span>回款日期 <em>*</em></span>
                <input v-model="payForm.payment_date" type="date" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="payForm.notes" placeholder="可选" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showPayModal = false">取消</button>
            <button class="btn btn-primary" :disabled="paySaving" @click="savePayment">{{ paySaving ? '保存中…' : '保存回款' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* KPI strip */
.kpi-strip { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
.kpi-pill {
  display: flex; align-items: baseline; gap: 6px;
  padding: 8px 16px; border-radius: 10px;
  background: rgba(255,255,255,0.7); border: 1px solid rgba(255,255,255,0.8);
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
.kpi-danger { border-left: 3px solid #c62828; }
.kpi-warn   { border-left: 3px solid #f57f17; }
.kpi-ok     { border-left: 3px solid #2e7d32; }
.kpi-num { font-size: 20px; font-weight: 700; color: var(--text); }
.kpi-label { font-size: 12px; color: var(--muted); }
.kpi-danger .kpi-num { color: #c62828; }
.kpi-warn .kpi-num   { color: #e65100; }
.kpi-ok .kpi-num     { color: #2e7d32; }

.strip-actions { display: flex; gap: 6px; align-items: center; margin-left: auto; flex-wrap: wrap; }
.act-btn {
  padding: 6px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 500;
  border: 1px solid var(--border); background: rgba(255,252,250,0.8); color: var(--muted);
  cursor: pointer; transition: all 0.14s; white-space: nowrap;
}
.act-btn:hover { border-color: var(--primary); color: var(--primary); }
.act-btn:disabled { opacity: 0.4; cursor: default; }

/* Segment control */
.segment-ctrl {
  display: inline-flex; gap: 0; padding: 4px;
  background: rgba(0,0,0,0.04); border-radius: 12px;
  margin-bottom: 16px;
}
.seg-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 18px; border-radius: 9px; border: none;
  font-size: 13px; font-weight: 500; color: var(--muted);
  background: transparent; cursor: pointer; transition: all 0.18s;
}
.seg-btn .seg-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(155,128,112,0.3); transition: all 0.18s;
}
.seg-btn.active {
  background: white; color: var(--primary); font-weight: 700;
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}
.seg-btn.active .seg-dot { background: var(--primary); box-shadow: 0 0 6px rgba(201,99,66,0.5); }

/* Table */
.rec-table { width: 100%; }
.rec-table th { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); padding: 9px 12px; background: rgba(0,0,0,0.02); }
.rec-table td { padding: 10px 12px; vertical-align: middle; }
.data-row { transition: background 0.12s; }
.data-row:hover { background: rgba(201,99,66,0.03); }
.data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.04); }
.row-overdue { background: rgba(198,40,40,0.03) !important; }

.empty-cell { text-align: center; padding: 48px !important; color: var(--muted); font-size: 14px; }
.proj-name { font-weight: 600; font-size: 13.5px; }
.proj-no { font-family: monospace; font-size: 11px; color: var(--muted); margin-top: 2px; }
.ym-chip { font-size: 12px; font-weight: 600; color: var(--muted); background: rgba(0,0,0,0.05); padding: 2px 8px; border-radius: 6px; white-space: nowrap; }
.ctr { text-align: center; }
.amt { text-align: right; }
.fw { font-weight: 700; }
.text-muted { color: var(--muted); }
.text-sm-muted { font-size: 12px; color: var(--muted); }
.amt-warn { color: #e65100; font-weight: 700; }
.amt-zero { color: var(--muted); }
.mode-tag { font-size: 11.5px; padding: 2px 8px; border-radius: 8px; background: rgba(0,0,0,0.05); color: var(--muted); font-weight: 500; }

/* Status pills */
.status-pill { font-size: 11.5px; padding: 3px 9px; border-radius: 20px; font-weight: 600; white-space: nowrap; }
.pill-ok     { background: rgba(46,125,50,0.1);  color: #2e7d32; }
.pill-warn   { background: rgba(245,127,23,0.12); color: #e65100; }
.pill-danger { background: rgba(198,40,40,0.1);  color: #c62828; }
.pill-blue   { background: rgba(21,101,192,0.1); color: #1565c0; }
.pill-muted  { background: rgba(0,0,0,0.06);     color: var(--muted); }

/* Payment rows */
.pay-toggle {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px; border-radius: 7px; border: 1px solid var(--border);
  background: rgba(255,252,250,0.8); cursor: pointer; transition: all 0.14s; font-size: 12.5px;
}
.pay-toggle:hover { border-color: var(--primary); }
.pay-count { font-weight: 700; font-size: 14px; }
.count-has { color: var(--primary); }
.count-none { color: var(--muted); }
.add-pay-btn {
  margin-left: 6px; padding: 3px 8px; border-radius: 7px; border: 1px dashed var(--primary);
  background: rgba(201,99,66,0.05); color: var(--primary); font-size: 12px; cursor: pointer; transition: all 0.14s;
}
.add-pay-btn:hover { background: rgba(201,99,66,0.12); }
.pay-row { background: linear-gradient(90deg, rgba(201,99,66,0.03), transparent 40%); }
.pay-row td { padding: 6px 12px; border-bottom: 1px solid rgba(0,0,0,0.03); }
.pay-detail { display: flex; align-items: center; gap: 10px; }
.pay-no   { font-size: 11px; color: var(--muted); background: rgba(0,0,0,0.05); padding: 1px 6px; border-radius: 5px; }
.pay-amt  { font-weight: 700; color: #2e7d32; font-size: 13.5px; }
.pay-date { font-size: 12px; color: var(--muted); }
.pay-notes { font-size: 12px; color: var(--muted); font-style: italic; }
.pay-empty { text-align: center; padding: 10px !important; color: var(--muted); font-size: 12px; }

.row-acts { display: flex; gap: 4px; justify-content: center; }
.icon-btn {
  width: 26px; height: 26px; border-radius: 6px; border: 1px solid var(--border);
  background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center;
  color: var(--muted); cursor: pointer; transition: all 0.13s;
}
.icon-btn:hover { border-color: var(--primary); color: var(--primary); }
.icon-btn-del:hover { border-color: var(--danger); color: var(--danger); background: rgba(198,40,40,0.07); }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; }
.page-btn { padding: 5px 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,252,250,0.7); color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.14s; }
.page-btn:hover { border-color: var(--primary); color: var(--primary); }
.page-btn:disabled { opacity: 0.35; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }
.search-input { padding: 7px 12px; border: 1px solid var(--border); border-radius: 9px; font-size: 13px; min-width: 160px; background: rgba(255,252,250,0.8); }
</style>
