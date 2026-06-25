<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact, fmtMoney } from '../../utils/format.js'
import ProjectPnlCard from './ProjectPnlCard.vue'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import { useToast } from '../../composables/useToast.js'

const toast = useToast()

const auth = useAuthStore()
const loading = ref(false)
const data = ref(null)
const err = ref('')

const filters = reactive({
  dept: '',
  year: yearCST(),
  date_start: '',
  date_end: '',
  useCustomDate: false,
})

// 聚合维度：项目 / 二级部门。后端 _CASHFLOW_DIMS 登记新维度后在此追加即可。
const DIMS = [
  { v: 'project', l: '项目' },
  { v: 'secondary_dept', l: '二级部门' },
]
const groupBy = ref('project')
const isProjDim = computed(() => groupBy.value === 'project')

const sortKey = ref('net')        // net | inflow | outflow | outstanding
const sortDesc = ref(true)
const search = ref('')
const askTarget = ref(null)       // { name, tag_label } for ProjectPnlCard

const fmtWan = v => fmtCompact(v, { decimals: 1, smallRound: true, dash: '0' })
const fmtPct = (num, den) => den ? `${(num / den * 100).toFixed(1)}%` : '—'

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

// Quick date presets（收进单个下拉，省横向空间）
// 工具：本地日期 -> YYYY-MM-DD；某月最后一天
const pad2 = n => String(n).padStart(2, '0')
const ymd = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
const lastDayOfMonth = (y, m0) => new Date(y, m0 + 1, 0).getDate()  // m0：0-based 月
// 给定基准日往前 n 天的区间（含今天）
const lastNDays = n => {
  const end = new Date()
  const start = new Date(); start.setDate(start.getDate() - (n - 1))
  return { date_start: ymd(start), date_end: ymd(end) }
}
const PRESETS = [
  { k: 'year', l: '今年', f: () => ({ date_start: `${filters.year}-01-01`, date_end: `${filters.year}-12-31` }) },
  { k: 'h1', l: '上半年', f: () => ({ date_start: `${filters.year}-01-01`, date_end: `${filters.year}-06-30` }) },
  { k: 'h2', l: '下半年', f: () => ({ date_start: `${filters.year}-07-01`, date_end: `${filters.year}-12-31` }) },
  { k: 'month', l: '本月', f: () => {
    const d = new Date(); const y = d.getFullYear(); const m0 = d.getMonth()
    return { date_start: `${y}-${pad2(m0 + 1)}-01`, date_end: `${y}-${pad2(m0 + 1)}-${pad2(lastDayOfMonth(y, m0))}` }
  }},
  { k: 'lastMonth', l: '上月', f: () => {
    const now = new Date()
    const y = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear()
    const m0 = now.getMonth() === 0 ? 11 : now.getMonth() - 1
    return { date_start: `${y}-${pad2(m0 + 1)}-01`, date_end: `${y}-${pad2(m0 + 1)}-${pad2(lastDayOfMonth(y, m0))}` }
  }},
  { k: 'quarter', l: '本季度', f: () => {
    const d = new Date(); const y = d.getFullYear(); const q = Math.floor(d.getMonth() / 3)
    const ms0 = q * 3; const me0 = q * 3 + 2
    return { date_start: `${y}-${pad2(ms0 + 1)}-01`, date_end: `${y}-${pad2(me0 + 1)}-${pad2(lastDayOfMonth(y, me0))}` }
  }},
  { k: 'lastQuarter', l: '上季度', f: () => {
    const now = new Date(); const curQ = Math.floor(now.getMonth() / 3)
    const y = curQ === 0 ? now.getFullYear() - 1 : now.getFullYear()
    const q = curQ === 0 ? 3 : curQ - 1
    const ms0 = q * 3; const me0 = q * 3 + 2
    return { date_start: `${y}-${pad2(ms0 + 1)}-01`, date_end: `${y}-${pad2(me0 + 1)}-${pad2(lastDayOfMonth(y, me0))}` }
  }},
  { k: 'd30', l: '近 30 天', f: () => lastNDays(30) },
  { k: 'd90', l: '近 90 天', f: () => lastNDays(90) },
]
const rangePreset = ref('')   // '' 全年 | 预设key | 'custom'

function applyPreset(p) {
  const { date_start, date_end } = p.f()
  filters.date_start = date_start; filters.date_end = date_end
  filters.useCustomDate = true
  load()
}

