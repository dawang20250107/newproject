<script setup>
import { ref, reactive, computed, onMounted, defineAsyncComponent, nextTick } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { yearCST, todayCST, DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'
import ColumnFilter from '../../components/ColumnFilter.vue'
import SkeletonRow from '../../components/SkeletonRow.vue'
import SchemePicker from '../../components/SchemePicker.vue'
import { useTableSchemes } from '../../composables/useTableSchemes.js'
import { useColWidths } from '../../composables/useColWidths.js'

// 项目损益卡（复用 P1 组件）— 点客户项目即下钻全链路损益
const ProjectPnlCard = defineAsyncComponent(() => import('../caiwu/ProjectPnlCard.vue'))

const auth = useAuthStore()
const accessibleDepts = computed(() => (auth.effectiveDepts || []).filter(d => DEPARTMENTS.includes(d)))

const items = ref([])
const total = ref(0)
const loading = ref(false)
const loadErr = ref('')
const page = ref(1)
const size = 50
const filters = reactive({ q: '', level: '', dept: '', status: '' })
const STATUSES = ['运作中', '中断', '结束']
const statusClass = s => ({ '运作中': 'st-on', '中断': 'st-pause', '结束': 'st-end' }[s] || 'st-on')

// 排序（服务端，跨分页生效；未收/逾期最常用）
const sortKey = ref('outstanding')
const sortDir = ref('desc')

// 列宽持久化
const cw = useColWidths('ar_customers', {
  name: 180, delivery_dept: 80, level: 70, status: 72, contact: 100,
  outstanding: 100, overdue_amount: 100, project_count: 72,
})

// Excel 风格列头筛选：真实列走 filters JSON，计算列仅排序
const colFilters = reactive({})
function setColFilter(field, val) {
  if (val == null) delete colFilters[field]
  else colFilters[field] = val
  load(true)
}
function setColSort(field, order) {
  if (!order) { sortKey.value = 'outstanding'; sortDir.value = 'desc' }
  else { sortKey.value = field; sortDir.value = order }
  load(true)
}

// 详情抽屉
const detail = ref(null)        // 客户详情数据
const detailLoading = ref(false)
const drawerOpen = ref(false)

// 编辑/新建
const showEdit = ref(false)
const editForm = reactive({ id: null, name: '', delivery_dept: '', level: '', status: '运作中', contact: '', customer_date: '', notes: '', push_status: false })
const saving = ref(false)

// 项目损益卡
const pnlName = ref('')
const year = ref(yearCST())

const toast = ref('')
let toastTimer = null
function showToast(m) { toast.value = m; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 2200) }

const wan = v => (v == null || v === '') ? '—' : (Number(v) / 1e4).toFixed(1) + '万'
const LEVELS = ['S级', 'A级', 'B级', 'C级', 'D级']
const levelClass = l => 'lvl-' + (l || '').replace('级', '')

