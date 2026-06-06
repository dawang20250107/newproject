<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const stats = ref(null)
const loading = ref(false)
const page = ref(1)
const size = 50

const filters = reactive({ q: '', dept: '', customer_level: '', invoice_mode: '', is_shared: '', is_draft: '' })
const CUSTOMER_LEVELS = ['S级', 'A级', 'B级', 'C级', 'D级']
const showModal = ref(false)
const editItem = ref(null)
const saving = ref(false)
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)

const form = reactive({
  contract_name: '', short_name: '', delivery_dept: '', sub_dept: '',
  business_mode: '', customer_level: 'A级', sales_contact: '', project_manager: '',
  has_contract: '有', contract_date: '', reconciliation_days: 0,
  invoice_wait_days: 0, post_invoice_days: 0, invoice_mode: '全额',
  invoice_type: '专票', tax_rate: '0.06', notes: '',
})

const totalDays = computed(() =>
  (parseInt(form.reconciliation_days) || 0) +
  (parseInt(form.invoice_wait_days) || 0) +
  (parseInt(form.post_invoice_days) || 0))

const isShared = computed(() =>
  form.sales_contact && form.project_manager &&
  form.sales_contact !== form.project_manager)

watch(() => form.invoice_type, val => { if (val === '不开票') form.tax_rate = '0' })

// Scoped to the user's currently-active department selection (set from
// the global picker in the sidebar footer). Falls back to all allowed.
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

// Field-permission column visibility
const show = k => auth.canArView(k)

function fmtNum(v) {
  const n = parseFloat(v) || 0
  return n.toLocaleString('zh-CN')
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const res = await ar.listProjects({ ...filters, page: page.value, size })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

async function loadStats() {
  try {
    const res = await ar.projectStats({ dept: filters.dept })
    stats.value = res.data
  } catch { stats.value = null }
}

function reloadAll() { load(true); loadStats() }

// 搜索防抖：输入停顿 280ms 再查，避免每次按键都打接口、页码反复重置
let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 280)
}
function clearSearch() { filters.q = ''; load(true) }

const hasActiveFilters = computed(() =>
  !!(filters.q || filters.dept || filters.customer_level || filters.invoice_mode ||
     filters.is_draft || (filters.is_shared && !auth.perms?.ar_shared_only)))

function resetFilters() {
  filters.q = ''
  filters.dept = ''
  filters.customer_level = ''
  filters.invoice_mode = ''
  if (!auth.perms?.ar_shared_only) filters.is_shared = ''
  filters.is_draft = ''
  reloadAll()
}

function openCreate() {
  editItem.value = null
  Object.assign(form, {
    contract_name: '', short_name: '', delivery_dept: accessibleDepts.value[0] || '',
    sub_dept: '', business_mode: '', customer_level: 'A级',
    sales_contact: '', project_manager: '', has_contract: '有', contract_date: '',
    reconciliation_days: 0, invoice_wait_days: 0, post_invoice_days: 0,
    invoice_mode: '全额', invoice_type: '专票', tax_rate: '0.06', notes: '',
  })
  showModal.value = true
}

function openEdit(item) {
  editItem.value = item
  Object.assign(form, {
    contract_name: item.contract_name,
    short_name: item.short_name,
    delivery_dept: item.delivery_dept, sub_dept: item.sub_dept,
    business_mode: item.business_mode, customer_level: item.customer_level || 'A级',
    sales_contact: item.sales_contact, project_manager: item.project_manager,
    has_contract: item.has_contract, contract_date: item.contract_date || '',
    reconciliation_days: item.reconciliation_days,
    invoice_wait_days: item.invoice_wait_days,
    post_invoice_days: item.post_invoice_days,
    invoice_mode: item.invoice_mode, invoice_type: item.invoice_type,
    tax_rate: item.tax_rate, notes: item.notes,
  })
  showModal.value = true
}

// Required fields — sub_dept / contract_date / tax_rate are optional
const REQUIRED = [
  ['contract_name', '合同名称'], ['short_name', '项目简称'],
  ['delivery_dept', '交付部门'], ['business_mode', '业务模式'],
  ['customer_level', '客户等级'], ['sales_contact', '销售对接人'],
  ['project_manager', '项目负责人'], ['has_contract', '有无合同'],
  ['invoice_mode', '开票模式'], ['invoice_type', '专票/普票'],
]

