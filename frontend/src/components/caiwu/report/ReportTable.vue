<script setup>
import { ref, computed } from 'vue'
import { fmtCompact } from '../../../utils/format.js'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  level: { type: Number, default: 1 },
  total: { type: Number, default: 0 },
  totalLabel: { type: String, default: '合计' },
})

const collapsed = ref(new Set())

// When the bottom-line figure (e.g. 经营净利) already appears as a calculated
// L1 row, a separate total row would duplicate it — suppress it and emphasise
// the matching row instead.
const dupRowId = computed(() => {
  const m = props.rows.find(r => r.l1_name === props.totalLabel)
  return m ? m.l1_id : null
})
const showTotalRow = computed(() => dupRowId.value === null)

function toggle(id) {
  if (collapsed.value.has(id)) collapsed.value.delete(id)
  else collapsed.value.add(id)
}

// 亿/万 两级单位（单位前带空格），万元以下两位小数；空值显示 0.00（保持原表现）
const fmt = (n) => fmtCompact(n, { space: true, dash: '0.00' })

// ── 环比 ─────────────────────────────────────────────────────────────────────
function momTxt(mom) {
  if (mom == null) return '—'
  return (mom >= 0 ? '▲' : '▼') + Math.abs(mom).toFixed(1) + '%'
}
function momCls(mom) {
  if (mom == null) return 'mom-na'
  return mom >= 0 ? 'mom-up' : 'mom-down'
}