// 批量打等级
const selected = ref(new Set())
const bulkLevel = ref('')
const bulkSaving = ref(false)
function toggleSel(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
const allOnPageSelected = computed(() =>
  items.value.length > 0 && items.value.every(c => selected.value.has(c.id)))
function toggleSelAll() {
  const s = new Set(selected.value)
  if (allOnPageSelected.value) items.value.forEach(c => s.delete(c.id))
  else items.value.forEach(c => s.add(c.id))
  selected.value = s
}
function clearSel() { selected.value = new Set() }

// 从项目台账回填客户（存量项目未建客户时一键补齐）
const syncing = ref(false)
async function syncFromProjects() {
  syncing.value = true
  try {
    const res = await ar.syncCustomersFromProjects()
    showToast(res.data?.message || '✓ 已同步')
    await load(true)
  } catch (e) { showToast(e?.error || '同步失败') }
  finally { syncing.value = false }
}

// 创建时间显示（只显示日期）
const fmtDate = v => v ? String(v).slice(0, 10) : '—'
async function applyBulkLevel() {
  if (!selected.value.size) return showToast('请先勾选客户')
  bulkSaving.value = true
  try {
    const res = await ar.bulkTagCustomerLevel({ ids: [...selected.value], level: bulkLevel.value })
    showToast(res.data?.message || '✓ 已更新')
    clearSel()
    await load()
  } catch (e) { showToast(e?.error || '批量打标失败') }
  finally { bulkSaving.value = false }
}

// 批量删除：名下有项目/合同关联的客户由后端保护跳过并说明原因
const bulkDeleting = ref(false)
async function bulkDeleteCustomers() {
  const n = selected.value.size
  if (!n) return showToast('请先勾选客户')
  if (!confirm(`确定删除选中的 ${n} 个客户？\n名下仍有项目或合同关联的客户会被自动跳过（不会误删）。`)) return
  bulkDeleting.value = true
  try {
    const res = await ar.bulkDeleteCustomers({ ids: [...selected.value] })
    const d = res.data
    showToast(d?.message || `已删除 ${d?.deleted ?? 0} 个客户`)
    if (d?.skipped_reasons?.length) {
      showToast(`以下客户被保护跳过：${d.skipped_reasons.join('；')}`)
    }
    clearSel()
    await load(true)
  } catch (e) { showToast(e?.error || e?.msg || '批量删除失败') }
  finally { bulkDeleting.value = false }
}

async function load(reset = false) {
  if (reset) { page.value = 1; clearSel() }
  loading.value = true
  loadErr.value = ''
  try {
    const params = { ...filters, page: page.value, size, sort: sortKey.value, dir: sortDir.value }
    if (Object.keys(colFilters).length) params.filters = JSON.stringify(colFilters)
    const res = await ar.listCustomers(params)
    items.value = res.data.items
    total.value = res.data.total
  } catch (e) { loadErr.value = e?.error || e?.message || '加载失败，请刷新重试'
  } finally { loading.value = false }
}
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size)))
function go(p) { if (p < 1 || p > totalPages.value) return; page.value = p; load() }
const jumpPage = ref(1)
function doJump() {
  const p = Math.max(1, Math.min(totalPages.value, Math.round(jumpPage.value)))
  if (p !== page.value) go(p)
}

let searchTimer = null
function onSearchInput() { clearTimeout(searchTimer); searchTimer = setTimeout(() => load(true), 280) }
const hasActiveFilters = computed(() => !!(filters.q || filters.level || filters.dept || filters.status || Object.keys(colFilters).length))
function resetFilters() {
  filters.q = ''; filters.level = ''; filters.dept = ''; filters.status = ''
  Object.keys(colFilters).forEach(k => delete colFilters[k])
  sortKey.value = 'outstanding'; sortDir.value = 'desc'
  load(true)
}

// 服务端排序：跨所有分页生效（点表头切换字段/方向并回到第1页重新取数）
function setSort(k) {
  if (sortKey.value === k) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  else { sortKey.value = k; sortDir.value = 'desc' }
  load(true)
}
function sortArrow(k) { return sortKey.value === k ? (sortDir.value === 'desc' ? ' ↓' : ' ↑') : '' }

// 通用筛选方案（表格方案基座）：列头筛选 + 排序(sortKey/sortDir) + 顶部等级/部门/状态筛选
const schemes = useTableSchemes('ar_customers', {
  colFilters, sortField: sortKey, sortOrder: sortDir,
  extra: {
    get: () => ({ level: filters.level, dept: filters.dept, status: filters.status }),
    set: (p) => { filters.level = p.level || ''; filters.dept = p.dept || ''; filters.status = p.status || '' },
  },
  onApply: () => { load(true) },
})

async function openDetail(c) {
  drawerOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const res = await ar.getCustomer(c.id)
    detail.value = res.data
    await nextTick()
    const drawerEl = document.querySelector('.drawer')
    if (drawerEl) {
      const closeBtn = drawerEl.querySelector('.dw-close')
      if (closeBtn) closeBtn.focus()
    }
  } catch (e) { showToast(e?.error || '加载失败') }
  finally { detailLoading.value = false }
}
function closeDrawer() { drawerOpen.value = false; detail.value = null }

function trapTab(e) {
  const el = e.currentTarget
  const focusable = [...el.querySelectorAll('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])')].filter(x => !x.disabled)
  if (!focusable.length) { e.preventDefault(); return }
  const first = focusable[0], last = focusable[focusable.length - 1]
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
}

