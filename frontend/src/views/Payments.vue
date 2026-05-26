<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { todayCST } from '../constants.js'
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
const today = todayCST()  // UTC+8，与服务端 Asia/Shanghai 保持一致

const filters = reactive({
  q: '', dept: '', status: '', start_date: '', end_date: '',
  sort_by: 'planned_date', sort_dir: 'desc',
  page: 1, size: 50,
})

// Non-admins may only filter by departments they are assigned to.
const deptChoices = computed(() => {
  if (auth.isAdmin) return departments.value
  const mine = auth.user?.departments || []
  return departments.value.filter(d => mine.includes(d))
})

// Hover tooltip card for truncated long cells (付款事项 / 收款方).
const tip = reactive({ show: false, text: '', x: 0, y: 0 })
function showTip(e, text) {
  if (!text) return
  tip.text = text
  positionTip(e)
  tip.show = true
}
function positionTip(e) {
  tip.x = Math.min(e.clientX + 16, window.innerWidth - 340)
  tip.y = Math.min(e.clientY + 18, window.innerHeight - 60)
}
function moveTip(e) { if (tip.show) positionTip(e) }
function hideTip() { tip.show = false }

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
    // Interceptor returns res.data, so for a blob request this IS the Blob.
    const blob = await api.get('/payments/template', { responseType: 'blob', timeout: 60000 })
    triggerDownload(blob, '排款导入模板.xlsx')
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
      timeout: 60000,
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
    const blob = await api.get('/payments/export', { params, responseType: 'blob', timeout: 60000 })
    const date = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', '月') + '日'
    triggerDownload(blob, `排款记录_${date}.xlsx`)
  } catch (e) { alert(e?.error || '导出失败，请稍后重试') }
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

function setPage(p) { filters.page = p; load() }
function onSort(k) {
  if (filters.sort_by === k) filters.sort_dir = filters.sort_dir === 'asc' ? 'desc' : 'asc'
  else { filters.sort_by = k; filters.sort_dir = 'desc' }
  filters.page = 1
  load()
}
</script>

