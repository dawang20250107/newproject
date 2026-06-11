<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import ProjectPnlCard from './ProjectPnlCard.vue'

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

// Quick date presets
const PRESETS = [
  { l: '今年', f: () => ({ date_start: `${filters.year}-01-01`, date_end: `${filters.year}-12-31` }) },
  { l: '上半年', f: () => ({ date_start: `${filters.year}-01-01`, date_end: `${filters.year}-06-30` }) },
  { l: '下半年', f: () => ({ date_start: `${filters.year}-07-01`, date_end: `${filters.year}-12-31` }) },
  { l: '本月', f: () => {
    const d = new Date(); const y = d.getFullYear(); const m = String(d.getMonth() + 1).padStart(2, '0')
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
    return { date_start: `${y}-${m}-01`, date_end: `${y}-${m}-${last}` }
  }},
  { l: '本季度', f: () => {
    const d = new Date(); const y = d.getFullYear(); const q = Math.floor(d.getMonth() / 3)
    const ms = q * 3 + 1; const me = q * 3 + 3
    const last = new Date(y, me, 0).getDate()
    return { date_start: `${y}-${String(ms).padStart(2,'0')}-01`, date_end: `${y}-${String(me).padStart(2,'0')}-${last}` }
  }},
]

function applyPreset(p) {
  const { date_start, date_end } = p.f()
  filters.date_start = date_start; filters.date_end = date_end
  filters.useCustomDate = true
  load()
}

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