function openCreate() {
  Object.assign(editForm, { id: null, name: '', delivery_dept: filters.dept || accessibleDepts.value[0] || '', level: '', status: '运作中', contact: '', customer_date: todayCST(), notes: '', push_status: false })
  showEdit.value = true
}
function openEditFromDetail() {
  const d = detail.value
  Object.assign(editForm, { id: d.id, name: d.name, delivery_dept: d.delivery_dept || '', level: d.level || '', status: d.status || '运作中', contact: d.contact || '', customer_date: d.customer_date || '', notes: d.notes || '', push_status: false })
  showEdit.value = true
}
// 从客户详情直接改某个项目的状态（项目状态各自独立，两边同步同一字段）
async function changeProjStatus(p) {
  try {
    await ar.updateProject(p.id, { status: p.status })
    showToast(`✓ 项目「${p.short_name}」状态改为${p.status}`)
  } catch (e) { showToast(e?.error || '改状态失败') }
}
async function saveCustomer() {
  if (!editForm.name.trim()) return showToast('客户名称不能为空')
  if (!editForm.id && !editForm.delivery_dept) return showToast('请选择客户所属事业部（客户按事业部隔离）')
  saving.value = true
  try {
    if (editForm.id) {
      await ar.updateCustomer(editForm.id, editForm)
      if (detail.value && detail.value.id === editForm.id) Object.assign(detail.value, { name: editForm.name, level: editForm.level, status: editForm.status, contact: editForm.contact, customer_date: editForm.customer_date, notes: editForm.notes })
      showToast(editForm.push_status ? '✓ 已保存并下发状态到名下项目' : '✓ 已保存')
    } else {
      await ar.createCustomer(editForm)
      showToast('✓ 已创建')
    }
    showEdit.value = false
    await load()
  } catch (e) { showToast(e?.error || '保存失败') }
  finally { saving.value = false }
}

onMounted(async () => {
  const applied = await schemes.loadAndApplyDefault()
  if (!applied) load(true)
})
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>客户管理</h1>
        <div class="sub">客户 · 绑定项目与应收 — 列表即看板，未收 / 逾期一目了然；点客户看其全部项目损益与回款</div>
      </div>
      <div class="topbar-actions">
        <button v-if="auth.canArWrite" class="btn btn-sm" :disabled="syncing" @click="syncFromProjects"
                title="把项目台账里有客户名称、但还没建客户的项目，自动补建客户并挂接">
          {{ syncing ? '同步中…' : '⟳ 同步项目客户' }}
        </button>
        <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" @click="openCreate">+ 新增客户</button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filter-strip">
      <div class="search-box">
        <input v-model="filters.q" class="search-input" placeholder="🔍 全局搜索：客户名称 / 联系人 / 备注"
               @input="onSearchInput" @keyup.enter="load(true)" />
        <button v-if="filters.q" class="search-clear" @click="filters.q=''; load(true)">✕</button>
      </div>
      <button v-if="hasActiveFilters" class="filter-reset" @click="resetFilters">清除全部筛选</button>
      <SchemePicker :ctl="schemes" :can-public="auth.canArWrite" :is-super-admin="auth.isSuperAdmin" />
