<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { TOOLTIP } from '../../utils/chartTheme.js'
import EmptyState from '../../components/EmptyState.vue'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import ProjectPnlCard from './ProjectPnlCard.vue'

defineProps({ embedded: { type: Boolean, default: false } })

const auth = useAuthStore()

const selectedDept = ref('')
const selectedYear = ref(yearCST())
const selectedMonth = ref('')          // '' = 全年累计
const groupBy = ref('project')          // project | customer
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

const loading = ref(false)
const loadErr = ref('')
const resp = ref(null)

const fmtWan = (v) => fmtCompact(v, { decimals: 1, smallRound: true, dash: '0' })
const fmtPct = (v) => (v == null ? '—' : `${v.toFixed(1)}%`)

// ── 融合标签视觉体系（与后端 _bf_tag 对齐）────────────────────────────────────
const TAGS = {
  healthy:    { label: '优质',         color: '#2e7d32', desc: '高毛利 + 回款健康' },
  low_margin: { label: '赚收入不赚钱', color: '#f9a825', desc: '规模大但毛利薄' },
  cash_risk:  { label: '赚利润收不回钱', color: '#fb8c00', desc: '有毛利但回款承压' },
  critical:   { label: '又薄又难收',   color: '#e53935', desc: '低毛利 + 回款差' },
  idle:       { label: '无收入',       color: '#9e9e9e', desc: '本期无收入确认' },
}
const tagOf = (k) => TAGS[k] || { label: k, color: '#9b8070', desc: '' }

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const params = { year: selectedYear.value, group_by: groupBy.value }
    if (selectedMonth.value) params.month = selectedMonth.value
    if (selectedDept.value) params.dept = selectedDept.value
    const r = await ar.businessFinance(params)
    resp.value = r.data
  } catch (e) {
    loadErr.value = e?.msg || '加载失败'
  } finally {
    loading.value = false
  }
}

const summary = computed(() => resp.value?.summary || null)
const rows = computed(() => resp.value?.rows || [])
const isCustomer = computed(() => groupBy.value === 'customer')

// 标签分布（按收入规模排序，无收入归类置后）
const tagStats = computed(() => {
  const bt = summary.value?.by_tag || {}
  const order = ['critical', 'cash_risk', 'low_margin', 'healthy', 'idle']
  return order.filter(k => bt[k]).map(k => ({ key: k, ...tagOf(k), ...bt[k] }))
})
const coverage = computed(() => {
  const s = summary.value
  if (!s || !s.project_count) return null
  return Math.round((s.linked_count / s.project_count) * 100)
})
// 客户维度：若全部归入「未关联客户」，说明应收项目尚未维护客户归属
const customerUnmapped = computed(() =>
  isCustomer.value && rows.value.length === 1 && rows.value[0]?.unlinked)

// ── 项目损益卡：点击项目行打开共享的 ProjectPnlCard ─────────────────────────
const pnlName = ref('')
function openPnl(row) {
  if (isCustomer.value) return            // 客户维度不下钻单项目卡
  pnlName.value = row.project_name
}