// ── 迷你趋势线（近 6 个月）──────────────────────────────────────────────────
const SPARK_W = 56, SPARK_H = 16, SPARK_PAD = 2
function spark(trend) {
  if (!trend || trend.length < 2) return null
  const min = Math.min(...trend), max = Math.max(...trend)
  const span = max - min || 1
  const n = trend.length
  const iw = SPARK_W - SPARK_PAD * 2, ih = SPARK_H - SPARK_PAD * 2
  const pts = trend.map((v, i) => [
    SPARK_PAD + (i / (n - 1)) * iw,
    SPARK_PAD + ih - ((v - min) / span) * ih,
  ])
  const last = pts[pts.length - 1]
  return {
    points: pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '),
    cx: last[0].toFixed(1), cy: last[1].toFixed(1),
  }
}
// 预算好每行的 sparkline，避免模板内重复计算
const sparkById = computed(() => {
  const m = {}
  for (const r of props.rows) m[r.l1_id] = spark(r.trend)
  return m
})
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th v-if="level >= 2" style="width:28px"></th>
          <th>一级科目</th>
          <th v-if="level >= 2">二级项目部</th>
          <th v-if="level >= 3">三级科目明细</th>
          <th class="amt">金额</th>
          <th class="col-mom">环比</th>
          <th class="col-trend">趋势</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="row.l1_id">
          <!-- L1 row -->
          <tr
            :class="[
              'l1-row',
              level >= 2 ? 'clickable' : '',
              row.is_calculated ? 'l1-calc' : '',
              (row.is_calculated && parseFloat(row.amount) < 0) ? 'l1-calc-neg' : '',
              row.l1_id === dupRowId ? 'l1-bottomline' : '',
            ]"
            @click="level >= 2 && toggle(row.l1_id)"
          >
            <td v-if="level >= 2" class="toggle-cell">
              <span class="toggle-icon">{{ collapsed.has(row.l1_id) ? '›' : '⌄' }}</span>
            </td>
            <td class="l1-name" :colspan="level >= 3 ? 3 : 1">{{ row.l1_name }}</td>
            <td v-if="level >= 2 && level < 3"></td>
            <td class="amt l1-amt" :class="row.amount < 0 ? 'amt-red' : ''">{{ fmt(row.amount) }}</td>
            <td class="col-mom mom-pill" :class="momCls(row.mom)">{{ momTxt(row.mom) }}</td>
            <td class="col-trend">
              <svg
                v-if="sparkById[row.l1_id]" class="spark" :class="momCls(row.mom)"
                :width="SPARK_W" :height="SPARK_H" :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
              >
                <polyline :points="sparkById[row.l1_id].points" fill="none" stroke-width="1.4"
                          stroke-linejoin="round" stroke-linecap="round" />
                <circle :cx="sparkById[row.l1_id].cx" :cy="sparkById[row.l1_id].cy" r="1.7" />
              </svg>
              <span v-else class="spark-na">—</span>
            </td>
          </tr>

          <!-- L2 rows -->
          <template v-if="level >= 2 && !collapsed.has(row.l1_id)">
            <template v-for="l2 in (row.children || [])" :key="l2.l2_id">
              <tr class="l2-row">
                <td></td>
                <td></td>
                <td class="l2-name">{{ l2.l2_name }}</td>
                <td v-if="level >= 3"></td>
                <td class="amt" :class="l2.amount < 0 ? 'amt-red' : ''">{{ fmt(l2.amount) }}</td>
                <td class="col-mom"></td>
                <td class="col-trend"></td>
              </tr>

              <!-- L3 rows -->
              <template v-if="level >= 3">
                <tr v-for="l3 in (l2.children || [])" :key="l3.l3_id" class="l3-row">
                  <td></td>
                  <td></td>
                  <td></td>
                  <td class="l3-name">{{ l3.l3_name }}</td>
                  <td class="amt" :class="l3.amount < 0 ? 'amt-red' : ''">{{ fmt(l3.amount) }}</td>
                  <td class="col-mom"></td>
                  <td class="col-trend"></td>
                </tr>
              </template>
            </template>
          </template>
        </template>

        <!-- Total row (only when it doesn't duplicate a bottom-line L1 row) -->
        <tr v-if="showTotalRow" class="total-row">
          <td v-if="level >= 2"></td>
          <td :colspan="level >= 3 ? 3 : (level >= 2 ? 2 : 1)" style="font-weight:700">{{ totalLabel }}</td>
          <td class="amt total-amt" :class="total < 0 ? 'amt-red' : ''">{{ fmt(total) }}</td>
          <td class="col-mom"></td>
          <td class="col-trend"></td>
        </tr>
      </tbody>
    </table>

    <div v-if="!rows.length" class="empty">
      <div class="icon">📭</div>本期暂无数据
    </div>
  </div>
</template>

<style scoped>
/* 财务报表专用紧凑排版：比全局表格更密，便于一屏看更多科目 */
.table-wrap :is(th, td) { padding: 5px 12px; font-size: 13px; }
.table-wrap th { font-size: 11px; }

.clickable { cursor: pointer; }
.clickable:hover td { background: rgba(201,99,66,.04); }
.toggle-cell { width: 32px; color: var(--muted); font-size: 14px; text-align: center; }
.toggle-icon { display: inline-block; transition: transform .15s; }

.l1-row td { font-weight: 600; background: rgba(201,99,66,.03); }
.l1-calc td { background: rgba(201,99,66,.07); font-style: italic; }
.l1-calc-neg td { background: rgba(198,40,40,.08) !important; box-shadow: inset 3px 0 0 rgba(198,40,40,.55); }
.l1-name { font-weight: 700; }

/* bottom-line row (经营净利) doubles as the report total */
.l1-bottomline td {
  border-top: 2px solid var(--border) !important;
  background: rgba(201,99,66,.08) !important;
  font-size: 13px; font-style: normal !important;
}
.l1-bottomline .l1-name { font-weight: 800; }
.l1-bottomline .l1-amt { font-size: 14px; color: var(--primary); }
.l1-bottomline.l1-calc-neg .l1-amt { color: var(--danger); }
.l1-amt { font-weight: 700; font-size: 13px; }
.l2-row td { background: transparent; }
.l2-name { color: var(--text); padding-left: 20px !important; }
.l3-row td { background: rgba(200,185,170,.05); }
.l3-name { color: var(--muted); padding-left: 36px !important; font-size: 12px; }

.total-row td {
  font-weight: 800; border-top: 2px solid var(--border);
  background: rgba(201,99,66,.06); font-size: 13px;
}
.total-amt { font-size: 14px; color: var(--primary); }

/* ── 环比 / 趋势列 ─────────────────────────────────────────────────────────── */
.col-mom { width: 64px; text-align: right; white-space: nowrap; }
.col-trend { width: 64px; text-align: center; }
.mom-pill { font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.mom-up   { color: #2e7d32; }
.mom-down { color: var(--danger); }
.mom-na   { color: var(--muted); font-weight: 400; }
.spark { vertical-align: middle; }
.spark polyline { stroke: currentColor; }
.spark circle { fill: currentColor; }
.spark.mom-na { color: var(--muted); opacity: .6; }
.spark-na { color: var(--muted); opacity: .5; }
</style>
