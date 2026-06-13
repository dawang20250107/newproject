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

const totals = computed(() => rows.value.reduce((t, r) => ({
  inflow: t.inflow + r.inflow, outflow: t.outflow + r.outflow,
  net: t.net + r.net, outstanding: t.outstanding + r.outstanding,
}), { inflow: 0, outflow: 0, net: 0, outstanding: 0 }))

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
  <div>
    <!-- 标题行：tab + 全部筛选同处一行，去掉独立的整行筛选框 -->
    <div class="topbar pcf-topbar">
      <div class="pcf-dim-seg pcf-tabs">
        <button v-for="d in DIMS" :key="d.v" class="pcf-dim-btn" :class="{ on: groupBy === d.v }"
          @click="setDim(d.v)">{{ d.l }}现金流</button>
      </div>
      <div class="pcf-controls">
        <select v-model="filters.dept" class="pcf-sel" @change="filters.useCustomDate ? load() : null">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <div class="pcf-search-wrap">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input v-model="search" class="pcf-search" placeholder="搜索项目 / 客户" />
        </div>
        <span class="pcf-fb-sep"></span>
        <select v-model.number="filters.year" class="pcf-sel">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
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

    <!-- 表格：标准 card -->
    <div class="card">
      <div class="section-title">
        {{ isProjDim ? '项目' : '二级部门' }}现金流明细
        <span class="section-sub">
          {{ filters.dept || '全部事业部' }}
          · <template v-if="filters.useCustomDate">{{ data?.date_start }} ~ {{ data?.date_end }}</template>
          <template v-else>{{ filters.year }} 年</template>
        </span>
      </div>

      <div v-if="loading" class="pcf-empty">加载中…</div>
      <div v-else-if="err" class="pcf-empty err">{{ err }}</div>
      <div v-else-if="!rows.length" class="pcf-empty">
        {{ data ? `暂无数据（所选时段内无关联${isProjDim ? '项目简称' : '二级部门'}的回款或付款）` : '请选择筛选条件后加载' }}
      </div>

      <div v-else class="table-wrap">
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
            <tr v-for="r in rows" :key="r.project" class="pcf-row" :class="{ 'no-drill': !isProjDim }" @click="openPnl(r)">
              <td class="pcf-td-proj">
                <div class="pcf-pname">{{ r.project }}</div>
                <div v-if="r.customer" class="pcf-psub">{{ r.customer }}</div>
              </td>
              <td><span class="dept-tag">{{ r.dept || '—' }}</span></td>
              <td class="amt green fw">{{ r.inflow ? fmtWan(r.inflow) : '—' }}</td>
              <td class="amt red">{{ r.outflow ? fmtWan(r.outflow) : '—' }}</td>
              <td class="amt fw" :style="{ color: netColor(r.net) }">{{ fmtWan(r.net) }}</td>
              <td class="amt" :class="r.outstanding > 0 ? 'amber' : 'muted'">
                {{ r.outstanding > 0 ? fmtWan(r.outstanding) : '—' }}
              </td>
              <td class="amt muted">
                {{ r.estimated > 0 ? fmtPct(r.inflow, r.estimated) : '—' }}
              </td>
              <td v-if="isProjDim" class="ctr">
                <button class="pcf-btn-detail" @click.stop="openPnl(r)">业财卡</button>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr class="pcf-foot">
              <td colspan="2" class="fw">合计 {{ rows.length }} 个{{ isProjDim ? '项目' : '二级部门' }}</td>
              <td class="amt green fw">{{ fmtWan(totals.inflow) }}</td>
              <td class="amt red fw">{{ fmtWan(totals.outflow) }}</td>
              <td class="amt fw" :style="{ color: netColor(totals.net) }">{{ fmtWan(totals.net) }}</td>
              <td class="amt amber fw">{{ fmtWan(totals.outstanding) }}</td>
              <td :colspan="isProjDim ? 2 : 1"></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>

    <!-- 吸底汇总：对齐付款台账的 bottom-bar。Teleport 到 body 逃脱 .card 包含块 -->
    <Teleport to="body">
      <div v-if="!loading && !err && rows.length && !askTarget" class="bottom-bar">
        <div class="bb-summary">
          <span class="bb-item"><i>合计</i><b>{{ rows.length }}</b> 个{{ isProjDim ? '项目' : '二级部门' }}</span>
          <span class="bb-item ok"><i>回款流入</i><b>{{ fmtWan(totals.inflow) }}</b></span>
          <span class="bb-item"><i>付款流出</i><b style="color:#c62828">{{ fmtWan(totals.outflow) }}</b></span>
          <span class="bb-item"><i>净现金</i><b :style="{ color: netColor(totals.net) }">{{ fmtWan(totals.net) }}</b></span>
          <span class="bb-item warn"><i>应收敞口</i><b>{{ fmtWan(totals.outstanding) }}</b></span>
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
  </div>