async function save() {
  const missing = REQUIRED.filter(([k]) => form[k] === '' || form[k] === null || form[k] === undefined)
  if (missing.length) {
    alert('请填写所有必填字段：\n' + missing.map(([, l]) => l).join('、'))
    return
  }
  saving.value = true
  try {
    if (editItem.value) {
      const payload = { ...form }
      if (editItem.value.is_draft) payload.is_draft = false
      delete payload._complete_draft
      await ar.updateProject(editItem.value.id, payload)
    } else {
      const saved = await ar.createProject(form)
      // 新建后确保立即可见：清空搜索、按新项目部门筛选、回到首页
      filters.q = ''
      const newDept = saved?.data?.delivery_dept || form.delivery_dept
      if (newDept && accessibleDepts.value.includes(newDept)) filters.dept = newDept
      page.value = 1
    }
    showModal.value = false
    reloadAll()
  } catch (e) {
    alert(e?.msg || '保存失败，请检查必填项与部门权限')
  } finally { saving.value = false }
}

async function remove(item) {
  if (!confirm(`确定删除项目「${item.short_name || item.contract_name}」？`)) return
  try { await ar.deleteProject(item.id); reloadAll() }
  catch (e) { alert(e?.msg || '删除失败') }
}

async function completeDraft(item) {
  editItem.value = item
  Object.assign(form, {
    contract_name: item.contract_name || item.short_name,
    short_name: item.short_name,
    delivery_dept: item.delivery_dept, sub_dept: item.sub_dept || '',
    business_mode: item.business_mode || '', customer_level: item.customer_level || 'A级',
    sales_contact: item.sales_contact || '', project_manager: item.project_manager || '',
    has_contract: item.has_contract || '无', contract_date: item.contract_date || '',
    reconciliation_days: item.reconciliation_days || 0,
    invoice_wait_days: item.invoice_wait_days || 0,
    post_invoice_days: item.post_invoice_days || 0,
    invoice_mode: item.invoice_mode || '全额', invoice_type: item.invoice_type || '专票',
    tax_rate: item.tax_rate || '0.06', notes: item.notes || '',
    _complete_draft: true,
  })
  showModal.value = true
}

const isDraftEdit = computed(() => !!(editItem.value?.is_draft))

async function downloadTemplate() {
  const res = await ar.projectTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '项目信息导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importProjects(fd); const d = res.data
    const parts = [`导入完成：新增 ${d.created} 条`]
    if (d.updated) parts.push(`更新 ${d.updated} 条`)
    if (d.skipped) parts.push(`跳过 ${d.skipped} 条`)
    if (d.errors?.length) parts.push(`\n\n以下行未通过校验：\n` + d.errors.join('\n'))
    alert(parts.join('，'))
    reloadAll()
  } catch (e) { alert(e?.msg || '导入失败')
  } finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportProjects(filters)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '项目信息.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.msg || '导出失败')
  } finally { exporting.value = false }
}