// ── 业财四象限：横轴毛利率、纵轴回款健康度(=100−逾期率)、气泡=收入、配色=标签 ──
const quadrantOption = computed(() => {
  const list = rows.value.filter(r => (r.revenue || 0) > 0)
  if (!list.length) return null
  const revs = list.map(r => r.revenue)
  const maxRev = Math.max(...revs, 1)
  const sizeOf = (rev) => 10 + Math.sqrt(Math.max(rev, 0) / maxRev) * 38
  // 回款健康度：优先用 100−逾期率；无逾期口径时退回回款率
  const health = (r) => {
    if (r.overdue_rate != null) return Math.max(0, 100 - r.overdue_rate)
    if (r.collect_rate != null) return r.collect_rate
    return null
  }
  const pts = list.filter(r => r.margin_rate != null && health(r) != null).map(r => ({
    value: [r.margin_rate, +health(r).toFixed(1), r.revenue],
    name: r.label,
    itemStyle: { color: tagOf(r.tag).color + 'cc', borderColor: '#fff', borderWidth: 1 },
    _r: r,
  }))
  if (!pts.length) return null
  // 显式轴边界，避免 markArea 角点撑大坐标轴
  const mrs = pts.map(p => p.value[0])
  const xMin = Math.min(-5, Math.floor(Math.min(...mrs) - 3))
  const xMax = Math.max(15, Math.ceil(Math.max(...mrs) + 3))
  return {
    tooltip: {
      trigger: 'item', ...TOOLTIP,
      formatter: (p) => {
        const r = p.data._r
        return `<b>${r.label}</b><br/>`
          + `${isCustomer.value ? '' : '客户：' + (r.customer || '—') + '<br/>'}`
          + `收入：${fmtWan(r.revenue)}　毛利率：${fmtPct(r.margin_rate)}<br/>`
          + `未收：${fmtWan(r.outstanding)}　逾期率：${fmtPct(r.overdue_rate)}<br/>`
          + `回款率：${fmtPct(r.collect_rate)}<br/>`
          + `<span style="color:${tagOf(r.tag).color}">● ${r.tag_label}</span>`
      },
    },
    grid: { top: 28, right: 20, bottom: 44, left: 56 },
    xAxis: {
      type: 'value', name: '毛利率 %', nameLocation: 'middle', nameGap: 28,
      min: xMin, max: xMax,
      nameTextStyle: { color: '#9b8070', fontSize: 11 },
      axisLabel: { color: '#9b8070', formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.12)' } },
    },
    yAxis: {
      type: 'value', name: '回款健康度', min: 0, max: 100,
      nameTextStyle: { color: '#9b8070', fontSize: 11 },
      axisLabel: { color: '#9b8070' },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.12)' } },
    },
    series: [{
      type: 'scatter', data: pts, symbolSize: (v) => sizeOf(v[2]),
      // 象限分割：毛利率 5% 薄利线、回款健康度 70 健康线
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { type: 'dashed', color: 'rgba(198,99,66,.5)' },
        label: { color: '#c96342', fontSize: 10 },
        data: [
          { xAxis: 5, label: { formatter: '薄利线 5%' } },
          { yAxis: 70, label: { formatter: '健康线 70' } },
        ],
      },
      markArea: {
        silent: true,
        data: [
          // 右上：优质区（绿）
          [{ itemStyle: { color: 'rgba(46,125,50,.05)' }, coord: [5, 70] }, { coord: [xMax, 100] }],
          // 左下：高危区（红）
          [{ itemStyle: { color: 'rgba(229,57,53,.06)' }, coord: [xMin, 0] }, { coord: [5, 70] }],
        ],
      },
    }],
  }
})

