<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'

const auth = useAuthStore()
const now = new Date()
const activeTab = ref('summary')  // summary | collection | payment
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const selectedDept = ref('')
const years = Array.from({ length: 5 }, (_, i) => now.getFullYear() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleDepts = computed(() =>
  auth.isSuperAdmin ? DEPARTMENTS : (auth.user?.departments || []).filter(d => DEPARTMENTS.includes(d)))

// Summary
const summary = ref(null)
const summLoading = ref(false)

// Lists
const collItems = ref([])
const payItems = ref([])
const collTotal = ref(0)
const payTotal = ref(0)
const listLoading = ref(false)

// Modal
const showModal = ref(false)
const modalType = ref('collection')  // collection | payment
const editItem = ref(null)
const saving = ref(false)
const form = reactive({ project_no: '', short_name: '', expected_date: '', sub_dept: '', delivery_dept: '', amount: '', notes: '' })

function fmtAmt(v) {
  const n = parseFloat(v) || 0
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(2)
}

function pct(actual, budget) {
  if (!budget || parseFloat(budget) === 0) return null
  return ((parseFloat(actual) / parseFloat(budget)) * 100).toFixed(1)
}

async function loadSummary() {
  summLoading.value = true
  try {
    const res = await ar.budgetSummary({ year: year.value, month: month.value, dept: selectedDept.value })
    summary.value = res.data
  } finally { summLoading.value = false }
}

async function loadLists() {
  listLoading.value = true
  try {
    const params = { year: year.value, month: month.value, dept: selectedDept.value, size: 200 }
    const [c, p] = await Promise.all([ar.listCollectionBudget(params), ar.listPaymentBudget(params)])
    collItems.value = c.data.items; collTotal.value = c.data.total_amount
    payItems.value = p.data.items; payTotal.value = p.data.total_amount
  } finally { listLoading.value = false }
}

async function loadAll() {
  await Promise.all([loadSummary(), loadLists()])
}

function openCreate(type) {
  modalType.value = type
  editItem.value = null
  const y = year.value, m = month.value
  const d = `${y}-${String(m).padStart(2, '0')}-01`
  Object.assign(form, { project_no: '', short_name: '', expected_date: d, sub_dept: '', delivery_dept: selectedDept.value || (accessibleDepts.value[0] || ''), amount: '', notes: '' })
  showModal.value = true
}

function openEdit(type, item) {
  modalType.value = type
  editItem.value = item
  Object.assign(form, { ...item })
  showModal.value = true
}

async function save() {
  if (!form.short_name || !form.expected_date || !form.amount) {
    alert('请填写项目简称、预计日期和金额')
    return
  }
  saving.value = true
  try {
    if (modalType.value === 'collection') {
      if (editItem.value) await ar.updateCollectionBudget(editItem.value.id, form)
      else await ar.createCollectionBudget(form)
    } else {
      if (editItem.value) await ar.updatePaymentBudget(editItem.value.id, form)
      else await ar.createPaymentBudget(form)
    }
    showModal.value = false
    await loadAll()
  } catch (e) { alert(e?.response?.data?.msg || '保存失败')
  } finally { saving.value = false }
}

async function remove(type, item) {
  if (!confirm(`确定删除「${item.short_name}」的${type === 'collection' ? '收款' : '付款'}预算？`)) return
  try {
    if (type === 'collection') await ar.deleteCollectionBudget(item.id)
    else await ar.deletePaymentBudget(item.id)
    await loadAll()
  } catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

onMounted(loadAll)
</script>

<template>
  <div>
    <div class="topbar">
      <h1>预算管理</h1>
      <div class="ctrl-row">
        <select v-model="year" class="sel-yr" @change="loadAll">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <select v-model="month" class="sel-mo" @change="loadAll">
          <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
        </select>
        <select v-model="selectedDept" class="sel-bu" @change="loadAll">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
    </div>

    <!-- Tabs -->
    <div style="display:flex;gap:4px;margin-bottom:16px">
      <button :class="['tab-btn', activeTab === 'summary' ? 'active' : '']" @click="activeTab = 'summary'">执行概览</button>
      <button :class="['tab-btn', activeTab === 'collection' ? 'active' : '']" @click="activeTab = 'collection'">收款预算</button>
      <button :class="['tab-btn', activeTab === 'payment' ? 'active' : '']" @click="activeTab = 'payment'">付款预算</button>
    </div>

    <!-- Summary tab -->
    <template v-if="activeTab === 'summary'">
      <!-- Alert -->
      <div v-if="summary?.has_alert" class="cashflow-alert">
        <span style="font-size:22px">⚠</span>
        <div>
          <div style="font-weight:700;color:#c62828">实际付款超过实际收款</div>
          <div style="font-size:12px;color:#c62828;margin-top:4px">{{ year }}年{{ month }}月 · {{ selectedDept || '全部事业部' }}</div>
        </div>
      </div>

      <div v-if="summary" class="kpi-grid kpi-4">
        <div class="kpi-card">
          <div class="label">收款预算</div>
          <div class="value" style="color:#1565c0">{{ fmtAmt(summary.budget_collection) }}</div>
          <div class="sub">元</div>
        </div>
        <div class="kpi-card">
          <div class="label">实际收款</div>
          <div class="value" style="color:#2e7d32">{{ fmtAmt(summary.actual_collection) }}</div>
          <div v-if="summary.collection_achievement_rate !== null" class="mom-badge" :class="parseFloat(summary.collection_achievement_rate) >= 100 ? 'mom-up' : 'mom-down'">
            达成率 {{ summary.collection_achievement_rate }}%
          </div>
        </div>
        <div class="kpi-card">
          <div class="label">付款预算</div>
          <div class="value" style="color:#f57f17">{{ fmtAmt(summary.budget_payment) }}</div>
          <div class="sub">元</div>
        </div>
        <div class="kpi-card" :class="summary.has_alert ? 'kpi-negative' : ''">
          <div class="label">实际付款</div>
          <div class="value" :style="summary.has_alert ? 'color:#c62828' : 'color:var(--text)'">{{ fmtAmt(summary.actual_payment) }}</div>
          <div v-if="summary.payment_achievement_rate !== null" class="mom-badge mom-neutral">
            达成率 {{ summary.payment_achievement_rate }}%
          </div>
        </div>
      </div>

      <div v-if="summary" class="card" style="margin-top:16px">
        <div class="section-title">收付缺口</div>
        <div style="display:flex;gap:24px;flex-wrap:wrap;padding:8px 0">
          <div>
            <div style="font-size:12px;color:var(--muted)">收款缺口（预算-实际）</div>
            <div style="font-size:18px;font-weight:700;" :class="parseFloat(summary.collection_gap) > 0 ? 'text-warn' : 'text-ok'">
              {{ fmtAmt(summary.collection_gap) }}
            </div>
          </div>
          <div>
            <div style="font-size:12px;color:var(--muted)">付款缺口（预算-实际）</div>
            <div style="font-size:18px;font-weight:700;color:var(--text)">{{ fmtAmt(summary.payment_gap) }}</div>
          </div>
          <div>
            <div style="font-size:12px;color:var(--muted)">净现金流（实收-实付）</div>
            <div style="font-size:18px;font-weight:700;" :class="parseFloat(summary.actual_collection) - parseFloat(summary.actual_payment) >= 0 ? 'text-ok' : 'text-danger'">
              {{ fmtAmt(parseFloat(summary.actual_collection) - parseFloat(summary.actual_payment)) }}
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Collection budget tab -->
    <template v-else-if="activeTab === 'collection'">
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <div class="section-title" style="margin:0">收款预算 · 合计 {{ fmtAmt(collTotal) }}</div>
          <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate('collection')">+ 新增</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>项目编号</th>
                <th>项目简称/摘要</th>
                <th>预计收款日期</th>
                <th>二级部门</th>
                <th>交付部门</th>
                <th class="amt">金额</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!collItems.length">
                <td colspan="8" style="text-align:center;padding:32px;color:var(--muted)">暂无收款预算数据</td>
              </tr>
              <tr v-for="item in collItems" :key="item.id">
                <td class="muted mono">{{ item.project_no || '—' }}</td>
                <td>{{ item.short_name }}</td>
                <td>{{ item.expected_date }}</td>
                <td>{{ item.sub_dept }}</td>
                <td>{{ item.delivery_dept }}</td>
                <td class="amt text-ok">{{ fmtAmt(item.amount) }}</td>
                <td class="muted">{{ item.notes }}</td>
                <td>
                  <button class="btn-link" @click="openEdit('collection', item)">编辑</button>
                  <span v-if="auth.canDelete"> · </span>
                  <button v-if="auth.canDelete" class="btn-link btn-link-danger" @click="remove('collection', item)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- Payment budget tab -->
    <template v-else>
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <div class="section-title" style="margin:0">付款预算 · 合计 {{ fmtAmt(payTotal) }}</div>
          <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate('payment')">+ 新增</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>项目编号</th>
                <th>项目简称/摘要</th>
                <th>预计付款日期</th>
                <th>二级部门</th>
                <th>交付部门</th>
                <th class="amt">金额</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!payItems.length">
                <td colspan="8" style="text-align:center;padding:32px;color:var(--muted)">暂无付款预算数据</td>
              </tr>
              <tr v-for="item in payItems" :key="item.id">
                <td class="muted mono">{{ item.project_no || '—' }}</td>
                <td>{{ item.short_name }}</td>
                <td>{{ item.expected_date }}</td>
                <td>{{ item.sub_dept }}</td>
                <td>{{ item.delivery_dept }}</td>
                <td class="amt" style="color:#f57f17">{{ fmtAmt(item.amount) }}</td>
                <td class="muted">{{ item.notes }}</td>
                <td>
                  <button class="btn-link" @click="openEdit('payment', item)">编辑</button>
                  <span v-if="auth.canDelete"> · </span>
                  <button v-if="auth.canDelete" class="btn-link btn-link-danger" @click="remove('payment', item)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- Budget Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:460px">
          <div class="modal-header">
            <h3>{{ editItem ? '编辑' : '新增' }}{{ modalType === 'collection' ? '收款' : '付款' }}预算</h3>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field" v-if="modalType === 'collection'">
                <span>项目编号（可选）</span>
                <input v-model="form.project_no" placeholder="填写后可关联项目" />
              </label>
              <label class="form-field" :class="modalType === 'payment' ? 'span2' : ''">
                <span>项目简称/摘要 <em>*</em></span>
                <input v-model="form.short_name" />
              </label>
              <label class="form-field">
                <span>预计{{ modalType === 'collection' ? '收款' : '付款' }}日期 <em>*</em></span>
                <input v-model="form.expected_date" type="date" />
              </label>
              <label class="form-field">
                <span>金额 <em>*</em></span>
                <input v-model="form.amount" type="number" step="0.01" />
              </label>
              <label class="form-field">
                <span>交付部门</span>
                <select v-model="form.delivery_dept">
                  <option value="">不限</option>
                  <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>二级部门</span>
                <input v-model="form.sub_dept" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="form.notes" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.tab-btn { padding: 7px 18px; border-radius: 8px; font-size: 13px; font-weight: 500; border: 1.5px solid var(--border); background: rgba(255,253,250,.6); color: var(--muted); cursor: pointer; transition: all .15s; }
.tab-btn.active { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 700; }
.kpi-4 { grid-template-columns: repeat(4,1fr) !important; }
@media (max-width:700px) { .kpi-4 { grid-template-columns: repeat(2,1fr) !important; } }
.kpi-negative { border-left: 3px solid var(--danger) !important; animation: negBreathe 2.2s ease-in-out infinite; }
@keyframes negBreathe { 0%,100% { box-shadow: 0 2px 8px rgba(198,40,40,.10); } 50% { box-shadow: 0 4px 18px rgba(198,40,40,.30); background: rgba(198,40,40,.04); } }
.cashflow-alert { display:flex;align-items:flex-start;gap:14px;padding:16px 20px;margin-bottom:16px;background:rgba(198,40,40,.06);border:1.5px solid rgba(198,40,40,.25);border-radius:12px;animation:alertGlow 1.4s ease-in-out infinite; }
@keyframes alertGlow { 0%,100% { box-shadow:0 2px 12px rgba(198,40,40,.1);border-color:rgba(198,40,40,.25); } 50% { box-shadow:0 4px 24px rgba(198,40,40,.28);border-color:rgba(198,40,40,.5);background:rgba(198,40,40,.1); } }
.btn-link { background:none;border:none;color:var(--primary);cursor:pointer;font-size:13px;padding:2px 4px; }
.btn-link-danger { color:var(--danger); }
.btn-link:hover { text-decoration:underline; }
.text-ok { color:#2e7d32; }
.text-warn { color:#e65100; font-weight:600; }
.text-danger { color:#c62828; font-weight:600; }
.muted { color:var(--muted); }
.mono { font-family:monospace;font-size:12px; }
.mom-badge { display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;border-radius:10px;margin-top:4px; }
.mom-up { background:rgba(46,125,50,.10);color:#2e7d32; }
.mom-down { background:rgba(198,40,40,.10);color:var(--danger); }
.mom-neutral { background:rgba(120,120,120,.08);color:var(--muted);font-weight:400; }
</style>