function openPnl(row) {
  // 业财损益卡只有项目维度可下钻；二级部门维度点击切回项目维并按部门过滤
  if (!isProjDim.value) return
  askTarget.value = { name: row.project, year: filters.year }
}

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
  <div class="pcf-page">
    <div class="pcf-header">
      <div class="pcf-header-left">
        <h1 class="pcf-title">{{ isProjDim ? '项目现金流' : '二级部门现金流' }}</h1>
        <p class="pcf-sub">按{{ isProjDim ? '项目' : '二级部门' }}聚合的回款（流入）、付款（流出）及净现金，洞察资金健康度</p>
      </div>
      <div class="pcf-controls">
        <!-- 维度切换 -->
        <div class="pcf-dim-seg">
          <button v-for="d in DIMS" :key="d.v" class="pcf-dim-btn" :class="{ on: groupBy === d.v }"
            @click="setDim(d.v)">{{ d.l }}</button>
        </div>
        <select v-model="filters.dept" class="pcf-sel" @change="filters.useCustomDate ? load() : null">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model.number="filters.year" class="pcf-sel">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <!-- Date range -->
        <div class="pcf-date-wrap">
          <template v-if="filters.useCustomDate">
            <input v-model="filters.date_start" type="date" class="pcf-date-inp" @change="load" />
            <span class="pcf-dash">—</span>
            <input v-model="filters.date_end" type="date" class="pcf-date-inp" @change="load" />
            <button class="pcf-clear-date" title="还原为年度" @click="clearCustomDate">✕</button>
          </template>
          <template v-else>
            <button v-for="p in PRESETS" :key="p.l" class="pcf-preset" @click="applyPreset(p)">{{ p.l }}</button>
          </template>
        </div>
      </div>
    </div>

    <!-- Summary KPI bar -->
    <div v-if="summary.count" class="pcf-kpi-bar">
      <div class="pcf-kpi">
        <span class="k">回款（流入）</span>
        <span class="v green">{{ fmtWan(summary.inflow) }}</span>
      </div>
      <div class="pcf-kpi-sep"></div>
      <div class="pcf-kpi">
        <span class="k">付款（流出）</span>
        <span class="v red">{{ fmtWan(summary.outflow) }}</span>
      </div>
      <div class="pcf-kpi-sep"></div>
      <div class="pcf-kpi">
        <span class="k">净现金</span>
        <span class="v" :style="{ color: netColor(summary.net) }">{{ fmtWan(summary.net) }}</span>
      </div>
      <div class="pcf-kpi-sep"></div>
      <div class="pcf-kpi">
        <span class="k">应收敞口</span>
        <span class="v amber">{{ fmtWan(summary.outstanding) }}</span>
      </div>
      <div class="pcf-kpi-sep"></div>
      <div class="pcf-kpi">
        <span class="k">涉及{{ isProjDim ? '项目' : '二级部门' }}</span>
        <span class="v">{{ summary.count }} 个</span>
      </div>
      <span v-if="filters.useCustomDate" class="pcf-date-badge">
        {{ data?.date_start }} ~ {{ data?.date_end }}
      </span>
    </div>

    <!-- Table -->
    <div class="pcf-card">
      <div class="pcf-card-top">
        <div class="pcf-search-wrap">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input v-model="search" class="pcf-search" placeholder="搜索项目 / 客户 / 部门" />
        </div>
        <span class="pcf-count">{{ rows.length }} 个{{ isProjDim ? '项目' : '二级部门' }}</span>
      </div>

      <div v-if="loading" class="pcf-empty">加载中…</div>
      <div v-else-if="err" class="pcf-empty err">{{ err }}</div>
      <div v-else-if="!rows.length" class="pcf-empty">
        {{ data ? `暂无数据（所选时段内无关联${isProjDim ? '项目简称' : '二级部门'}的回款或付款）` : '请选择筛选条件后加载' }}
      </div>

      <div v-else class="pcf-table-wrap">
        <table class="pcf-table">
          <thead>
            <tr>
              <th class="pcf-th-proj">{{ isProjDim ? '项目' : '二级部门' }}</th>
              <th>事业部</th>
              <th class="pcf-th-num sortable" :class="{ sorted: sortKey === 'inflow' }" @click="setSort('inflow')">
                回款流入 <span class="sort-arr">{{ sortKey === 'inflow' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="pcf-th-num sortable" :class="{ sorted: sortKey === 'outflow' }" @click="setSort('outflow')">
                付款流出 <span class="sort-arr">{{ sortKey === 'outflow' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="pcf-th-num sortable" :class="{ sorted: sortKey === 'net' }" @click="setSort('net')">
                净现金 <span class="sort-arr">{{ sortKey === 'net' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="pcf-th-num sortable" :class="{ sorted: sortKey === 'outstanding' }" @click="setSort('outstanding')">
                应收敞口 <span class="sort-arr">{{ sortKey === 'outstanding' ? (sortDesc ? '↓' : '↑') : '↕' }}</span>
              </th>
              <th class="pcf-th-num">回款率</th>
              <th v-if="isProjDim" class="pcf-th-act">详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.project" class="pcf-row" :class="{ 'no-drill': !isProjDim }" @click="openPnl(r)">
              <td class="pcf-td-proj">
                <div class="pcf-pname">{{ r.project }}</div>
                <div v-if="r.customer" class="pcf-psub">{{ r.customer }}</div>
              </td>
              <td class="pcf-td-dept"><span class="dept-tag">{{ r.dept || '—' }}</span></td>
              <td class="pcf-td-num green fw">{{ r.inflow ? fmtWan(r.inflow) : '—' }}</td>
              <td class="pcf-td-num red">{{ r.outflow ? fmtWan(r.outflow) : '—' }}</td>
              <td class="pcf-td-num fw" :style="{ color: netColor(r.net) }">{{ fmtWan(r.net) }}</td>
              <td class="pcf-td-num" :class="r.outstanding > 0 ? 'amber' : 'muted'">
                {{ r.outstanding > 0 ? fmtWan(r.outstanding) : '—' }}
              </td>
              <td class="pcf-td-num muted">
                {{ r.estimated > 0 ? fmtPct(r.inflow, r.estimated) : '—' }}
              </td>
              <td v-if="isProjDim" class="pcf-td-act">
                <button class="pcf-btn-detail" @click.stop="openPnl(r)">业财卡</button>
              </td>
            </tr>
          </tbody>
          <!-- Footer totals -->
          <tfoot>
            <tr class="pcf-foot">
              <td colspan="2">合计 {{ rows.length }} 个{{ isProjDim ? '项目' : '二级部门' }}</td>
              <td class="pcf-td-num green fw">{{ fmtWan(rows.reduce((s, r) => s + r.inflow, 0)) }}</td>
              <td class="pcf-td-num red">{{ fmtWan(rows.reduce((s, r) => s + r.outflow, 0)) }}</td>
              <td class="pcf-td-num fw" :style="{ color: netColor(rows.reduce((s, r) => s + r.net, 0)) }">
                {{ fmtWan(rows.reduce((s, r) => s + r.net, 0)) }}
              </td>
              <td class="pcf-td-num amber">{{ fmtWan(rows.reduce((s, r) => s + r.outstanding, 0)) }}</td>
              <td :colspan="isProjDim ? 2 : 1"></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>

    <!-- ProjectPnlCard overlay -->
    <ProjectPnlCard
      v-if="askTarget"
      :name="askTarget.name"
      :year="askTarget.year"
      :askable="false"
      @close="askTarget = null"
    />
  </div>
</template>

<style scoped>
.pcf-page { padding: 20px 24px; max-width: 1200px; }
.pcf-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.pcf-title { font-size: 22px; font-weight: 800; color: #5f4d3d; margin: 0 0 4px; }
.pcf-sub { font-size: 12.5px; color: #9b8070; margin: 0; }
.pcf-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pcf-sel {
  border: 1px solid rgba(180,140,110,.3); border-radius: 8px; padding: 6px 10px;
  font-size: 13px; background: rgba(255,255,255,.7); color: #5f4d3d; cursor: pointer;
}
.pcf-date-wrap { display: flex; align-items: center; gap: 4px; }
.pcf-date-inp {
  border: 1px solid rgba(180,140,110,.3); border-radius: 8px; padding: 5px 8px;
  font-size: 12px; background: rgba(255,255,255,.7); color: #5f4d3d;
}
.pcf-dash { color: #9b8070; font-size: 13px; }
.pcf-clear-date {
  border: none; background: transparent; cursor: pointer; color: #9b8070; font-size: 13px; padding: 2px 4px;
}
.pcf-clear-date:hover { color: #c62828; }
.pcf-preset {
  border: 1px solid rgba(180,140,110,.25); background: rgba(255,255,255,.6); color: #6b5a4a;
  font-size: 12px; padding: 4px 10px; border-radius: 7px; cursor: pointer;
}
.pcf-preset:hover { background: rgba(201,99,66,.1); border-color: rgba(201,99,66,.4); color: var(--primary, #c96342); }
.pcf-dim-seg {
  display: flex; border: 1px solid rgba(180,140,110,.3); border-radius: 8px; overflow: hidden;
  background: rgba(255,255,255,.6);
}
.pcf-dim-btn {
  border: none; background: transparent; padding: 6px 14px; font-size: 13px;
  color: #8a7665; cursor: pointer; font-weight: 600;
}
.pcf-dim-btn + .pcf-dim-btn { border-left: 1px solid rgba(180,140,110,.2); }
.pcf-dim-btn.on { background: var(--primary, #c96342); color: #fff; }
.pcf-row.no-drill { cursor: default; }

/* KPI bar */
.pcf-kpi-bar {
  display: flex; align-items: center; gap: 0; flex-wrap: wrap;
  background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.18);
  border-radius: 12px; padding: 12px 20px; margin-bottom: 16px;
  box-shadow: 0 2px 8px rgba(100,60,30,.07);
}
.pcf-kpi { display: flex; flex-direction: column; gap: 3px; padding: 0 16px; }
.pcf-kpi .k { font-size: 11px; color: #9b8070; }
.pcf-kpi .v { font-size: 18px; font-weight: 800; color: #5f4d3d; font-variant-numeric: tabular-nums; }
.pcf-kpi .v.green { color: #2e7d32; }
.pcf-kpi .v.red { color: #c62828; }
.pcf-kpi .v.amber { color: #e65100; }
.pcf-kpi-sep { width: 1px; height: 36px; background: rgba(180,140,110,.2); flex-shrink: 0; }
.pcf-date-badge {
  margin-left: auto; font-size: 11px; color: #9b8070;
  background: rgba(180,140,110,.1); border-radius: 6px; padding: 3px 8px;
}

/* Card */
.pcf-card {
  background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.18);
  border-radius: 14px; box-shadow: 0 2px 12px rgba(100,60,30,.08);
  overflow: hidden;
}
.pcf-card-top {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid rgba(180,140,110,.12);
}
.pcf-search-wrap {
  display: flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,.8); border: 1px solid rgba(180,140,110,.2);
  border-radius: 8px; padding: 5px 10px;
}
.pcf-search { border: none; background: transparent; font-size: 13px; color: #5f4d3d; outline: none; width: 220px; }
.pcf-count { font-size: 12px; color: #9b8070; }
.pcf-empty { padding: 40px; text-align: center; color: #b3a08f; font-size: 13px; }
.pcf-empty.err { color: #c62828; }
.pcf-table-wrap { overflow-x: auto; }

/* Table */
.pcf-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pcf-table thead th {
  padding: 10px 14px; text-align: left; font-size: 11.5px; font-weight: 700;
  color: #8a7665; background: rgba(250,245,240,.8);
  border-bottom: 1px solid rgba(180,140,110,.15); white-space: nowrap;
}
.pcf-th-num { text-align: right; }
.pcf-th-act { text-align: center; }
.pcf-th-proj { min-width: 160px; }
.sortable { cursor: pointer; }
.sortable:hover { color: var(--primary, #c96342); }
.sorted { color: var(--primary, #c96342); }
.sort-arr { font-size: 10px; }

.pcf-row { cursor: pointer; transition: background .15s; }
.pcf-row:hover td { background: rgba(201,99,66,.04); }
.pcf-table td { padding: 10px 14px; border-bottom: 1px solid rgba(180,140,110,.08); color: #5f4d3d; vertical-align: middle; }
.pcf-td-proj { min-width: 160px; }
.pcf-pname { font-weight: 600; font-size: 13px; }
.pcf-psub { font-size: 11px; color: #9b8070; margin-top: 2px; }
.pcf-td-dept {}
.dept-tag {
  display: inline-block; padding: 2px 7px; border-radius: 5px;
  background: rgba(180,140,110,.1); color: #8a7665; font-size: 11px; white-space: nowrap;
}
.pcf-td-num { text-align: right; font-variant-numeric: tabular-nums; }
.pcf-td-act { text-align: center; }
.green { color: #2e7d32; }
.red { color: #c62828; }
.amber { color: #e65100; }
.muted { color: #9b8070; }
.fw { font-weight: 700; }

.pcf-btn-detail {
  border: 1px solid rgba(122,159,212,.3); background: rgba(122,159,212,.08);
  color: #4a6fa5; font-size: 11.5px; padding: 3px 9px; border-radius: 7px; cursor: pointer;
  white-space: nowrap;
}
.pcf-btn-detail:hover { background: rgba(122,159,212,.18); }

.pcf-foot td {
  padding: 10px 14px; font-size: 12px; color: #8a7665;
  background: rgba(250,245,240,.9); border-top: 2px solid rgba(180,140,110,.18);
}
</style>
