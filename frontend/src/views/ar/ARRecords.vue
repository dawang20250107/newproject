<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'
import ARStatusBadge from '../../components/ar/ARStatusBadge.vue'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = 50
const activeTab = ref('reconciliation')  // reconciliation | invoice | collection
const filters = reactive({ dept: '', year: new Date().getFullYear(), month: '', status: '', invoice_status: '', reconciliation_status: '', q: '' })

// Record modal
const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const recForm = reactive({
  project_id: '', operation_year: new Date().getFullYear(), operation_month: new Date().getMonth() + 1,
  estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
  invoice_date: '', reconciliation_time: '', notes: '',
})

// Projects for picker
const projects = ref([])
const projLoading = ref(false)

// Payment modal
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
    const res = await ar.listRecords({
      ...filters, include_payments: 1, page: page.value, size,
    })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

async function loadProjects() {
  projLoading.value = true
  try {
    const res = await ar.listProjects({ size: 200 })
    projects.value = res.data.items
  } finally { projLoading.value = false }
}

function openCreate() {
  editRec.value = null
  Object.assign(recForm, {
    project_id: projects.value[0]?.id || '', operation_year: new Date().getFullYear(),
    operation_month: new Date().getMonth() + 1, estimated_amount: '',
    actual_invoice_amount: '', tax_amount: '', invoice_date: '', reconciliation_time: '', notes: '',
  })
  showModal.value = true
}

function openEdit(rec) {
  editRec.value = rec
  Object.assign(recForm, {
    project_id: rec.project_id,
    operation_year: rec.operation_year, operation_month: rec.operation_month,
    estimated_amount: rec.estimated_amount,
    actual_invoice_amount: rec.actual_invoice_amount || '',
    tax_amount: rec.tax_amount || '',
    invoice_date: rec.invoice_date || '',
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
      project_id: recForm.project_id,
      operation_year: recForm.operation_year,
      operation_month: recForm.operation_month,
      estimated_amount: recForm.estimated_amount || 0,
      actual_invoice_amount: recForm.actual_invoice_amount || null,
      tax_amount: recForm.tax_amount || null,
      invoice_date: recForm.invoice_date || null,
      reconciliation_time: recForm.reconciliation_time || null,
      notes: recForm.notes,
    }
    if (editRec.value) {
      await ar.updateRecord(editRec.value.id, payload)
    } else {
      await ar.createRecord(payload)
    }
    showModal.value = false
    await load()
  } catch (e) {
    alert(e?.response?.data?.msg || '保存失败')
  } finally { saving.value = false }
}

