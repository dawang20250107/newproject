<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import StatusBadge from '../components/StatusBadge.vue'
import PaymentModal from '../components/PaymentModal.vue'

const auth = useAuthStore()

// Column visibility from field-level view permissions.
const showPaid = computed(() => auth.canView('pay1') || auth.canView('pay2') || auth.canView('pay3'))
const showRemaining = computed(() => auth.canView('total_amount') && showPaid.value)
function dash(v) { return v === null || v === undefined ? '—' : fmt(v) }
const items = ref([])
const total = ref(0)
const loading = ref(false)
const departments = ref([])
const showModal = ref(false)
const editItem = ref(null)
const loadErr = ref('')

const filters = reactive({
  q: '', dept: '', status: '', start_date: '', end_date: '',
  page: 1, size: 50,
})

function fmt(n) {
  const v = parseFloat(n || 0)
  return v >= 10000 ? (v / 10000).toFixed(2) + ' 万' : v.toFixed(2)
}

// ── Excel import / export / template ──────────────────────────────────────────
const importInputRef = ref(null)
const importing = ref(false)
const exportingXlsx = ref(false)
const importResult = ref(null)

async function downloadTemplate() {
  try {
    const res = await api.get('/payments/template', { responseType: 'blob' })
    triggerDownload(res.data, '排款导入模板.xlsx')
  } catch { alert('模板下载失败') }
}

function triggerImport() {
  importResult.value = null
  importInputRef.value.click()
}

async function onImportFile(e) {
  const file = e.target.files[0]
  if (!file) return
  importing.value = true
  importResult.value = null
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await api.post('/payments/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    importResult.value = res.data
    if (res.data.created > 0) load()
  } catch (ex) {
    importResult.value = { error: ex?.error || '导入失败，请检查文件格式' }
  } finally {
    importing.value = false
    e.target.value = ''
  }
}

async function exportExcel() {
  exportingXlsx.value = true
  try {
    const params = Object.fromEntries(
      Object.entries(filters).filter(([k, v]) => v !== '' && k !== 'page' && k !== 'size')
    )
    const res = await api.get('/payments/export', { params, responseType: 'blob' })
    const date = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', '月') + '日'
    triggerDownload(res.data, `排款记录_${date}.xlsx`)
  } catch { alert('导出失败，请稍后重试') }
  finally { exportingXlsx.value = false }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ''))
    const res = await api.get('/payments', { params })
    items.value = res.data.items
    total.value = res.data.total
  } catch (e) {
    loadErr.value = e?.error || '加载失败，请刷新重试'
  } finally {
    loading.value = false
  }
}

async function loadDepts() {
  try {
    const res = await api.get('/departments')
    departments.value = res.data
  } catch {}
}

onMounted(() => { load(); loadDepts() })

function openAdd() { editItem.value = null; showModal.value = true }
function openEdit(p) { editItem.value = p; showModal.value = true }

function onSaved(p) {
  showModal.value = false
  load()
  loadDepts()
}

async function onDelete(p) {
  if (!confirm(`确定删除「${p.project_desc}」？此操作不可撤销。`)) return
  try {
    await api.delete(`/payments/${p.id}`)
    load()
  } catch (e) {
    alert(e?.error || '删除失败')
  }
}

function search() { filters.page = 1; load() }
function resetFilters() {
  Object.assign(filters, { q: '', dept: '', status: '', start_date: '', end_date: '', page: 1 })
  load()
}

const totalPages = ref(0)
function setPage(p) { filters.page = p; load() }
</script>