<template>
  <div>
    <div class="topbar">
      <h1>付款台账</h1>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate" title="下载Excel导入模板">
          <span style="margin-right:4px">⬇</span>模板
        </button>
        <button class="btn btn-ghost btn-sm" :disabled="importing" @click="triggerImport">
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

    <div class="card" style="margin-bottom:16px">
      <div class="filter-bar">
        <input v-model="filters.q" placeholder="搜索事项/收款方/单号…" style="min-width:200px" @keyup.enter="search" />
        <select v-model="filters.dept" @change="search">
          <option value="">全部部门</option>
          <option v-for="d in deptChoices" :key="d" :value="d">{{ d }}</option>
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
              <th v-if="auth.canView('department')" @click="onSort('department')" style="cursor:pointer">部门</th>
              <th v-if="auth.canView('approval_number')" @click="onSort('approval_number')" style="cursor:pointer">审批单号</th>
              <th v-if="auth.canView('project_desc')" @click="onSort('project_desc')" style="cursor:pointer">付款事项</th>
              <th v-if="auth.canView('payee')" @click="onSort('payee')" style="cursor:pointer">收款方</th>
              <th v-if="auth.canView('planned_date')" @click="onSort('planned_date')" style="cursor:pointer">计划日期</th>
              <th v-if="auth.canView('total_amount')" @click="onSort('total_amount')" style="cursor:pointer">计划总额 (元)</th>
              <th v-if="showPaid" @click="onSort('total_paid')" style="cursor:pointer">已付 (元)</th>
              <th v-if="showRemaining" @click="onSort('remaining')" style="cursor:pointer">剩余 (元)</th>
              <th>状态</th>
              <th v-if="auth.canWrite || auth.canDelete">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in items" :key="p.id"
              :class="{ 'overdue-row': p.status !== 'settled' && p.planned_date && p.planned_date < today }">
              <td v-if="auth.canView('department')">{{ p.department }}</td>
              <td v-if="auth.canView('approval_number')">{{ p.approval_number || '—' }}</td>
              <td v-if="auth.canView('project_desc')" class="cell-clip cell-desc"
                @mouseenter="showTip($event, p.project_desc)" @mousemove="moveTip" @mouseleave="hideTip">
                {{ p.project_desc }}
              </td>
              <td v-if="auth.canView('payee')" class="cell-clip cell-payee"
                @mouseenter="showTip($event, p.payee)" @mousemove="moveTip" @mouseleave="hideTip">
                {{ p.payee }}
              </td>
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

    <!-- import result popup -->
    <div v-if="importResult" class="overlay" @click.self="importResult = null">
      <div class="modal" style="width:520px">
        <div class="modal-header">
          <h3 v-if="importResult.error">导入失败</h3>
          <h3 v-else>导入完成</h3>
          <button class="modal-close" @click="importResult = null">×</button>
        </div>

        <!-- hard error (whole file rejected) -->
        <div v-if="importResult.error" class="imp-hero imp-hero-err">
          <div class="imp-emoji">⚠️</div>
          <div class="imp-msg">{{ importResult.error }}</div>
        </div>

        <template v-else>
          <!-- summary -->
          <div class="imp-summary">
            <div class="imp-stat imp-stat-ok">
              <div class="imp-num">{{ importResult.created }}</div>
              <div class="imp-lbl">成功导入</div>
            </div>
            <div class="imp-stat" :class="importResult.skipped ? 'imp-stat-skip' : ''">
              <div class="imp-num">{{ importResult.skipped || 0 }}</div>
              <div class="imp-lbl">跳过 / 未通过</div>
            </div>
          </div>

          <!-- highlighted list of skipped / non-compliant rows -->
          <div v-if="importResult.message" class="imp-msg-banner">{{ importResult.message }}</div>

          <div v-if="importResult.errors?.length" class="imp-errbox">
            <div class="imp-errtitle">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              以下 {{ importResult.errors.length }} 行未通过校验，已跳过：
            </div>
            <ul class="imp-errlist">
              <li v-for="(e, i) in importResult.errors" :key="i">{{ e }}</li>
            </ul>
          </div>

          <div v-else-if="!importResult.skipped" class="imp-allok">🎉 全部数据校验通过，无跳过项。</div>
        </template>

        <div class="modal-footer">
          <button class="btn btn-primary" @click="importResult = null">我知道了</button>
        </div>
      </div>
    </div>

    <!-- hover tooltip card for long cells -->
    <Transition name="tip-fade">
      <div v-if="tip.show" class="cell-tooltip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
        {{ tip.text }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* truncated long cells + hover tooltip card */
.cell-clip {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}
.cell-desc { max-width: 160px; }
.cell-payee { max-width: 110px; }
.cell-tooltip {
  position: fixed;
  z-index: 9000;
  max-width: 320px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(36, 18, 10, 0.94);
  color: #f3e7dc;
  font-size: 13px;
  line-height: 1.55;
  white-space: normal;
  word-break: break-word;
  box-shadow: 0 10px 30px rgba(20, 8, 4, 0.4);
  border: 1px solid rgba(255,255,255,0.1);
  pointer-events: none;
  backdrop-filter: blur(6px);
}
.tip-fade-enter-active, .tip-fade-leave-active { transition: opacity 0.14s ease; }
.tip-fade-enter-from, .tip-fade-leave-to { opacity: 0; }

/* import result popup */
.imp-hero { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0 8px; text-align: center; }
.imp-emoji { font-size: 44px; }
.imp-msg { font-size: 14px; line-height: 1.6; }
.imp-hero-err .imp-msg { color: #c62828; }
.imp-summary { display: flex; gap: 14px; margin-bottom: 16px; }
.imp-stat {
  flex: 1; text-align: center; padding: 16px 10px;
  border-radius: 14px; border: 1px solid var(--border);
  background: rgba(255,253,250,0.6);
}
.imp-stat-ok { background: rgba(46,125,50,0.08); border-color: rgba(46,125,50,0.25); }
.imp-stat-skip { background: rgba(245,127,23,0.09); border-color: rgba(245,127,23,0.3); }
.imp-num { font-size: 30px; font-weight: 800; line-height: 1; }
.imp-stat-ok .imp-num { color: #2e7d32; }
.imp-stat-skip .imp-num { color: #e65100; }
.imp-lbl { font-size: 12px; color: var(--muted); margin-top: 6px; letter-spacing: 0.03em; }
.imp-errbox {
  border-radius: 12px; border: 1px solid rgba(245,127,23,0.3);
  background: rgba(245,127,23,0.06); overflow: hidden;
}
.imp-errtitle {
  display: flex; align-items: center; gap: 7px;
  padding: 10px 14px; font-size: 12.5px; font-weight: 600; color: #e65100;
  background: rgba(245,127,23,0.1);
}
.imp-errtitle svg { flex-shrink: 0; }
.imp-errlist {
  margin: 0; padding: 8px 14px 10px 30px;
  max-height: 240px; overflow-y: auto;
  font-size: 12.5px; line-height: 1.7; color: #b35309;
}
.imp-allok { text-align: center; color: #2e7d32; font-size: 13.5px; padding: 6px 0 4px; }
.imp-msg-banner {
  font-size: 13px; color: #5a4030; background: rgba(201,99,66,0.07);
  border: 1px solid rgba(201,99,66,0.18); border-radius: 8px;
  padding: 8px 14px; margin-bottom: 12px; line-height: 1.5;
}
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
</style>