watch([selectedDept, selectedYear, selectedMonth, groupBy], load)
const onScopeChange = () => {
  if (selectedDept.value && !accessibleDepts.value.includes(selectedDept.value)) selectedDept.value = ''
  load()
}
onMounted(() => { load(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div class="bf-panel" :class="{ embedded }">
    <!-- 筛选条 -->
    <div class="bf-filters">
      <div class="seg">
        <button :class="{ on: groupBy === 'project' }" @click="groupBy = 'project'">按项目</button>
        <button :class="{ on: groupBy === 'customer' }" @click="groupBy = 'customer'">按客户</button>
      </div>
      <select v-model="selectedDept">
        <option value="">全部事业部</option>
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
      <select v-model.number="selectedYear">
        <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
      </select>
      <select v-model="selectedMonth">
        <option value="">全年累计</option>
        <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
      </select>
      <span class="bf-hint">融合财务毛利 × 应收回款，揪出「赚收入不赚钱」「赚利润收不回钱」</span>
    </div>

    <div v-if="customerUnmapped" class="bf-notice">
      ⓘ 当前应收项目尚未维护「客户归属」，客商画像暂归入「未关联客户」。在应收项目中关联客户后，此视图将按客户聚合点亮。
    </div>

    <EmptyState v-if="loading && !resp" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="summary">
      <div :class="{ 'data-reloading': loading }">

        <!-- 汇总带：盈利侧 + 应收侧 -->
        <div class="bf-summary">
          <div class="bf-kpi profit">
            <div class="t">财务毛利</div>
            <div class="v">{{ fmtWan(summary.margin) }}</div>
            <div class="s">收入 {{ fmtWan(summary.revenue) }} · 毛利率 {{ fmtPct(summary.margin_rate) }}</div>
          </div>
          <div class="bf-kpi cash">
            <div class="t">应收未收</div>
            <div class="v">{{ fmtWan(summary.outstanding) }}</div>
            <div class="s">已开票 {{ fmtWan(summary.invoiced) }} · 回款率 {{ fmtPct(summary.collect_rate) }}</div>
          </div>
          <div class="bf-kpi risk">
            <div class="t">逾期未收</div>
            <div class="v" :style="{ color: summary.overdue > 0 ? '#c62828' : '#2e7d32' }">{{ fmtWan(summary.overdue) }}</div>
            <div class="s">逾期占比 {{ fmtPct(summary.overdue_rate) }}</div>
          </div>
          <div class="bf-kpi link">
            <div class="t">业财匹配</div>
            <div class="v">{{ coverage == null ? '—' : coverage + '%' }}</div>
            <div class="s">{{ summary.linked_count }} / {{ summary.project_count }} 个项目接通应收</div>
          </div>
        </div>

        <!-- 融合标签分布 -->
        <div class="bf-tags">
          <div v-for="t in tagStats" :key="t.key" class="bf-tag" :style="{ borderColor: t.color + '55' }">
            <span class="dot" :style="{ background: t.color }"></span>
            <span class="lbl" :style="{ color: t.color }">{{ t.label }}</span>
            <span class="cnt">{{ t.count }}</span>
            <span class="amt">收入 {{ fmtWan(t.revenue) }}<template v-if="t.overdue > 0"> · 逾期 {{ fmtWan(t.overdue) }}</template></span>
            <span class="desc">{{ t.desc }}</span>
          </div>
        </div>

        <!-- 业财四象限 + 明细表 -->
        <div class="bf-grid">
          <div class="bf-card">
            <div class="bf-card-title">业财四象限<span class="tip">气泡=收入规模 · 横轴毛利率 · 纵轴回款健康度</span></div>
            <BaseChart v-if="quadrantOption" :option="quadrantOption" height="360px" />
            <EmptyState v-else empty text="暂无可定位的项目（缺毛利率或回款口径）" />
          </div>
          <div class="bf-card">
            <div class="bf-card-title">{{ isCustomer ? '客商损益榜' : '项目损益榜' }}<span class="tip">按收入排序 · 红=隐性风险</span></div>
            <div class="bf-table-wrap">
              <table class="bf-table">
                <thead>
                  <tr>
                    <th class="l">{{ isCustomer ? '客户' : '项目' }}</th>
                    <th v-if="!isCustomer">客户</th>
                    <th>收入</th>
                    <th>毛利率</th>
                    <th>未收</th>
                    <th>逾期率</th>
                    <th>评级</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in rows" :key="r.key" :class="{ clickable: !isCustomer }" @click="openPnl(r)">
                    <td class="l" :title="isCustomer ? r.label : r.label + '（点击看损益卡）'">{{ r.label }}</td>
                    <td v-if="!isCustomer" class="dim">{{ r.customer || '—' }}</td>
                    <td class="num">{{ fmtWan(r.revenue) }}</td>
                    <td class="num" :style="{ color: (r.margin_rate ?? 99) < 5 ? '#e65100' : '#2e7d32' }">{{ fmtPct(r.margin_rate) }}</td>
                    <td class="num">{{ fmtWan(r.outstanding) }}</td>
                    <td class="num" :style="{ color: (r.overdue_rate ?? 0) > 30 ? '#c62828' : '#6b5a4a' }">{{ fmtPct(r.overdue_rate) }}</td>
                    <td><span class="pill" :style="{ color: tagOf(r.tag).color, borderColor: tagOf(r.tag).color + '55' }">{{ r.tag_label }}</span></td>
                  </tr>
                  <tr v-if="!rows.length"><td :colspan="isCustomer ? 6 : 7" class="empty">暂无数据</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </template>
    <EmptyState v-else empty text="暂无业财融合数据" />

    <!-- 项目损益卡（全链路）— 共享组件 -->
    <ProjectPnlCard v-if="pnlName" :name="pnlName" :year="selectedYear" @close="pnlName = ''" />
  </div>
</template>

<style scoped>
.bf-panel { padding: 4px 0; }
.bf-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.bf-filters select {
  padding: 6px 10px; border: 1px solid rgba(180,140,110,.28); border-radius: 8px;
  background: #fff; color: #5f4d3d; font-size: 13px;
}
.seg { display: inline-flex; border: 1px solid rgba(180,140,110,.28); border-radius: 8px; overflow: hidden; }
.seg button { padding: 6px 14px; border: none; background: #fff; color: #8a7665; font-size: 13px; cursor: pointer; }
.seg button.on { background: linear-gradient(120deg, #c96342, #b5532f); color: #fff; }
.bf-hint { font-size: 11.5px; color: #9b8070; }
.bf-notice {
  margin-bottom: 12px; padding: 9px 12px; border-radius: 10px; font-size: 12.5px; color: #8a6d3b;
  background: rgba(249,168,37,.1); border: 1px solid rgba(249,168,37,.3);
}

.bf-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }
@media (max-width: 820px) { .bf-summary { grid-template-columns: repeat(2, 1fr); } }
.bf-kpi { padding: 12px 14px; border-radius: 12px; background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.16); }
.bf-kpi .t { font-size: 12px; color: #9b8070; }
.bf-kpi .v { font-size: 22px; font-weight: 800; color: #5f4d3d; margin: 2px 0; }
.bf-kpi .s { font-size: 11px; color: #8a7665; }
.bf-kpi.profit { border-left: 3px solid #00897b; }
.bf-kpi.cash { border-left: 3px solid #1565c0; }
.bf-kpi.risk { border-left: 3px solid #e53935; }
.bf-kpi.link { border-left: 3px solid #9b8070; }

.bf-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.bf-tag {
  display: flex; align-items: center; gap: 6px; padding: 6px 11px;
  background: rgba(255,255,255,.6); border: 1px solid; border-radius: 20px; font-size: 12px;
}
.bf-tag .dot { width: 8px; height: 8px; border-radius: 50%; }
.bf-tag .lbl { font-weight: 700; }
.bf-tag .cnt { font-weight: 800; color: #5f4d3d; }
.bf-tag .amt { color: #8a7665; }
.bf-tag .desc { color: #b3a08f; font-size: 11px; }

.bf-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 980px) { .bf-grid { grid-template-columns: 1fr; } }
.bf-card { background: rgba(255,255,255,.55); border: 1px solid rgba(180,140,110,.16); border-radius: 14px; padding: 12px 14px; }
.bf-card-title { font-size: 14px; font-weight: 700; color: #5f4d3d; margin-bottom: 8px; }
.bf-card-title .tip { font-size: 11px; font-weight: 400; color: #9b8070; margin-left: 8px; }

.bf-table-wrap { max-height: 360px; overflow-y: auto; }
.bf-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.bf-table th {
  position: sticky; top: 0; background: #faf6f1; color: #9b8070; font-weight: 600;
  text-align: right; padding: 7px 8px; border-bottom: 1px solid rgba(180,140,110,.2); white-space: nowrap;
}
.bf-table th.l, .bf-table td.l { text-align: left; }
.bf-table td { padding: 7px 8px; border-bottom: 1px solid rgba(180,140,110,.1); color: #5f4d3d; }
.bf-table td.l { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bf-table td.dim { color: #8a7665; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bf-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.bf-table td.empty, .bf-table .empty { text-align: center; color: #b3a08f; padding: 18px; }
.pill { display: inline-block; padding: 1px 8px; border: 1px solid; border-radius: 10px; font-size: 11px; white-space: nowrap; }
.bf-table tr.clickable { cursor: pointer; }
.bf-table tr.clickable:hover td { background: rgba(201,99,66,.06); }

.data-reloading { opacity: .55; transition: opacity .2s; }

/* ── 项目损益卡 ─────────────────────────────────────────────────────────────── */
.pnl-mask {
  position: fixed; inset: 0; z-index: 1200; background: rgba(60,40,30,.42);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.pnl-card {
  width: min(720px, 96vw); max-height: 88vh; overflow-y: auto;
  background: #fdfaf6; border-radius: 16px; padding: 18px 20px;
  box-shadow: 0 18px 50px rgba(60,40,30,.3);
}
.pnl-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.pnl-title { font-size: 18px; font-weight: 800; color: #5f4d3d; }
.pnl-sub { font-size: 12.5px; color: #8a7665; margin-top: 4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pnl-x { border: none; background: none; font-size: 18px; color: #b3a08f; cursor: pointer; line-height: 1; }
.pnl-x:hover { color: #5f4d3d; }
.pnl-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
@media (max-width: 560px) { .pnl-cards { grid-template-columns: 1fr; } }
.pnl-kpi { padding: 11px 13px; border-radius: 11px; background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.16); }
.pnl-kpi .t { font-size: 11.5px; color: #9b8070; }
.pnl-kpi .v { font-size: 20px; font-weight: 800; color: #5f4d3d; margin: 2px 0; }
.pnl-kpi .s { font-size: 11px; color: #8a7665; }
.pnl-kpi.profit { border-left: 3px solid #00897b; }
.pnl-kpi.cash { border-left: 3px solid #1565c0; }
.pnl-kpi.risk { border-left: 3px solid #e53935; }
.pnl-block-title { font-size: 13.5px; font-weight: 700; color: #5f4d3d; margin: 6px 0 6px; }
.pnl-block-title .tip { font-size: 11px; font-weight: 400; color: #9b8070; margin-left: 8px; }
.pnl-empty { padding: 14px; text-align: center; color: #b3a08f; font-size: 12.5px; }
.pnl-flow { display: flex; flex-direction: column; gap: 0; padding-left: 4px; }
.flow-item {
  display: flex; align-items: center; gap: 10px; padding: 7px 0; font-size: 12.5px;
  border-left: 2px solid rgba(180,140,110,.25); padding-left: 14px; position: relative;
}
.flow-item .dot { position: absolute; left: -5px; width: 8px; height: 8px; border-radius: 50%; background: #2e7d32; }
.flow-item .fdate { color: #6b5a4a; font-variant-numeric: tabular-nums; min-width: 88px; }
.flow-item .famt { color: #2e7d32; font-weight: 700; min-width: 72px; }
.flow-item .fsrc { color: #8a7665; }
</style>