</template>

<style scoped>
/* 标题行：tab 居左作页面标题，筛选项全部并入同一行靠右，去掉独立筛选条 */
.pcf-topbar { gap: 12px; flex-wrap: wrap; }
.pcf-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.pcf-sel {
  border: 1px solid var(--border); background: rgba(255,255,255,.6); padding: 7px 12px;
  border-radius: 8px; font-size: 13px; color: var(--text); cursor: pointer; outline: none;
}
.pcf-sel:hover, .pcf-sel:focus { background: rgba(201,99,66,.09); color: var(--primary); }
.pcf-fb-sep { width: 1px; height: 20px; background: var(--border); margin: 0 2px; }
.pcf-dim-seg { display: inline-flex; background: rgba(0,0,0,.05); border-radius: 9px; padding: 3px; }
.pcf-tabs .pcf-dim-btn { font-size: 15px; padding: 6px 18px; }
.pcf-dim-btn {
  border: none; background: none; padding: 5px 16px; border-radius: 7px;
  font-size: 12.5px; color: var(--muted); cursor: pointer; font-weight: 600;
}
.pcf-dim-btn.on { background: #fff; color: var(--primary); font-weight: 700; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
.pcf-date-inp {
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 9px;
  font-size: 12.5px; background: rgba(255,255,255,.6); color: var(--text);
}
.pcf-dash { color: var(--muted); font-size: 13px; }
.pcf-clear-date { border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 13px; padding: 2px 4px; }
.pcf-clear-date:hover { color: #c62828; }
.pcf-preset {
  border: 1px solid var(--border); background: rgba(255,255,255,.6); color: var(--muted);
  font-size: 12.5px; padding: 6px 12px; border-radius: 8px; cursor: pointer;
}
.pcf-preset:hover { background: rgba(201,99,66,.09); border-color: rgba(201,99,66,.4); color: var(--primary); }

/* Search in section title */
.pcf-search-wrap {
  margin-left: auto; display: inline-flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,.6); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; color: var(--muted);
}
.pcf-search {
  border: none; background: transparent; font-size: 13px; color: var(--text);
  outline: none; width: 96px; transition: width .18s;
}
.pcf-search:focus { width: 160px; }

.pcf-empty { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
.pcf-empty.err { color: #c62828; }

/* Table — 对齐项目毛利的 pm-table */
.pcf-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pcf-table thead th {
  padding: 9px 12px; text-align: left; font-size: 11.5px; font-weight: 700;
  color: var(--muted); border-bottom: 1px solid rgba(0,0,0,.08); white-space: nowrap;
}
.amt { text-align: right; font-variant-numeric: tabular-nums; }
.ctr { text-align: center; }
.sortable { cursor: pointer; }
.sortable:hover { color: var(--primary, #c96342); }
.sorted { color: var(--primary, #c96342); }
.sort-arr { font-size: 10px; }

.pcf-row { cursor: pointer; }
.pcf-row.no-drill { cursor: default; }
.pcf-table tbody td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,.04); color: var(--text); vertical-align: middle; }
.pcf-table tbody tr:hover td { background: rgba(201,99,66,.03); }
.pcf-th-proj { min-width: 160px; }
.pcf-td-proj { min-width: 160px; }
.pcf-pname { font-weight: 600; }
.pcf-psub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.dept-tag {
  display: inline-block; padding: 2px 7px; border-radius: 5px;
  background: rgba(180,140,110,.12); color: var(--muted); font-size: 11px; white-space: nowrap;
}
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

.pcf-foot td { padding: 10px 12px; border-top: 2px solid rgba(201,99,66,.3); background: #f8efeb; font-size: 12.5px; color: var(--text); }
</style>