<div class="spacer"></div>
      <div class="count-tip">共 {{ total }} 个客户</div>
    </div>

    <!-- 批量打等级工具条（勾选客户后出现）-->
    <div v-if="selected.size" class="bulk-bar">
      <span class="bb-count">已选 <b>{{ selected.size }}</b> 个客户</span>
      <span class="bb-label">批量设为</span>
      <select v-model="bulkLevel" class="bb-sel">
        <option value="">未分级（清空）</option>
        <option v-for="l in LEVELS" :key="l" :value="l">{{ l }}</option>
      </select>
      <button class="btn btn-primary btn-sm" :disabled="bulkSaving" @click="applyBulkLevel">{{ bulkSaving ? '应用中…' : '应用' }}</button>
      <button v-if="auth.canDelete" class="bb-del" :disabled="bulkDeleting" @click="bulkDeleteCustomers">
        {{ bulkDeleting ? '删除中…' : `删除选中(${selected.size})` }}
      </button>
      <button class="btn btn-sm" @click="clearSel">取消选择</button>
    </div>

    <!-- 客户列表 -->
    <div class="card fh-fill" :class="{ 'data-reloading': loading && items.length }">
      <div class="table-wrap page-scroll">
        <table class="cu-table">
          <thead>
            <tr>
              <th class="ctr chk-col sticky-col"><input type="checkbox" :checked="allOnPageSelected" @change="toggleSelAll" title="全选本页" /></th>
              <th class="l sticky-col" :style="cw.thStyle('name')">
                <ColumnFilter label="客户名称" field="name" type="text" :model-value="colFilters.name" :sort-field="sortKey" :sort-order="sortDir" @update:model-value="v=>setColFilter('name',v)" @sort="o=>setColSort('name',o)" />
                <div class="col-rh" @mousedown.stop="cw.startDrag($event, 'name')"></div>
              </th>
              <th class="ctr"><ColumnFilter label="状态" field="status" type="enum" :options="STATUSES" :model-value="colFilters.status" :sort-field="sortKey" :sort-order="sortDir" @update:model-value="v=>setColFilter('status',v)" @sort="o=>setColSort('status',o)" /></th>
              <th class="ctr"><ColumnFilter label="等级" field="level" type="enum" :options="LEVELS" :model-value="colFilters.level" :sort-field="sortKey" :sort-order="sortDir" @update:model-value="v=>setColFilter('level',v)" @sort="o=>setColSort('level',o)" /></th>
              <th class="l"><ColumnFilter label="事业部" field="delivery_dept" type="enum" :options="accessibleDepts" :model-value="colFilters.delivery_dept" :sort-field="sortKey" :sort-order="sortDir" @update:model-value="v=>setColFilter('delivery_dept',v)" @sort="o=>setColSort('delivery_dept',o)" /></th>
              <th class="ctr"><ColumnFilter label="项目数" field="project_count" :filterable="false" :sort-field="sortKey" :sort-order="sortDir" @sort="o=>setColSort('project_count',o)" /></th>
              <th class="rgt"><ColumnFilter label="累计开票" field="invoiced" :filterable="false" :sort-field="sortKey" :sort-order="sortDir" @sort="o=>setColSort('invoiced',o)" /></th>
              <th class="rgt"><ColumnFilter label="未收金额" field="outstanding" :filterable="false" :sort-field="sortKey" :sort-order="sortDir" @sort="o=>setColSort('outstanding',o)" /></th>
              <th class="rgt"><ColumnFilter label="逾期金额" field="overdue" :filterable="false" :sort-field="sortKey" :sort-order="sortDir" @sort="o=>setColSort('overdue',o)" /></th>
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-if="loading && !items.length">
              <SkeletonRow v-for="n in 8" :key="n" :cols="10" />
            </template>
            <tr v-else-if="loadErr">
              <td colspan="10" class="empty">⚠️ {{ loadErr }} <button class="btn-link" @click="load()">重试</button></td>
            </tr>
            <tr v-else-if="!loading && !items.length"><td colspan="10" class="empty">暂无客户数据</td></tr>
            <tr v-for="c in items" :key="c.id" class="row" :class="{ sel: selected.has(c.id) }" @click="openDetail(c)">
              <td class="ctr chk-col sticky-col" @click.stop><input type="checkbox" :checked="selected.has(c.id)" @change="toggleSel(c.id)" /></td>
              <td class="l name sticky-col" :style="cw.thStyle('name')" :title="c.name + (c.contact ? ' · ' + c.contact : '')">{{ c.name }}<span v-if="c.contact" class="contact">· {{ c.contact }}</span></td>
              <td class="ctr"><span class="st-pill" :class="statusClass(c.status)">{{ c.status || '运作中' }}</span></td>
              <td class="ctr"><span v-if="c.level" class="lvl" :class="levelClass(c.level)">{{ c.level }}</span><span v-else class="muted">—</span></td>
              <td class="l dept-cell" :title="c.delivery_dept || ''">{{ c.delivery_dept || '—' }}</td>
              <td class="ctr">{{ c.project_count ?? 0 }}</td>
              <td class="rgt">{{ wan(c.invoiced) }}</td>
              <td class="rgt strong">{{ wan(c.outstanding) }}</td>
              <td class="rgt"><span :class="{ overdue: (c.overdue||0) > 0 }">{{ wan(c.overdue) }}</span></td>
              <td class="ctr"><button class="btn-link" @click.stop="openDetail(c)">查看 ›</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="total > size" class="cu-pager">
        <button :disabled="page <= 1" class="page-btn" @click="go(page - 1)">‹ 上一页</button>
        <span class="page-info">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 个客户</span>
        <button :disabled="page >= totalPages" class="page-btn" @click="go(page + 1)">下一页 ›</button>
        <span class="pg-jump">跳至<input v-model.number="jumpPage" class="pg-jump-input" type="number" min="1" :max="totalPages" :placeholder="`1-${totalPages}`" @keyup.enter="doJump" />页<button class="page-btn" @click="doJump">Go</button></span>
      </div>
    </div>

    <!-- 客户详情抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="drawerOpen" class="drawer-mask" @click.self="closeDrawer">
          <div class="drawer" tabindex="-1" @keydown.tab.capture="trapTab" @keydown.escape="closeDrawer">
            <div class="dw-head">
              <div>
                <div class="dw-title">{{ detail?.name || '加载中…' }}
                  <span v-if="detail?.level" class="lvl" :class="levelClass(detail.level)">{{ detail.level }}</span>
                </div>
                <div v-if="detail?.contact || detail?.notes || detail?.customer_date || detail?.created_at" class="dw-sub">
                  <span v-if="detail.contact">联系人：{{ detail.contact }}</span>
                  <span>建档日期：{{ fmtDate(detail.customer_date || detail.created_at) }}</span>
                  <span v-if="detail.notes" class="dw-notes">{{ detail.notes }}</span>
                </div>
              </div>
              <div class="dw-head-actions">
                <button v-if="auth.canArWrite && detail" class="btn btn-sm" @click="openEditFromDetail">编辑</button>
                <button class="dw-close" @click="closeDrawer">✕</button>
              </div>
            </div>

            <div v-if="detailLoading" class="dw-loading">加载中…</div>
            <template v-else-if="detail">
              <!-- KPI 条 -->
              <div class="dw-kpis">
                <div class="dw-kpi"><div class="k-label">项目数</div><div class="k-val">{{ detail.stats.project_count }}</div></div>
                <div class="dw-kpi"><div class="k-label">累计开票</div><div class="k-val">{{ wan(detail.stats.invoiced) }}</div></div>
                <div class="dw-kpi"><div class="k-label">已收</div><div class="k-val green">{{ wan(detail.stats.collected) }}</div></div>
                <div class="dw-kpi"><div class="k-label">未收</div><div class="k-val">{{ wan(detail.stats.outstanding) }}</div></div>
                <div class="dw-kpi"><div class="k-label">逾期</div><div class="k-val" :class="{ red: detail.stats.overdue > 0 }">{{ wan(detail.stats.overdue) }}</div></div>
              </div>

              <!-- 项目列表 -->
              <div class="dw-section-title">绑定项目 <span class="tip">点项目查看全链路损益与回款</span></div>
              <div v-if="!detail.projects.length" class="dw-empty">该客户暂无关联项目</div>
              <table v-else class="dw-proj-table">
                <thead>
                  <tr><th class="l">项目</th><th class="ctr">状态</th><th class="rgt">开票</th><th class="rgt">未收</th><th class="rgt">逾期</th></tr>
                </thead>
                <tbody>
                  <tr v-for="p in detail.projects" :key="p.id" class="proj-row">
                    <td class="l" @click="pnlName = p.short_name || p.customer_name">{{ p.short_name || p.customer_name }}<span class="drill">损益 ›</span></td>
                    <td class="ctr" @click.stop>
                      <select v-if="auth.canArWrite" v-model="p.status" class="proj-st-sel" :class="statusClass(p.status)" @change="changeProjStatus(p)">
                        <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
                      </select>
                      <span v-else class="st-pill" :class="statusClass(p.status)">{{ p.status }}</span>
                    </td>
                    <td class="rgt" @click="pnlName = p.short_name || p.customer_name">{{ wan(p.invoiced) }}</td>
                    <td class="rgt strong" @click="pnlName = p.short_name || p.customer_name">{{ wan(p.outstanding) }}</td>
                    <td class="rgt" @click="pnlName = p.short_name || p.customer_name"><span :class="{ overdue: p.overdue > 0 }">{{ wan(p.overdue) }}</span></td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 项目损益卡 -->
    <ProjectPnlCard v-if="pnlName" :name="pnlName" :year="year" @close="pnlName = ''" />

    <!-- 编辑/新建客户 -->
    <Teleport to="body">
      <div v-if="showEdit" class="edit-mask" @click.self="showEdit = false">
        <div class="edit-modal">
          <div class="em-title">{{ editForm.id ? '编辑客户' : '新增客户' }}</div>
          <label class="em-label">客户名称</label>
          <input v-model="editForm.name" class="em-input" placeholder="客户公司名称" />
          <label class="em-label">所属事业部 <span style="color:#c0392b">*</span><span style="font-weight:400;color:#9b8070">（客户按事业部隔离，同名客户在不同部门相互独立）</span></label>
          <select v-model="editForm.delivery_dept" class="em-input" :disabled="!!editForm.id">
            <option value="">未指定</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <div class="em-row">
            <div style="flex:1">
              <label class="em-label">状态</label>
              <select v-model="editForm.status" class="em-input">
                <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
              </select>
            </div>
            <div style="flex:1">
              <label class="em-label">等级</label>
              <select v-model="editForm.level" class="em-input">
                <option value="">未分级</option>
                <option v-for="l in LEVELS" :key="l" :value="l">{{ l }}</option>
              </select>
            </div>
            <div style="flex:1">
              <label class="em-label">建档日期</label>
              <input v-model="editForm.customer_date" type="date" class="em-input" />
            </div>
            <div style="flex:1">
              <label class="em-label">联系人</label>
              <input v-model="editForm.contact" class="em-input" placeholder="联系人 / 电话" />
            </div>
          </div>
          <label v-if="editForm.id" class="em-push">
            <input type="checkbox" v-model="editForm.push_status" />
            <span>保存时把「{{ editForm.status }}」状态一键下发到该客户名下所有项目（项目状态各自独立，不勾选则只改客户）</span>
          </label>
          <label class="em-label">备注</label>
          <textarea v-model="editForm.notes" class="em-textarea" rows="2" placeholder="备注（可选）" />
          <div class="em-actions">
            <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveCustomer">{{ saving ? '保存中…' : '保存' }}</button>
            <button class="btn btn-sm" @click="showEdit = false">取消</button>
          </div>
        </div>
      </div>
    </Teleport>

    <Transition name="toast"><div v-if="toast" class="cu-toast">{{ toast }}</div></Transition>
  </div>