<template>
  <div>
    <div class="topbar">
      <h1>付款台账</h1>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate" title="下载Excel导入模板">
          <span style="margin-right:4px">⬇</span>模板
        </button>
        <button v-if="auth.canCreate" class="btn btn-ghost btn-sm" :disabled="importing" @click="triggerImport">
          <span v-if="importing" class="btn-spin"></span>
          <span v-else style="margin-right:4px">📥</span>{{ importing ? '导入中…' : '导入' }}
        </button>
        <button class="btn btn-ghost btn-sm" :disabled="exportingXlsx" @click="exportExcel">
          <span v-if="exportingXlsx" class="btn-spin"></span>
          <span v-else style="margin-right:4px">📤</span>{{ exportingXlsx ? '导出中…' : '导出' }}
        </button>
        <button v-if="auth.canCreate" class="btn btn-primary" @click="openAdd">+ 新增排款</button>
      </div>
    </div>

    <!-- hidden file input for import -->
    <input ref="importInputRef" type="file" accept=".xlsx,.xls" style="display:none" @change="onImportFile" />

    <!-- import result feedback -->
    <Transition name="fade-slide">
      <div v-if="importResult" class="import-result" :class="importResult.error ? 'import-err' : 'import-ok'">
        <div v-if="importResult.error">❌ {{ importResult.error }}</div>
        <div v-else>
          <strong>✅ 导入完成：成功 {{ importResult.created }} 条
          <span v-if="importResult.skipped">，跳过 {{ importResult.skipped }} 条</span></strong>
          <ul v-if="importResult.errors?.length" style="margin:6px 0 0;padding-left:18px;font-size:12px">
            <li v-for="e in importResult.errors.slice(0, 10)" :key="e">{{ e }}</li>
            <li v-if="importResult.errors.length > 10">… 共 {{ importResult.errors.length }} 个错误</li>
          </ul>
        </div>
        <button class="close-btn" @click="importResult = null">✕</button>
      </div>
    </Transition>

    <div class="card" style="margin-bottom:16px">
      <div class="filter-bar">
        <input v-model="filters.q" placeholder="搜索事项/收款方/单号…" style="min-width:200px" @keyup.enter="search" />
        <select v-model="filters.dept" @change="search">
          <option value="">全部部门</option>
          <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.status" @change="search">
          <option value="">全部状态</option>
          <option value="pending">⏳ 待付款</option>
          <option value="partial">⚡ 部分付款</option>
          <option value="settled">✅ 已付清</option>
        </select>
        <input v-model="filters.start_date" type="date" style="min-width:130px" @change="search" />
        <input v-model="filters.end_date" type="date" style="min-width:130px" @change="search" />
        <button class="btn btn-ghost btn-sm" @click="search">筛选</button>
        <button class="btn btn-sm" style="background:var(--bg2);border:none" @click="resetFilters">重置</button>
      </div>

      <div style="font-size:13px;color:var(--muted);margin-bottom:8px">共 {{ total }} 条记录</div>

      <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="loadErr" class="empty" style="color:#c62828"><div class="icon">⚠️</div>{{ loadErr }}</div>

      <div v-else-if="!items.length" class="empty">
        <div class="icon">📭</div>暂无数据
      </div>

      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th v-if="auth.canView('department')">部门</th>
              <th v-if="auth.canView('approval_number')">审批单号</th>
              <th v-if="auth.canView('project_desc')">付款事项</th>
              <th v-if="auth.canView('payee')">收款方</th>
              <th v-if="auth.canView('planned_date')">计划日期</th>
              <th v-if="auth.canView('total_amount')">计划总额 (元)</th>
              <th v-if="showPaid">已付 (元)</th>
              <th v-if="showRemaining">剩余 (元)</th>
              <th>状态</th>
              <th v-if="auth.canWrite || auth.canDelete">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in items" :key="p.id">
              <td v-if="auth.canView('department')">{{ p.department }}</td>
              <td v-if="auth.canView('approval_number')">{{ p.approval_number || '—' }}</td>
              <td v-if="auth.canView('project_desc')" style="max-width:200px;white-space:normal;word-break:break-all">{{ p.project_desc }}</td>
              <td v-if="auth.canView('payee')">{{ p.payee }}</td>
              <td v-if="auth.canView('planned_date')">{{ p.planned_date }}</td>
              <td v-if="auth.canView('total_amount')" class="amt">{{ dash(p.total_amount) }}</td>
              <td v-if="showPaid" class="amt amt-green">{{ dash(p.total_paid) }}</td>
              <td v-if="showRemaining" class="amt" :class="parseFloat(p.remaining) > 0 ? 'amt-red' : ''">{{ dash(p.remaining) }}</td>
              <td><StatusBadge :status="p.status" /></td>
              <td v-if="auth.canWrite || auth.canDelete">
                <div style="display:flex;gap:6px">
                  <button v-if="auth.canWrite" class="btn btn-ghost btn-sm" @click="openEdit(p)">编辑</button>
                  <button v-if="auth.canDelete" class="btn btn-danger btn-sm" @click="onDelete(p)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- pagination -->
      <div class="pagination">
        <span>第 {{ filters.page }} 页，共 {{ Math.ceil(total / filters.size) || 1 }} 页</span>
        <button :disabled="filters.page <= 1" @click="setPage(filters.page - 1)">上一页</button>
        <button :disabled="filters.page * filters.size >= total" @click="setPage(filters.page + 1)">下一页</button>
      </div>
    </div>

    <PaymentModal
      v-if="showModal"
      :payment="editItem"
      :departments="departments"
      @saved="onSaved"
      @close="showModal = false"
    />
  </div>
</template>

<style scoped>
.import-result {
  position: relative;
  margin-bottom: 14px;
  padding: 12px 40px 12px 16px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
}
.import-ok {
  background: rgba(46,125,50,0.08);
  border: 1px solid rgba(46,125,50,0.25);
  color: #2e7d32;
}
.import-err {
  background: rgba(198,40,40,0.07);
  border: 1px solid rgba(198,40,40,0.25);
  color: #c62828;
}
.close-btn {
  position: absolute;
  top: 8px; right: 10px;
  background: none; border: none;
  cursor: pointer; font-size: 14px; color: inherit; opacity: 0.6;
}
.close-btn:hover { opacity: 1; }
.btn-spin {
  display: inline-block;
  width: 11px; height: 11px;
  border-radius: 50%;
  border: 2px solid rgba(0,0,0,0.2);
  border-top-color: var(--primary);
  animation: spin 0.7s linear infinite;
  margin-right: 4px;
  vertical-align: middle;
}
@keyframes spin { to { transform: rotate(360deg); } }
.fade-slide-enter-active, .fade-slide-leave-active { transition: opacity 0.2s, transform 0.2s; }
.fade-slide-enter-from, .fade-slide-leave-to { opacity: 0; transform: translateY(-6px); }
</style>