function onRangeChange() {
  const v = rangePreset.value
  if (v === '') { clearCustomDate(); return }
  if (v === 'custom') {
    filters.useCustomDate = true
    if (!filters.date_start) { filters.date_start = `${filters.year}-01-01`; filters.date_end = `${filters.year}-12-31` }
    load(); return
  }
  const p = PRESETS.find(x => x.k === v)
  if (p) applyPreset(p)
}
function onDateEdit() { rangePreset.value = 'custom'; load() }

async function load() {
  loading.value = true; err.value = ''
  try {
    const params = { year: filters.year, group_by: groupBy.value }
    if (filters.dept) params.dept = filters.dept
    if (filters.useCustomDate && filters.date_start) params.date_start = filters.date_start
    if (filters.useCustomDate && filters.date_end) params.date_end = filters.date_end
    const res = await ar.projectCashflow(params)
    data.value = res.data
  } catch (e) {
    err.value = e?.msg || '加载失败'
  } finally { loading.value = false }
}

function setDim(v) {
  if (groupBy.value === v) return
  groupBy.value = v
  load()
}

function clearCustomDate() {
  filters.date_start = ''; filters.date_end = ''; filters.useCustomDate = false
  load()
}

function setSort(key) {
  if (sortKey.value === key) sortDesc.value = !sortDesc.value
  else { sortKey.value = key; sortDesc.value = true }
}

const rows = computed(() => {
  if (!data.value?.rows) return []
  let r = data.value.rows
  if (search.value.trim()) {
    const q = search.value.trim().toLowerCase()
    r = r.filter(x => x.project.toLowerCase().includes(q) || x.customer.toLowerCase().includes(q) || x.dept.toLowerCase().includes(q))
  }
  const sign = sortDesc.value ? -1 : 1
  return [...r].sort((a, b) => (a[sortKey.value] - b[sortKey.value]) * sign)
})

const summary = computed(() => data.value?.summary || {})
const netColor = v => parseFloat(v) >= 0 ? '#2e7d32' : '#c62828'

// 事业部色标：按名称稳定散列到一个柔和色相，让不同事业部的标签一眼可分
function deptStyle(name) {
  if (!name) return {}
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360
  return { background: `hsl(${h} 42% 93%)`, color: `hsl(${h} 38% 38%)`, borderColor: `hsl(${h} 40% 84%)` }
}

// 回款率：迷你进度条 + 色阶（高绿、中琥珀、低红）
const rateOf = r => (r.estimated > 0 ? (r.inflow / r.estimated) * 100 : null)
const rateColor = p => (p >= 80 ? '#2e7d32' : p >= 50 ? '#e65100' : '#c62828')

const totals = computed(() => rows.value.reduce((t, r) => ({
  inflow: t.inflow + r.inflow, outflow: t.outflow + r.outflow,
  net: t.net + r.net, outstanding: t.outstanding + r.outstanding,
}), { inflow: 0, outflow: 0, net: 0, outstanding: 0 }))

function openPnl(row) {
  // 业财损益卡只有项目维度可下钻；二级部门维度点击切回项目维并按部门过滤
  if (!isProjDim.value) return
  askTarget.value = { name: row.project, year: filters.year }
}

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const ctx = useContextMenu()
const dimLabel = computed(() => DIMS.find(d => d.v === groupBy.value)?.l || '名称')
const ROW_COPY_COLS = computed(() => [
  { key: 'project', label: dimLabel.value },
  { key: 'inflow', label: '流入', format: v => fmtMoney(v) },
  { key: 'outflow', label: '流出', format: v => fmtMoney(v) },
  { key: 'net', label: '净流量', format: v => fmtMoney(v) },
  { key: 'outstanding', label: '未收', format: v => fmtMoney(v) },
])
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}
async function copyWholeRow(r) {
  const ok = await copyRowTSV(r, ROW_COPY_COLS.value, { header: true })
  ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')
}
const ctxItems = computed(() => {
  const r = ctx.menu.payload
  if (!r) return []
  return [
    {
      key: 'pnl', label: isProjDim.value ? '查看业财损益卡' : '业财损益卡（仅项目维度）',
      icon: 'chart', disabled: !isProjDim.value, action: row => openPnl(row),
    },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: row => copyWholeRow(row) },
        { divider: true },
        { key: 'copy-name', label: dimLabel.value + '名称', icon: 'cell', action: row => copyField(row.project, row.project) },
        { key: 'copy-net', label: '净流量', icon: 'cell', action: row => copyField(fmtMoney(row.net), fmtMoney(row.net)) },
        { key: 'copy-out', label: '未收', icon: 'cell', action: row => copyField(fmtMoney(row.outstanding), fmtMoney(row.outstanding)) },
      ],
    },
  ]
})