</template>

<style scoped>
.topbar { display: flex; justify-content: space-between; align-items: flex-start; }
.topbar-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.cu-table td.date { color: #9b8070; font-size: 12px; white-space: nowrap; }
.cu-table td.dept-cell { font-size: 12px; color: #6b5a4a; }
.cu-pager { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 14px 0 4px; }
.cu-pager .page-btn { padding: 5px 14px; border: 1px solid #d4b896; border-radius: 8px; background: #fff; color: #4a3728; font-size: 13px; cursor: pointer; }
.cu-pager .page-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.cu-pager .page-btn:disabled { opacity: .4; cursor: default; }
.cu-pager .page-info { font-size: 12.5px; color: #9b8070; }
.pg-jump{display:inline-flex;align-items:center;gap:4px;font-size:13px;color:var(--muted);margin-left:8px}
.pg-jump-input{width:46px;text-align:center;padding:2px 4px;border:1px solid var(--border);border-radius:6px;font-size:13px}
.sub { font-size: 13px; color: var(--muted); margin-top: 2px; }

.filter-strip { display: flex; align-items: center; gap: 10px; margin: 14px 0; }
.spacer { flex: 1; }
.count-tip { font-size: 12px; color: var(--muted); }

/* 批量打标工具条 */
.bulk-bar { display: flex; align-items: center; gap: 10px; margin: 0 0 12px; padding: 10px 14px;
  background: linear-gradient(120deg, rgba(21,101,192,.08), rgba(46,125,50,.06));
  border: 1px solid rgba(21,101,192,.22); border-radius: 10px; }
.bb-count { font-size: 13px; color: #3a2c1d; }
.bb-count b { color: #1565c0; }
.bb-label { font-size: 12px; color: #9b8070; margin-left: 4px; }
.bb-sel { padding: 5px 10px; border: 1px solid #d4b896; border-radius: 7px; background: #fff; font-size: 13px; }
.bb-del { margin-left: auto; padding: 5px 12px; border: 1px solid rgba(198,40,40,.45); border-radius: 7px;
  background: rgba(198,40,40,.06); color: #c62828; font-size: 12.5px; font-weight: 700; cursor: pointer; }
.bb-del:hover:not(:disabled) { background: rgba(198,40,40,.13); }
.bb-del:disabled { opacity: .5; cursor: not-allowed; }
.chk-col { width: 36px; }
.chk-col input { cursor: pointer; }
.row.sel td { background: rgba(21,101,192,.06); }

.cu-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cu-table th { background: #f3ede6; color: #6b5a4a; padding: 9px 14px; font-weight: 600; white-space: nowrap; text-align: right; overflow: visible; }
/* 固定视口：表头吸顶，仅表体内部滚动 */
.table-wrap thead th { position: sticky; top: 0; z-index: 5; background: #f3ede6; }
.cu-pager { flex-shrink: 0; }
.cu-table th.l { text-align: left; }
.cu-table th.ctr { text-align: center; }
.cu-table th.clk { cursor: pointer; user-select: none; }
.cu-table th.clk:hover { color: var(--primary); }
/* 单元格强制单行：行高不随列宽变化，从设计上杜绝「滚动条↔换行↔高度」回流抖动 */
.cu-table td { padding: 10px 14px; border-bottom: 1px solid #f0e8de; text-align: right; color: #2d2010; white-space: nowrap; }
/* 长文本列截断+省略号（完整内容见悬停提示），保持列宽稳定与排版整洁 */
.cu-table td.name { max-width: 240px; overflow: hidden; text-overflow: ellipsis; }
.cu-table td.dept-cell { max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.cu-table td.l { text-align: left; }
.cu-table td.ctr { text-align: center; }
.row { cursor: pointer; }
.row:hover td { background: #faf5ef; }
.name { font-weight: 600; color: #4a3728; }
.contact { font-weight: 400; font-size: 12px; color: #9b8070; margin-left: 6px; }
.strong { font-weight: 700; }
.overdue { color: #c62828; font-weight: 700; }
.muted { color: #c9b8a8; }
.empty { text-align: center; color: #9e9e9e; padding: 40px; }
.btn-link { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 12.5px; }

.st-pill { display: inline-block; padding: 1px 8px; border-radius: 9px; font-size: 11px; font-weight: 600; }
.st-on { background: #e8f5e9; color: #2e7d32; }
.st-pause { background: #fff3e0; color: #e65100; }
.st-end { background: #f3f3f3; color: #9e9e9e; }
.proj-st-sel { font-size: 11px; border: 1px solid #d4b896; border-radius: 7px; padding: 1px 4px; cursor: pointer; background: #fff; }
.proj-st-sel.st-on { color: #2e7d32; } .proj-st-sel.st-pause { color: #e65100; } .proj-st-sel.st-end { color: #9e9e9e; }
.em-push { display: flex; align-items: flex-start; gap: 6px; font-size: 11.5px; color: #6b5a4a; margin: 10px 0 4px; line-height: 1.4; cursor: pointer; }
.em-push input { margin-top: 2px; }
.lvl { display: inline-block; min-width: 18px; padding: 1px 7px; border-radius: 9px; font-size: 11px; font-weight: 700; color: #fff; }
.lvl-S { background: #6a1b9a; } .lvl-A { background: #2e7d32; } .lvl-B { background: #1565c0; } .lvl-C { background: #e65100; } .lvl-D { background: #9e9e9e; }

/* 抽屉 */
.drawer-mask { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 3000; display: flex; justify-content: flex-end; }
.drawer { width: 620px; max-width: 94vw; height: 100%; background: #fdfbf8; box-shadow: -8px 0 30px rgba(0,0,0,.18); overflow-y: auto; padding: 22px 24px; }
.dw-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid #eee2d4; }
.dw-title { font-size: 19px; font-weight: 800; color: #3a2c1d; display: flex; align-items: center; gap: 8px; }
.dw-sub { font-size: 12.5px; color: #9b8070; margin-top: 5px; display: flex; gap: 12px; flex-wrap: wrap; }
.dw-notes { color: #b0a090; }
.dw-head-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.dw-close { border: none; background: none; font-size: 18px; color: #9b8070; cursor: pointer; line-height: 1; }
.dw-loading, .dw-empty { text-align: center; color: #9e9e9e; padding: 30px; }

.dw-kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; margin: 16px 0; background: #fff; border: 1px solid #eee2d4; border-radius: 10px; overflow: hidden; }
.dw-kpi { padding: 12px; text-align: center; border-right: 1px solid #f0e8de; }
.dw-kpi:last-child { border-right: none; }
.k-label { font-size: 11px; color: #9b8070; margin-bottom: 4px; }
.k-val { font-size: 17px; font-weight: 800; color: #2d2010; }
.k-val.green { color: #2e7d32; } .k-val.red { color: #c62828; }

.dw-section-title { font-size: 14px; font-weight: 700; color: #4a3728; margin: 18px 0 8px; }
.tip { font-size: 11px; font-weight: 400; color: #9b8070; margin-left: 6px; }
.dw-proj-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.dw-proj-table th { background: #f3ede6; color: #6b5a4a; padding: 7px 10px; font-weight: 600; text-align: right; }
.dw-proj-table th.l { text-align: left; }
.dw-proj-table td { padding: 8px 10px; border-bottom: 1px solid #f3ece2; text-align: right; }
.dw-proj-table td.l { text-align: left; font-weight: 600; color: #4a3728; }
.proj-row { cursor: pointer; }
.proj-row:hover td { background: #faf5ef; }
.drill { font-size: 11px; color: var(--primary); margin-left: 6px; opacity: 0; transition: opacity .15s; }
.proj-row:hover .drill { opacity: 1; }
.dept { color: #9b8070; }

/* 编辑弹窗 */
.edit-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 4000; display: flex; align-items: center; justify-content: center; }
.edit-modal { background: #fff; border-radius: 14px; padding: 24px; width: 440px; max-width: 95vw; box-shadow: 0 20px 60px rgba(0,0,0,.25); }
.em-title { font-size: 16px; font-weight: 700; color: #4a3728; margin-bottom: 14px; }
.em-label { display: block; font-size: 12px; color: #9b8070; margin: 8px 0 4px; }
.em-input, .em-textarea { width: 100%; padding: 7px 10px; border: 1px solid #d4b896; border-radius: 7px; font-size: 13px; box-sizing: border-box; }
.em-textarea { resize: vertical; }
.em-row { display: flex; gap: 10px; }
.em-actions { display: flex; gap: 8px; margin-top: 16px; }

.cu-toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: #2e7d32; color: #fff; padding: 8px 20px; border-radius: 20px; font-size: 13px; z-index: 8000; }
.drawer-enter-active, .drawer-leave-active { transition: opacity .2s; }
.drawer-enter-active .drawer, .drawer-leave-active .drawer { transition: transform .25s ease; }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer, .drawer-leave-to .drawer { transform: translateX(40px); }
.toast-enter-active, .toast-leave-active { transition: opacity .2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; }

@media (max-width: 640px) {
  .dw-kpis { grid-template-columns: repeat(3, 1fr); }
}

/* 列宽拖拽柄 */
.cu-table th { position: relative; }
.col-rh {
  position: absolute; right: 0; top: 0; bottom: 0; width: 5px;
  cursor: col-resize; opacity: 0; transition: opacity 0.15s;
}
.col-rh:hover, .col-rh:active { opacity: 1; background: rgba(201,99,66,0.4); }
.cu-table th:hover .col-rh { opacity: 0.35; }

/* 冻结首列 */
.sticky-col { position: sticky; left: 0; z-index: 3; background: #f3ede6; }
.cu-table tbody tr td.sticky-col { background: #fdfbf8; }
.cu-table tbody tr:hover td.sticky-col { background: #faf5ef; }
/* 选中态用实色，避免右滚时透出下层内容 */
.cu-table tbody tr.sel td.sticky-col { background: #eef2f7; }
</style>
