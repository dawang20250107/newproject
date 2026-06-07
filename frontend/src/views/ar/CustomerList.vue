<script setup>
import { ref, reactive, computed, onMounted, defineAsyncComponent } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { yearCST } from '../../constants.js'
import ar from '../../api/ar.js'

// 项目损益卡（复用 P1 组件）— 点客户项目即下钻全链路损益
const ProjectPnlCard = defineAsyncComponent(() => import('../caiwu/ProjectPnlCard.vue'))

const auth = useAuthStore()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = 50
const filters = reactive({ q: '', level: '' })

// 排序（当前页客户端排序：未收/逾期最常用）
const sortKey = ref('outstanding')
const sortDir = ref('desc')

// 详情抽屉
const detail = ref(null)        // 客户详情数据
const detailLoading = ref(false)
const drawerOpen = ref(false)

// 编辑/新建
const showEdit = ref(false)
const editForm = reactive({ id: null, name: '', level: '', contact: '', notes: '' })
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

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const res = await ar.listCustomers({ ...filters, page: page.value, size })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

let searchTimer = null
function onSearchInput() { clearTimeout(searchTimer); searchTimer = setTimeout(() => load(true), 280) }
const hasActiveFilters = computed(() => !!(filters.q || filters.level))
function resetFilters() { filters.q = ''; filters.level = ''; load(true) }

const sortedItems = computed(() => {
  const arr = [...items.value]
  const k = sortKey.value, dir = sortDir.value === 'desc' ? -1 : 1
  arr.sort((a, b) => {
    const av = a[k] ?? -Infinity, bv = b[k] ?? -Infinity
    if (typeof av === 'string') return av.localeCompare(bv) * dir
    return (av - bv) * dir
  })
  return arr
})
function setSort(k) {
  if (sortKey.value === k) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  else { sortKey.value = k; sortDir.value = 'desc' }
}
function sortArrow(k) { return sortKey.value === k ? (sortDir.value === 'desc' ? ' ↓' : ' ↑') : '' }

async function openDetail(c) {
  drawerOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const res = await ar.getCustomer(c.id)
    detail.value = res.data
  } catch (e) { showToast(e?.error || '加载失败') }
  finally { detailLoading.value = false }
}
function closeDrawer() { drawerOpen.value = false; detail.value = null }

function openCreate() {
  Object.assign(editForm, { id: null, name: '', level: '', contact: '', notes: '' })
  showEdit.value = true
}
function openEditFromDetail() {
  const d = detail.value
  Object.assign(editForm, { id: d.id, name: d.name, level: d.level || '', contact: d.contact || '', notes: d.notes || '' })
  showEdit.value = true
}
async function saveCustomer() {
  if (!editForm.name.trim()) return showToast('客户名称不能为空')
  saving.value = true
  try {
    if (editForm.id) {
      await ar.updateCustomer(editForm.id, editForm)
      if (detail.value && detail.value.id === editForm.id) Object.assign(detail.value, { name: editForm.name, level: editForm.level, contact: editForm.contact, notes: editForm.notes })
      showToast('✓ 已保存')
    } else {
      await ar.createCustomer(editForm)
      showToast('✓ 已创建')
    }
    showEdit.value = false
    await load()
  } catch (e) { showToast(e?.error || '保存失败') }
  finally { saving.value = false }
}