async function deleteRec(rec) {
  if (!confirm(`确定删除「${rec.short_name}」${rec.operation_year}年${rec.operation_month}月的应收记录？`)) return
  try {
    await ar.deleteRecord(rec.id)
    await load()
  } catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

function togglePayments(id) {
  expandedPayments.value[id] = !expandedPayments.value[id]
}

function openAddPayment(rec) {
  payRec.value = rec
  Object.assign(payForm, { amount: '', payment_date: '', notes: '' })
  showPayModal.value = true
}

async function savePayment() {
  if (!payForm.amount || !payForm.payment_date) { alert('金额和日期必填'); return }
  paySaving.value = true
  try {
    await ar.addPayment(payRec.value.id, payForm)
    showPayModal.value = false
    await load()
  } catch (e) {
    alert(e?.response?.data?.msg || '保存失败')
  } finally { paySaving.value = false }
}

async function deletePayment(rec, pay) {
  if (!confirm(`确定删除第${pay.payment_no}次回款 ${pay.amount} 元？`)) return
  try {
    await ar.deletePayment(rec.id, pay.id)
    await load()
  } catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

async function downloadTemplate() {
  const res = await ar.recordTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '应收账款明细导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}

async function handleImport(e) {
  const f = e.target.files?.[0]
  if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importRecords(fd)
    const d = res.data
    alert(`导入完成：创建 ${d.created}，更新 ${d.updated}，跳过 ${d.skipped}${d.errors?.length ? `，错误 ${d.errors.length} 条` : ''}`)
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
      <h1>应收明细</h1>
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
        <div class="ctrl-sep"></div>
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate">下载模板</button>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer">
          {{ importing ? '导入中…' : '导入Excel' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" />
        </label>
        <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">{{ exporting ? '导出中…' : '导出Excel' }}</button>
        <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增</button>
      </div>
    </div>

    <!-- Tracking tabs -->
    <div class="card" style="padding-bottom:4px">
      <div class="tab-bar">
        <button :class="['tab-btn', activeTab === 'reconciliation' ? 'active' : '']" @click="activeTab = 'reconciliation'">对账跟踪</button>
        <button :class="['tab-btn', activeTab === 'invoice' ? 'active' : '']" @click="activeTab = 'invoice'">开票跟踪</button>
        <button :class="['tab-btn', activeTab === 'collection' ? 'active' : '']" @click="activeTab = 'collection'">回款跟踪</button>
      </div>

      <div class="table-wrap" style="margin-top:8px">
        <table>
          <thead>
            <tr>
              <th>项目简称</th>
              <th>年月</th>
              <!-- Reconciliation tab -->
              <template v-if="activeTab === 'reconciliation'">
                <th class="amt">预估金额</th>
                <th>对账状态</th>
                <th>对账时间</th>
                <th>应收日期</th>
                <th class="amt">未收金额</th>
                <th>状态</th>
              </template>
              <!-- Invoice tab -->
              <template v-else-if="activeTab === 'invoice'">
                <th class="amt">预估金额</th>
                <th class="amt">实际开票额</th>
                <th class="amt">税额</th>
                <th>开票日期</th>
                <th>开票模式</th>
                <th class="amt">账实差额</th>
                <th>开票状态</th>
              </template>
              <!-- Collection tab -->
              <template v-else>
                <th class="amt">应收基础</th>
                <th>回款记录</th>
                <th class="amt">未收金额</th>
                <th>回款状态</th>
              </template>
              <th style="width:100px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td colspan="12" style="text-align:center;padding:40px;color:var(--muted)">加载中…</td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="12" style="text-align:center;padding:40px;color:var(--muted)">暂无数据</td>
            </tr>
            <template v-for="rec in items" :key="rec.id">
              <tr :class="{ 'data-reloading': loading, 'row-overdue': rec.is_overdue }">
                <td>
                  <span class="proj-name">{{ rec.short_name || rec.contract_name }}</span>
                  <div class="proj-no">{{ rec.project_no }}</div>
                </td>
                <td>{{ rec.operation_year }}年{{ rec.operation_month }}月</td>

                <!-- Reconciliation -->
                <template v-if="activeTab === 'reconciliation'">
                  <td class="amt">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td><span :class="rec.reconciliation_status === '已对账' ? 'badge badge-ok' : 'badge badge-warn'">{{ rec.reconciliation_status }}</span></td>
                  <td>{{ rec.reconciliation_time ? rec.reconciliation_time.slice(0,10) : '—' }}</td>
                  <td>{{ rec.due_date || '—' }}</td>
                  <td class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'text-warn' : ''">{{ fmtAmt(rec.outstanding_amount) }}</td>
                  <td><ARStatusBadge v-bind="rec" /></td>
                </template>

                <!-- Invoice -->
                <template v-else-if="activeTab === 'invoice'">
                  <td class="amt">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td class="amt">{{ rec.actual_invoice_amount ? fmtAmt(rec.actual_invoice_amount) : '—' }}</td>
                  <td class="amt">{{ rec.tax_amount ? fmtAmt(rec.tax_amount) : '—' }}</td>
                  <td>{{ rec.invoice_date || '—' }}</td>
                  <td>{{ rec.invoice_mode }}</td>
                  <td class="amt">{{ fmtAmt(rec.account_diff_adjustment) }}</td>
                  <td><ARStatusBadge :invoice-status="rec.invoice_status" /></td>
                </template>

                <!-- Collection -->
                <template v-else>
                  <td class="amt">{{ fmtAmt(rec.actual_invoice_amount || rec.estimated_amount) }}</td>
                  <td>
                    <button class="btn-link" @click="togglePayments(rec.id)">
                      {{ rec.payments?.length ? `${rec.payments.length}笔回款` : '无回款' }}
                      {{ expandedPayments[rec.id] ? '▲' : '▼' }}
                    </button>
                    <button v-if="auth.canCreate" class="btn-link" style="margin-left:6px" @click="openAddPayment(rec)">+ 添加</button>
                  </td>
                  <td class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'text-warn' : ''">{{ fmtAmt(rec.outstanding_amount) }}</td>
                  <td><ARStatusBadge :invoice-status="rec.invoice_status" v-bind="rec" /></td>
                </template>

                <td>
                  <button class="btn-link" @click="openEdit(rec)">编辑</button>
                  <span v-if="auth.canDelete"> · </span>
                  <button v-if="auth.canDelete" class="btn-link btn-link-danger" @click="deleteRec(rec)">删除</button>
                </td>
              </tr>
              <!-- Payment rows (collection tab) -->
              <tr v-if="activeTab === 'collection' && expandedPayments[rec.id] && rec.payments?.length"
                  v-for="pay in rec.payments" :key="pay.id" class="payment-row">
                <td colspan="2"></td>
                <td class="amt muted">第{{ pay.payment_no }}次</td>
                <td colspan="2" style="font-size:12px;color:var(--muted)">
                  <b>{{ fmtAmt(pay.amount) }}</b> · {{ pay.payment_date }}
                  <span v-if="pay.notes"> · {{ pay.notes }}</span>
                </td>
                <td colspan="2">
                  <button v-if="auth.canDelete" class="btn-link btn-link-danger" style="font-size:12px" @click="deletePayment(rec, pay)">删除</button>
                </td>
                <td></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" @click="page--; load()">上一页</button>
        <span>第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" @click="page++; load()">下一页</button>
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
            <button class="btn btn-primary" :disabled="saving" @click="saveRec">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Payment Modal -->
      <div v-if="showPayModal" class="modal-overlay" @click.self="showPayModal = false">
        <div class="modal-box" style="max-width:400px">
          <div class="modal-header">
            <h3>添加回款 — {{ payRec?.short_name }}</h3>
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
                <input v-model="payForm.notes" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showPayModal = false">取消</button>
            <button class="btn btn-primary" :disabled="paySaving" @click="savePayment">
              {{ paySaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.search-input { padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; min-width: 160px; background: rgba(255,252,250,.7); }
.tab-bar { display: flex; gap: 4px; }
.tab-btn { padding: 7px 18px; border-radius: 8px; font-size: 13px; font-weight: 500; border: 1.5px solid var(--border); background: rgba(255,253,250,.6); color: var(--muted); cursor: pointer; transition: all .15s; }
.tab-btn.active { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 700; }
.tab-btn:hover:not(.active) { border-color: var(--primary); color: var(--primary); }
.proj-name { font-weight: 600; font-size: 13px; }
.proj-no { font-family: monospace; font-size: 11px; color: var(--muted); }
.row-overdue { background: rgba(198,40,40,.04); }
.payment-row { background: rgba(250,248,245,.6); }
.payment-row td { padding-top: 4px; padding-bottom: 4px; }
.muted { color: var(--muted); }
.text-warn { color: #e65100; font-weight: 600; }
.badge-ok { background: rgba(46,125,50,.1); color: #2e7d32; font-size:11px; padding: 2px 8px; border-radius:10px; }
.badge-warn { background: rgba(245,127,23,.12); color: #e65100; font-size:11px; padding: 2px 8px; border-radius:10px; }
.btn-link { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 13px; padding: 2px 4px; }
.btn-link-danger { color: var(--danger); }
.btn-link:hover { text-decoration: underline; }
.pagination { display:flex; align-items:center; justify-content:center; gap:12px; padding:12px 0 4px; font-size:13px; color:var(--muted); }
.pagination button { padding:4px 12px; border:1px solid var(--border); border-radius:6px; background:rgba(255,252,250,.7); cursor:pointer; }
.pagination button:disabled { opacity:.4; cursor:default; }
</style>