watch(() => [filters.dept, filters.year], () => {
  if (!filters.useCustomDate) load()
})

const route = useRoute()
onMounted(() => {
  // 资金池「查看全部」等深链带入部门预筛；dept 变化由 watch 触发加载，避免双请求
  if (route.query.group_by && DIMS.some(d => d.v === route.query.group_by)) {
    groupBy.value = String(route.query.group_by)
  }
  if (route.query.dept) { filters.dept = String(route.query.dept); return }
  load()
})
</script>

<template>
  <div class="pcf-wrap">
    <!-- 标题行：h1 + 维度 tab，对齐付款台账风格 -->
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:14px">
        <h1>项目现金流</h1>
        <div class="tab-bar">
          <button v-for="d in DIMS" :key="d.v" class="tab-btn" :class="{ active: groupBy === d.v }"
            @click="setDim(d.v)">{{ d.l }}</button>
        </div>
      </div>
    </div>

    <!-- 表格卡片 -->
    <div class="card fh-fill">
      <!-- 筛选条：对齐付款台账 filter-bar 风格 -->
      <div class="filter-bar">
        <select v-model="filters.dept" @change="filters.useCustomDate ? load() : null">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model.number="filters.year">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model="rangePreset" style="min-width:100px" @change="onRangeChange">
          <option value="">全年</option>
          <option v-for="p in PRESETS" :key="p.k" :value="p.k">{{ p.l }}</option>
          <option value="custom">自定义…</option>
        </select>
        <template v-if="filters.useCustomDate">
          <input v-model="filters.date_start" type="date" style="min-width:120px" @change="onDateEdit" />
          <span style="color:var(--muted);font-size:12px;flex-shrink:0">~</span>
          <input v-model="filters.date_end" type="date" style="min-width:120px" @change="onDateEdit" />
        </template>
        <span v-else-if="rangePreset && rangePreset !== 'custom' && filters.date_start" class="date-range-hint">
          {{ filters.date_start }} ~ {{ filters.date_end }}
        </span>
        <div class="pcf-search-wrap">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="flex-shrink:0;color:var(--muted)"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input v-model="search" class="pcf-search" placeholder="搜索项目 / 客户" />
        </div>
      </div>

      <div v-if="loading" class="pcf-empty">加载中…</div>
      <div v-else-if="err" class="pcf-empty err">{{ err }}</div>
      <div v-else-if="!rows.length" class="pcf-empty">
        {{ data ? `暂无数据（所选时段内无关联${isProjDim ? '项目简称' : '二级部门'}的回款或付款）` : '请选择筛选条件后加载' }}
      </div>

      <div v-else class="table-wrap page-scroll">
        <table class="pcf-table">
          <thead>
            <tr>
              <th class="pcf-th-proj">{{ isProjDim ? '项目' : '二级部门' }}</th>
              <th>事业部</th>
              <th class="amt sortable" :class="{ sorted: sortKey === 'inflow' }" @click="setSort('inflow')">
                回款流入 <span class="sort-arr">{{ sortKey === 'inflow' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="amt sortable" :class="{ sorted: sortKey === 'outflow' }" @click="setSort('outflow')">
                付款流出 <span class="sort-arr">{{ sortKey === 'outflow' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="amt sortable" :class="{ sorted: sortKey === 'net' }" @click="setSort('net')">
                净现金 <span class="sort-arr">{{ sortKey === 'net' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="amt sortable" :class="{ sorted: sortKey === 'outstanding' }" @click="setSort('outstanding')">
                应收敞口 <span class="sort-arr">{{ sortKey === 'outstanding' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="amt">回款率</th>
              <th v-if="isProjDim" class="ctr">详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.project" class="pcf-row" :class="{ 'no-drill': !isProjDim }" @click="openPnl(r)" @contextmenu.prevent="ctx.open($event, r)">
              <td class="pcf-td-proj">
                <div class="pcf-pname">{{ r.project }}</div>
                <div v-if="r.customer" class="pcf-psub">{{ r.customer }}</div>
              </td>
              <td><span class="dept-tag" :style="deptStyle(r.dept)">{{ r.dept || '—' }}</span></td>
              <td class="amt green fw" :class="{ 'col-on': sortKey === 'inflow' }">{{ r.inflow ? fmtWan(r.inflow) : '—' }}</td>
              <td class="amt red" :class="{ 'col-on': sortKey === 'outflow' }">{{ r.outflow ? fmtWan(r.outflow) : '—' }}</td>
              <td class="amt fw" :class="{ 'col-on': sortKey === 'net' }" :style="{ color: netColor(r.net) }">
                <span class="caret">{{ r.net >= 0 ? '▲' : '▼' }}</span>{{ fmtWan(r.net) }}
              </td>
              <td class="amt" :class="[r.outstanding > 0 ? 'amber' : 'muted', { 'col-on': sortKey === 'outstanding' }]">
                {{ r.outstanding > 0 ? fmtWan(r.outstanding) : '—' }}
              </td>
              <td class="amt">
                <div v-if="rateOf(r) !== null" class="rate-cell">
                  <span class="rate-val" :style="{ color: rateColor(rateOf(r)) }">{{ rateOf(r).toFixed(1) }}%</span>
                  <span class="rate-track"><i :style="{ width: Math.min(rateOf(r), 100) + '%', background: rateColor(rateOf(r)) }"></i></span>
                </div>
                <span v-else class="muted">—</span>
              </td>
              <td v-if="isProjDim" class="ctr">
                <button class="pcf-btn-detail" @click.stop="openPnl(r)">业财卡</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 吸底汇总：对齐付款台账的 bottom-bar。Teleport 到 body 逃脱 .card 包含块 -->
    <Teleport to="body">
      <div v-if="!loading && !err && rows.length && !askTarget" class="bottom-bar">
        <div class="bb-summary">
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#9b8070" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4-8 4-8-4 8-4z"/><path d="M4 12l8 4 8-4"/></svg>
            <i>合计</i><b>{{ rows.length }}</b> 个{{ isProjDim ? '项目' : '二级部门' }}</span>
          <span class="bb-item ok">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#2e7d32" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/></svg>
            <i>回款流入</i><b>{{ fmtWan(totals.inflow) }}</b></span>
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#c62828" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V9"/><path d="M7 14l5-5 5 5"/><path d="M5 4h14"/></svg>
            <i>付款流出</i><b style="color:#c62828">{{ fmtWan(totals.outflow) }}</b></span>
          <span class="bb-item">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#7a614c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10.5h18"/></svg>
            <i>净现金</i><b :style="{ color: netColor(totals.net) }"><span class="bb-caret">{{ totals.net >= 0 ? '▲' : '▼' }}</span>{{ fmtWan(totals.net) }}</b></span>
          <span class="bb-item warn">
            <svg class="bb-ico" viewBox="0 0 24 24" fill="none" stroke="#c0392b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 16H3z"/><path d="M12 10v4"/><path d="M12 17h.01"/></svg>
            <i>应收敞口</i><b>{{ fmtWan(totals.outstanding) }}</b></span>
        </div>
        <div class="bb-pager">
          <span class="page-info">
            <template v-if="filters.useCustomDate">{{ data?.date_start }} ~ {{ data?.date_end }}</template>
            <template v-else>{{ filters.year }} 年</template>
            · {{ filters.dept || '全部事业部' }}
          </span>
        </div>
      </div>
    </Teleport>

    <!-- ProjectPnlCard overlay -->
    <ProjectPnlCard
      v-if="askTarget"
      :name="askTarget.name"
      :year="askTarget.year"
      :askable="false"
      @close="askTarget = null"
    />

    <!-- 右键上下文菜单 -->
    <ContextMenu :ctx="ctx" :items="ctxItems" />
  </div>
</template>

<style scoped>
/* 维度 tab（对齐付款台账 .tab-bar / .tab-btn）*/
.tab-bar { display: flex; gap: 2px; background: rgba(0,0,0,0.05); border-radius: 10px; padding: 3px; }
.tab-btn { border: none; background: none; padding: 5px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; color: var(--muted); cursor: pointer; }
.tab-btn.active { background: #fff; color: var(--text); box-shadow: 0 1px 4px rgba(0,0,0,0.12); }

/* 搜索小框：内嵌在 filter-bar 右侧，宽度自适应 */
.pcf-search-wrap {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,.6); border: 1px solid var(--border);
  border-radius: 8px; padding: 0 10px; height: 32px; min-width: 140px;
  transition: border-color .15s, width .18s;
}
.pcf-search-wrap:focus-within { border-color: rgba(201,99,66,.5); background: #fff; min-width: 200px; }
.pcf-search { flex: 1 1 auto; min-width: 0; border: none; background: transparent; font-size: 13px; color: var(--text); outline: none; }
.pcf-search::placeholder { color: var(--muted); }

.pcf-empty { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
.pcf-empty.err { color: #c62828; }

/* 固定视口：fh-fill + page-scroll（全局 full-height-view 链路），表头吸顶实色 */
.fh-fill { padding-bottom: 40px; }
.table-wrap thead th {
  position: sticky; top: 0; z-index: 5;
  background: #f4f1ef; box-shadow: inset 0 -1px 0 rgba(0,0,0,.08);
}

/* Table — 表头与单元格统一居中，字段名与内容上下对齐 */
.pcf-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pcf-table thead th {
  padding: 9px 12px; text-align: center; font-size: 11.5px; font-weight: 700;
  color: var(--muted); white-space: nowrap; background: #f4f1ef;
}
.amt { font-variant-numeric: tabular-nums; }
.sortable { cursor: pointer; }
.sortable:hover { color: var(--primary, #c96342); }
/* 排序列表头用实色，防滚动时数据透出 */
.pcf-table thead th.sorted { background: #f0e6e1; color: var(--primary, #c96342); }
.sort-arr { font-size: 10px; }

.pcf-row { cursor: pointer; }
.pcf-row.no-drill { cursor: default; }
.pcf-table tbody td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,.04); color: var(--text); vertical-align: middle; text-align: center; }
.pcf-table tbody tr:hover td { background: rgba(201,99,66,.08); }
.pcf-th-proj { min-width: 160px; }
.pcf-td-proj { min-width: 160px; }
.pcf-pname { font-weight: 600; }
.pcf-psub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.dept-tag {
  display: inline-block; padding: 2px 8px; border-radius: 6px; border: 1px solid transparent;
  background: rgba(180,140,110,.12); color: var(--muted); font-size: 11px; white-space: nowrap; font-weight: 600;
}
.caret { font-size: 8px; margin-right: 3px; vertical-align: 1px; opacity: .85; }
.bb-caret { font-size: 8px; margin-right: 2px; vertical-align: 1px; }
.pcf-table thead th.sorted { background: #f0e6e1; }
.pcf-table tbody td.col-on { background: rgba(201,99,66,.045); }
.pcf-table tbody tr:hover td.col-on { background: rgba(201,99,66,.07); }
.pcf-table tbody tr:nth-child(even) td { background: rgba(255,255,255,.20); }
.pcf-table tbody tr:nth-child(even) td.col-on { background: rgba(201,99,66,.05); }
.pcf-table tbody tr:hover td { background: rgba(201,99,66,.08); }

/* 回款率：迷你进度条 + 色阶 */
.rate-cell { display: inline-flex; flex-direction: column; align-items: center; gap: 3px; }
.rate-val { font-variant-numeric: tabular-nums; font-weight: 600; font-size: 12.5px; }
.rate-track { width: 58px; height: 4px; border-radius: 3px; background: rgba(180,140,110,.18); overflow: hidden; }
.rate-track i { display: block; height: 100%; border-radius: 3px; transition: width .3s; }

/* 吸底栏小图标 */
.bb-ico { width: 13px; height: 13px; align-self: center; flex-shrink: 0; }
.green { color: #2e7d32; }
.red { color: #c62828; }
.amber { color: #e65100; }
.muted { color: var(--muted); }
.fw { font-weight: 700; }

.pcf-btn-detail {
  border: 1px solid rgba(122,159,212,.3); background: rgba(122,159,212,.08);
  color: #4a6fa5; font-size: 11.5px; padding: 3px 9px; border-radius: 7px; cursor: pointer; white-space: nowrap;
}
.pcf-btn-detail:hover { background: rgba(122,159,212,.18); }
</style>