const onScopeChange = () => {
  if (filters.dept && !accessibleDepts.value.includes(filters.dept)) filters.dept = ''
  page.value = 1
  reloadAll()
}
onMounted(() => {
  if (auth.perms?.ar_shared_only) filters.is_shared = '1'
  load(); loadStats(); window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div>
    <!-- Header -->
    <div class="topbar">
      <div>
        <h1>项目台账</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">为应收账款提供项目主数据 · 合同账期 · 开票配置</div>
      </div>
    </div>

    <!-- Stats strip -->
    <div class="stats-strip">
      <div class="stat-pill">
        <div class="stat-label">项目总数</div>
        <div class="stat-value">{{ stats?.total ?? '—' }}</div>
      </div>
      <div class="stat-pill stat-pill-gold">
        <div class="stat-label">S 级客户</div>
        <div class="stat-value">{{ stats?.s_count ?? 0 }}</div>
      </div>
      <div class="stat-pill stat-pill-blue">
        <div class="stat-label">A 级客户</div>
        <div class="stat-value">{{ stats?.a_count ?? 0 }}</div>
      </div>
      <div class="stat-pill stat-pill-purple">
        <div class="stat-label">共享业务</div>
        <div class="stat-value">{{ stats?.shared ?? 0 }}</div>
      </div>
      <div v-if="stats?.draft_count" class="stat-pill stat-pill-draft" style="cursor:pointer" @click="filters.is_draft='true'; load(true)" title="点击筛选草稿项目">
        <div class="stat-label">待完善草稿</div>
        <div class="stat-value" style="color:#c0392b">{{ stats.draft_count }}</div>
      </div>
      <div class="stat-pill stat-pill-mom">
        <div class="stat-label">本月新签（环比）</div>
        <div class="stat-value">
          {{ stats?.new_this_month ?? 0 }}
          <span v-if="stats && stats.mom_growth !== null" class="mom-tag" :class="stats.mom_growth >= 0 ? 'mom-up' : 'mom-down'">
            {{ stats.mom_growth >= 0 ? '▲' : '▼' }} {{ Math.abs(stats.mom_growth) }}%
          </span>
          <span v-else class="mom-tag mom-flat">无基期</span>
        </div>
      </div>
      <div class="stat-actions">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate" title="下载模板">↓ 模板</button>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer">
          {{ importing ? '导入中…' : '↑ 导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" :disabled="importing" />
        </label>
        <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">↓ 导出</button>
        <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增项目</button>
      </div>
    </div>

    <!-- Filter strip -->
    <div class="filter-strip">
      <div class="search-box">
        <svg class="search-ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <input v-model="filters.q" class="search-input"
               placeholder="搜索项目编号 / 合同名称 / 项目简称 / 负责人 / 销售对接人"
               @input="onSearchInput" @keyup.enter="load(true)" />
        <button v-if="filters.q" class="search-clear" title="清除" @click="clearSearch">✕</button>
      </div>
      <select v-model="filters.dept" class="sel-bu" @change="reloadAll">
        <option value="">全部事业部</option>
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
      <select v-model="filters.customer_level" class="sel-mo" @change="load(true)">
        <option value="">全部等级</option>
        <option v-for="l in CUSTOMER_LEVELS" :key="l" :value="l">{{ l }}</option>
      </select>
      <select v-model="filters.invoice_mode" class="sel-mo" @change="load(true)">
        <option value="">全部开票</option>
        <option value="全额">全额</option>
        <option value="差额">差额</option>
      </select>
      <select v-model="filters.is_shared" class="sel-mo" @change="load(true)"
              :disabled="auth.perms?.ar_shared_only">
        <option value="">全部业务</option>
        <option value="true">共享业务</option>
        <option value="false">非共享</option>
      </select>
      <select v-model="filters.is_draft" class="sel-mo" @change="load(true)">
        <option value="">全部项目</option>
        <option value="true">待完善草稿</option>
        <option value="false">已完善项目</option>
      </select>
      <button v-if="hasActiveFilters" class="filter-reset" @click="resetFilters">重置筛选</button>
    </div>

    <!-- Table card -->
    <div class="card" :class="{ 'data-reloading': loading && items.length }">
      <div class="table-wrap">
        <table class="proj-table">
          <thead>
            <tr>
              <th>项目编号</th>
              <th v-if="show('p_contract_name') || show('p_short_name')">合同 / 简称</th>
              <th v-if="show('p_delivery_dept')">交付部门</th>
              <th v-if="show('p_sub_dept')">二级部门</th>
              <th v-if="show('p_business_mode')">业务模式</th>
              <th v-if="show('p_customer_level')" class="ctr">客户等级</th>
              <th v-if="show('p_project_manager')">负责人</th>
              <th v-if="show('p_sales_contact')">销售</th>
              <th v-if="show('p_has_contract')" class="ctr">合同</th>
              <th v-if="show('p_contract_date')" class="ctr">签订日期</th>
              <th v-if="show('p_account_period')" class="ctr">总账期</th>
              <th v-if="show('p_invoice_config')" class="ctr">开票</th>
              <th v-if="show('p_notes')">备注</th>
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td colspan="14" class="empty-cell"><div class="empty-inner">⏳ 加载中…</div></td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="14" class="empty-cell"><div class="empty-inner">暂无项目数据，点击「新增项目」开始</div></td>
            </tr>
            <tr v-for="item in items" :key="item.id" class="data-row">
              <td>
                <span class="proj-no-tag">{{ item.project_no }}</span>
                <span v-if="item.is_draft" class="badge-draft" title="导入自动创建，请补充完善">待完善</span>
              </td>
              <td v-if="show('p_contract_name') || show('p_short_name')">
                <div class="contract-name">{{ item.contract_name }}</div>
                <div v-if="item.short_name" class="short-name">{{ item.short_name }}</div>
              </td>
              <td v-if="show('p_delivery_dept')"><span class="dept-chip">{{ item.delivery_dept }}</span></td>
              <td v-if="show('p_sub_dept')" class="text-muted">{{ item.sub_dept || '—' }}</td>
              <td v-if="show('p_business_mode')" class="text-muted">{{ item.business_mode || '—' }}</td>
              <td v-if="show('p_customer_level')" class="ctr">
                <span class="level-chip" :class="'lv-' + (item.customer_level || '')">{{ item.customer_level || '—' }}</span>
              </td>
              <td v-if="show('p_project_manager')" class="person">{{ item.project_manager }}</td>
              <td v-if="show('p_sales_contact')" class="person">
                {{ item.sales_contact }}
                <span v-if="item.is_shared" class="badge-shared">共享</span>
              </td>
              <td v-if="show('p_has_contract')" class="ctr">
                <span :class="item.has_contract === '有' ? 'yn-yes' : 'yn-no'">{{ item.has_contract }}</span>
              </td>
              <td v-if="show('p_contract_date')" class="ctr text-sm">{{ item.contract_date || '—' }}</td>
              <td v-if="show('p_account_period')" class="ctr">
                <span class="days-chip">{{ item.total_days }}天</span>
              </td>
              <td v-if="show('p_invoice_config')" class="ctr">
                <span class="invoice-mode" :class="item.invoice_mode === '全额' ? 'mode-full' : 'mode-diff'">{{ item.invoice_mode }}</span>
                <div class="text-sm text-muted">{{ item.invoice_type }} · {{ (parseFloat(item.tax_rate) * 100).toFixed(0) }}%</div>
              </td>
              <td v-if="show('p_notes')" class="text-muted text-sm">{{ item.notes || '—' }}</td>
              <td class="ctr">
                <div class="row-actions">
                  <button v-if="item.is_draft && auth.canCreate" class="icon-btn icon-btn-complete" @click="completeDraft(item)" title="补充完善草稿项目">完善</button>
                  <button class="icon-btn" @click="openEdit(item)" title="编辑">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button v-if="auth.canDelete" class="icon-btn icon-btn-danger" @click="remove(item)" title="删除">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
      </div>
    </div>

    <!-- Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:720px">
          <div class="modal-header">
            <div>
              <h3>{{ isDraftEdit ? '完善草稿项目' : (editItem ? '编辑项目' : '新增项目') }}</h3>
              <div class="modal-subtitle">
                <span v-if="isDraftEdit" class="badge-draft" style="margin-right:6px">待完善</span>
                {{ editItem ? editItem.project_no : '编号将自动生成 · 标 * 为必填' }}
                <span v-if="isDraftEdit" style="margin-left:6px;color:#c0392b"> — 请补充完整后保存，将自动移出草稿</span>
              </div>
            </div>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>

          <!-- Derived info bar -->
          <div class="derived-bar">
            <div class="derived-item">
              <span class="derived-label">总账期</span>
              <span class="derived-value">{{ totalDays }} 天</span>
            </div>
            <span v-if="isShared" class="badge-shared" style="font-size:12px;padding:3px 10px">共享业务</span>
            <span v-else class="badge-self">自营业务</span>
          </div>

          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2">
                <span>合同名称 <em>*</em></span>
                <input v-model="form.contract_name" placeholder="合同/客户全称（即客户/往来单位名称，预收录入时自动带出）" />
              </label>
              <label class="form-field">
                <span>项目简称 <em>*</em></span>
                <input v-model="form.short_name" placeholder="显示在明细中" />
              </label>
              <label class="form-field">
                <span>交付部门 <em>*</em></span>
                <select v-model="form.delivery_dept">
                  <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>二级部门</span>
                <input v-model="form.sub_dept" placeholder="可选" />
              </label>
              <label class="form-field">
                <span>业务模式 <em>*</em></span>
                <input v-model="form.business_mode" />
              </label>
              <label class="form-field">
                <span>客户等级 <em>*</em></span>
                <select v-model="form.customer_level">
                  <option v-for="l in CUSTOMER_LEVELS" :key="l" :value="l">{{ l }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>销售对接人 <em>*</em></span>
                <input v-model="form.sales_contact" />
              </label>
              <label class="form-field">
                <span>项目负责人 <em>*</em></span>
                <input v-model="form.project_manager" />
              </label>
              <label class="form-field">
                <span>有无合同 <em>*</em></span>
                <select v-model="form.has_contract"><option>有</option><option>无</option></select>
              </label>
              <label class="form-field">
                <span>签订日期</span>
                <input v-model="form.contract_date" type="date" />
              </label>
              <label class="form-field">
                <span>合同对账期（天） <em>*</em></span>
                <input v-model.number="form.reconciliation_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>开票等待期（天） <em>*</em></span>
                <input v-model.number="form.invoice_wait_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>票后等待期（天） <em>*</em></span>
                <input v-model.number="form.post_invoice_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>开票模式 <em>*</em></span>
                <select v-model="form.invoice_mode"><option>全额</option><option>差额</option></select>
              </label>
              <label class="form-field">
                <span>专票 / 普票 <em>*</em></span>
                <select v-model="form.invoice_type"><option>专票</option><option>普票</option><option>不开票</option></select>
              </label>
              <label class="form-field">
                <span>税率（如 0.06 = 6%）</span>
                <input v-model="form.tax_rate" placeholder="0.06，不开票可留空" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="form.notes" placeholder="可选" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存项目' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Stats strip */
.stats-strip { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.stat-pill {
  display: flex; flex-direction: column; gap: 2px;
  padding: 10px 18px; border-radius: 12px;
  background: rgba(255,255,255,0.7); border: 1px solid rgba(255,255,255,0.8);
  box-shadow: 0 2px 12px rgba(0,0,0,0.06); backdrop-filter: blur(10px); min-width: 88px;
}
.stat-pill-gold { border-left: 3px solid #c9a227; }
.stat-pill-blue { border-left: 3px solid #1565c0; }
.stat-pill-purple { border-left: 3px solid #6a1b9a; }
.stat-pill-mom { border-left: 3px solid #2e7d32; }
.stat-label { font-size: 11px; color: var(--muted); font-weight: 500; letter-spacing: 0.03em; }
.stat-value { font-size: 20px; font-weight: 700; color: var(--text); line-height: 1.2; display: flex; align-items: baseline; gap: 6px; }
.mom-tag { font-size: 12px; font-weight: 700; }
.mom-up { color: #2e7d32; }
.mom-down { color: #c62828; }
.mom-flat { color: var(--muted); font-weight: 500; }
.stat-actions { display: flex; gap: 6px; align-items: center; margin-left: auto; flex-wrap: wrap; }
/* Table — compact density */
.proj-table { width: 100%; font-size: 12.5px; table-layout: auto; }
.proj-table th {
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); padding: 9px 12px; background: rgba(0,0,0,0.025);
  border-bottom: 1px solid rgba(0,0,0,0.06); white-space: nowrap;
}
.proj-table td { padding: 9px 12px; vertical-align: middle; }
.proj-table .data-row { transition: background 0.12s; }
.proj-table .data-row:hover { background: rgba(201,99,66,0.04); }
.proj-table .data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.035); }

.empty-cell { padding: 48px !important; text-align: center; }
.empty-inner { color: var(--muted); font-size: 14px; }

.proj-no-tag { font-family: monospace; font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,0.04); padding: 2px 7px; border-radius: 5px; white-space: nowrap; }
.contract-name { font-weight: 600; font-size: 13px; color: var(--text); }
.short-name { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.dept-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 600; white-space: nowrap; }
.person { font-size: 12.5px; color: var(--text); white-space: nowrap; }
.badge-shared { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: rgba(106,27,154,0.1); color: #6a1b9a; font-weight: 600; margin-left: 5px; }
.badge-draft { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: rgba(192,57,43,0.12); color: #c0392b; font-weight: 600; margin-left: 5px; white-space: nowrap; }
.icon-btn-complete { font-size: 11px; font-weight: 600; color: #1565c0; border-color: rgba(21,101,192,0.3); background: rgba(21,101,192,0.06); width: auto; padding: 0 8px; }
.icon-btn-complete:hover { border-color: #1565c0; background: rgba(21,101,192,0.12); color: #1565c0; }
.badge-self { font-size: 12px; padding: 2px 10px; border-radius: 8px; background: rgba(46,125,50,0.1); color: #2e7d32; font-weight: 600; }
.level-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; font-weight: 700; background: rgba(0,0,0,0.05); color: var(--muted); }
.level-chip.lv-S级 { background: rgba(201,162,39,0.15); color: #a8851c; }
.level-chip.lv-A级 { background: rgba(21,101,192,0.12); color: #1565c0; }
.level-chip.lv-B级 { background: rgba(46,125,50,0.1); color: #2e7d32; }
.level-chip.lv-C级 { background: rgba(155,128,112,0.15); color: var(--muted); }
.level-chip.lv-D级 { background: rgba(100,100,100,0.1); color: #888; }
.yn-yes { color: #2e7d32; font-weight: 600; }
.yn-no { color: var(--muted); }
.days-chip { font-size: 12px; padding: 2px 8px; border-radius: 8px; background: rgba(21,101,192,0.08); color: #1565c0; font-weight: 600; white-space: nowrap; }
.invoice-mode { font-size: 12px; padding: 2px 8px; border-radius: 8px; font-weight: 600; }
.mode-full { background: rgba(46,125,50,0.1); color: #2e7d32; }
.mode-diff { background: rgba(245,127,23,0.1); color: #f57f17; }
.text-muted { color: var(--muted); }
.text-sm { font-size: 12px; }
.ctr { text-align: center; }

.row-actions { display: flex; gap: 4px; justify-content: center; }
.icon-btn {
  width: 28px; height: 28px; border-radius: 7px; border: 1px solid var(--border);
  background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center;
  color: var(--muted); cursor: pointer; transition: all 0.14s;
}
.icon-btn:hover { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.08); }
.icon-btn-danger:hover { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.07); }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; }
.page-btn { padding: 5px 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,252,250,0.7); color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.14s; }
.page-btn:hover { border-color: var(--primary); color: var(--primary); }
.page-btn:disabled { opacity: 0.35; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }

/* Modal */
.modal-subtitle { font-size: 12px; color: var(--muted); margin-top: 3px; }
.derived-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 12px 28px; background: linear-gradient(135deg, rgba(201,99,66,0.06), rgba(201,99,66,0.02));
  border-bottom: 1px solid rgba(201,99,66,0.1);
}
.derived-item { display: flex; align-items: baseline; gap: 5px; }
.derived-label { font-size: 11px; color: var(--muted); font-weight: 500; }
.derived-value { font-size: 16px; font-weight: 700; color: var(--primary); }
.filter-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.search-box {
  position: relative; display: flex; align-items: center; flex: 1; min-width: 280px; max-width: 460px;
}
.search-ico { position: absolute; left: 11px; color: var(--muted); pointer-events: none; }
.search-input {
  width: 100%; padding: 9px 30px 9px 34px; border: 1px solid var(--border); border-radius: 10px;
  background: rgba(255,255,255,0.8); font-size: 13px; color: var(--text); transition: border-color .14s, box-shadow .14s;
}
.search-input:focus {
  outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(201,99,66,0.12);
}
.search-clear {
  position: absolute; right: 8px; width: 18px; height: 18px; border: none; border-radius: 50%;
  background: rgba(0,0,0,0.08); color: var(--muted); font-size: 10px; cursor: pointer;
  display: flex; align-items: center; justify-content: center; line-height: 1;
}
.search-clear:hover { background: rgba(198,40,40,0.12); color: #c62828; }
.filter-reset {
  padding: 8px 14px; border: 1px dashed var(--primary); border-radius: 10px; background: transparent;
  color: var(--primary); font-size: 12.5px; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.filter-reset:hover { background: rgba(201,99,66,0.08); }
</style>
