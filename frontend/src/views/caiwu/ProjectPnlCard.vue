<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { TOOLTIP } from '../../utils/chartTheme.js'
import EmptyState from '../../components/EmptyState.vue'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'

const props = defineProps({
  name: { type: String, required: true },
  year: { type: Number, required: true },
})
const emit = defineEmits(['close'])

const data = ref(null)
const loading = ref(true)
const err = ref('')

const fmtWan = (v) => fmtCompact(v, { decimals: 1, smallRound: true, dash: '0' })
const fmtPct = (v) => (v == null ? '—' : `${v.toFixed(1)}%`)

const TAGS = {
  healthy: { label: '优质', color: '#2e7d32' },
  low_margin: { label: '赚收入不赚钱', color: '#f9a825' },
  cash_risk: { label: '赚利润收不回钱', color: '#fb8c00' },
  critical: { label: '又薄又难收', color: '#e53935' },
  idle: { label: '无收入', color: '#9e9e9e' },
}
const tagOf = (k) => TAGS[k] || { label: k, color: '#9b8070' }

async function load() {
  loading.value = true; err.value = ''; data.value = null
  try {
    const r = await ar.projectPnl({ year: props.year, name: props.name })
    data.value = r.data
  } catch (e) {
    err.value = e?.msg || '加载失败'
  } finally {
    loading.value = false
  }
}
watch(() => [props.name, props.year], load)
onMounted(load)

const monthlyOption = computed(() => {
  const m = data.value?.monthly || []
  if (!m.length) return null
  const x = m.map(r => `${r.month}月`)
  const w = (v) => (Math.abs(v) >= 10000 ? (v / 10000).toFixed(0) + '万' : Math.round(v))
  return {
    tooltip: {
      trigger: 'axis', ...TOOLTIP,
      formatter: (ps) => {
        let s = `<b>${ps[0]?.axisValue}</b><br/>`
        ps.forEach(p => {
          const isPct = p.seriesName.includes('率')
          s += `${p.marker}${p.seriesName}：<b>${p.value == null ? '—' : (isPct ? p.value + '%' : fmtWan(p.value))}</b><br/>`
        })
        return s
      },
    },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#6b5a4a' }, data: ['收入', '成本', '毛利率'] },
    grid: { top: 16, right: 46, bottom: 34, left: 52 },
    xAxis: { type: 'category', data: x, axisLabel: { color: '#9b8070' } },
    yAxis: [
      { type: 'value', axisLabel: { color: '#9b8070', formatter: w }, splitLine: { lineStyle: { color: 'rgba(180,140,110,.12)' } } },
      { type: 'value', name: '毛利率%', position: 'right', axisLabel: { color: '#9b8070', formatter: '{value}%' }, splitLine: { show: false } },
    ],
    series: [
      { name: '收入', type: 'bar', data: m.map(r => r.revenue), itemStyle: { color: '#66bb6a', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 22 },
      { name: '成本', type: 'bar', data: m.map(r => r.cost), itemStyle: { color: '#ef9a9a', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 22 },
      { name: '毛利率', type: 'line', yAxisIndex: 1, data: m.map(r => r.margin_rate), smooth: true, symbol: 'circle', symbolSize: 5, lineStyle: { color: '#00897b', width: 2.5 }, itemStyle: { color: '#00897b' } },
    ],
  }
})
</script>

<template>
  <div class="pnl-mask" @click.self="emit('close')">
    <div class="pnl-card">
      <div class="pnl-head">
        <div>
          <div class="pnl-title">{{ data?.project?.name || name }}</div>
          <div v-if="data?.totals" class="pnl-sub">
            {{ data.project?.customer || '未关联客户' }} · {{ data.project?.delivery_dept }}
            · 负责人 {{ data.project?.project_manager || '—' }}
            <span class="pill" :style="{ color: tagOf(data.totals.tag).color, borderColor: tagOf(data.totals.tag).color + '55' }">{{ data.totals.tag_label }}</span>
          </div>
        </div>
        <button class="pnl-x" @click="emit('close')">✕</button>
      </div>

      <EmptyState v-if="loading" loading />
      <EmptyState v-else-if="err" :error="err" />
      <template v-else-if="data?.totals">
        <div class="pnl-cards">
          <div class="pnl-kpi profit">
            <div class="t">财务毛利</div>
            <div class="v">{{ fmtWan(data.totals.margin) }}</div>
            <div class="s">收入 {{ fmtWan(data.totals.revenue) }} · 毛利率 {{ fmtPct(data.totals.margin_rate) }}</div>
          </div>
          <div class="pnl-kpi cash">
            <div class="t">应收未收</div>
            <div class="v">{{ fmtWan(data.totals.outstanding) }}</div>
            <div class="s">已开票 {{ fmtWan(data.totals.invoiced) }} · 回款率 {{ fmtPct(data.totals.collect_rate) }}</div>
          </div>
          <div class="pnl-kpi risk">
            <div class="t">逾期未收</div>
            <div class="v" :style="{ color: data.totals.overdue > 0 ? '#c62828' : '#2e7d32' }">{{ fmtWan(data.totals.overdue) }}</div>
            <div class="s">逾期占比 {{ fmtPct(data.totals.overdue_rate) }}</div>
          </div>
        </div>

        <div class="pnl-block-title">逐月损益<span class="tip">收入/成本柱 + 毛利率线</span></div>
        <BaseChart v-if="monthlyOption" :option="monthlyOption" height="220px" />
        <div v-else class="pnl-empty">暂无逐月盈利数据</div>

        <div class="pnl-block-title">回款流水<span class="tip">{{ data.payments?.length || 0 }} 笔</span></div>
        <div v-if="data.payments?.length" class="pnl-flow">
          <div v-for="(p, i) in data.payments" :key="i" class="flow-item">
            <span class="dot"></span>
            <span class="fdate">{{ p.date || '—' }}</span>
            <span class="famt">+{{ fmtWan(p.amount) }}</span>
            <span class="fsrc">{{ p.source }}<template v-if="p.operation_month"> · {{ p.operation_month }}月账</template></span>
          </div>
        </div>
        <div v-else class="pnl-empty">该项目本年暂无回款记录（未收 {{ fmtWan(data.totals.outstanding) }}）</div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.pnl-mask {
  position: fixed; inset: 0; z-index: 1300; background: rgba(60,40,30,.42);
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
.pill { display: inline-block; padding: 1px 8px; border: 1px solid; border-radius: 10px; font-size: 11px; white-space: nowrap; }
</style>