onMounted(() => load(true))
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>客户管理</h1>
        <div class="sub">客户 · 绑定项目与应收 — 列表即看板，未收 / 逾期一目了然；点客户看其全部项目损益与回款</div>
      </div>
      <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增客户</button>
    </div>

    <!-- 筛选 -->
    <div class="filter-strip">
      <div class="search-box">
        <input v-model="filters.q" class="search-input" placeholder="搜索客户名称 / 联系人 / 备注"
               @input="onSearchInput" @keyup.enter="load(true)" />
        <button v-if="filters.q" class="search-clear" @click="filters.q=''; load(true)">✕</button>
      </div>
      <select v-model="filters.level" class="sel-bu" @change="load(true)">
        <option value="">全部等级</option>
        <option v-for="l in LEVELS" :key="l" :value="l">{{ l }}</option>
      </select>
      <button v-if="hasActiveFilters" class="filter-reset" @click="resetFilters">重置筛选</button>
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
      <button class="btn btn-sm" @click="clearSel">取消选择</button>
    </div>

    <!-- 客户列表 -->
    <div class="card" :class="{ 'data-reloading': loading && items.length }">
      <div class="table-wrap">
        <table class="cu-table">
          <thead>
            <tr>
              <th class="ctr chk-col"><input type="checkbox" :checked="allOnPageSelected" @change="toggleSelAll" title="全选本页" /></th>
              <th class="l">客户名称</th>
              <th class="ctr">等级</th>
              <th class="ctr clk" @click="setSort('project_count')">项目数{{ sortArrow('project_count') }}</th>
              <th class="rgt clk" @click="setSort('invoiced')">累计开票{{ sortArrow('invoiced') }}</th>
              <th class="rgt clk" @click="setSort('outstanding')">未收金额{{ sortArrow('outstanding') }}</th>
              <th class="rgt clk" @click="setSort('overdue')">逾期金额{{ sortArrow('overdue') }}</th>
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!loading && !items.length"><td colspan="8" class="empty">暂无客户数据</td></tr>
            <tr v-for="c in sortedItems" :key="c.id" class="row" :class="{ sel: selected.has(c.id) }" @click="openDetail(c)">
              <td class="ctr chk-col" @click.stop><input type="checkbox" :checked="selected.has(c.id)" @change="toggleSel(c.id)" /></td>
              <td class="l name">{{ c.name }}<span v-if="c.contact" class="contact">· {{ c.contact }}</span></td>
              <td class="ctr"><span v-if="c.level" class="lvl" :class="levelClass(c.level)">{{ c.level }}</span><span v-else class="muted">—</span></td>
              <td class="ctr">{{ c.project_count ?? 0 }}</td>
              <td class="rgt">{{ wan(c.invoiced) }}</td>
              <td class="rgt strong">{{ wan(c.outstanding) }}</td>
              <td class="rgt"><span :class="{ overdue: (c.overdue||0) > 0 }">{{ wan(c.overdue) }}</span></td>
              <td class="ctr"><button class="btn-link" @click.stop="openDetail(c)">查看 ›</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 客户详情抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="drawerOpen" class="drawer-mask" @click.self="closeDrawer">
          <div class="drawer">
            <div class="dw-head">
              <div>
                <div class="dw-title">{{ detail?.name || '加载中…' }}
                  <span v-if="detail?.level" class="lvl" :class="levelClass(detail.level)">{{ detail.level }}</span>
                </div>
                <div v-if="detail?.contact || detail?.notes" class="dw-sub">
                  <span v-if="detail.contact">联系人：{{ detail.contact }}</span>
                  <span v-if="detail.notes" class="dw-notes">{{ detail.notes }}</span>
                </div>
              </div>
              <div class="dw-head-actions">
                <button v-if="auth.canCreate && detail" class="btn btn-sm" @click="openEditFromDetail">编辑</button>
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
                  <tr><th class="l">项目</th><th>部门</th><th class="rgt">开票</th><th class="rgt">未收</th><th class="rgt">逾期</th></tr>
                </thead>
                <tbody>
                  <tr v-for="p in detail.projects" :key="p.id" class="proj-row" @click="pnlName = p.short_name || p.customer_name">
                    <td class="l">{{ p.short_name || p.customer_name }}<span class="drill">损益 ›</span></td>
                    <td class="dept">{{ p.delivery_dept }}</td>
                    <td class="rgt">{{ wan(p.invoiced) }}</td>
                    <td class="rgt strong">{{ wan(p.outstanding) }}</td>
                    <td class="rgt"><span :class="{ overdue: p.overdue > 0 }">{{ wan(p.overdue) }}</span></td>
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
          <div class="em-row">
            <div style="flex:1">
              <label class="em-label">等级</label>
              <select v-model="editForm.level" class="em-input">
                <option value="">未分级</option>
                <option v-for="l in LEVELS" :key="l" :value="l">{{ l }}</option>
              </select>
            </div>
            <div style="flex:2">
              <label class="em-label">联系人</label>
              <input v-model="editForm.contact" class="em-input" placeholder="联系人 / 电话" />
            </div>
          </div>
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
.chk-col { width: 36px; }
.chk-col input { cursor: pointer; }
.row.sel td { background: rgba(21,101,192,.06); }

.cu-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cu-table th { background: #f3ede6; color: #6b5a4a; padding: 9px 14px; font-weight: 600; white-space: nowrap; text-align: right; }
.cu-table th.l { text-align: left; }
.cu-table th.ctr { text-align: center; }
.cu-table th.clk { cursor: pointer; user-select: none; }
.cu-table th.clk:hover { color: var(--primary); }
.cu-table td { padding: 10px 14px; border-bottom: 1px solid #f0e8de; text-align: right; color: #2d2010; }
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
</style>
