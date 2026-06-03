<script setup>
import { computed } from 'vue'

// 渲染「环比 + 迷你趋势线」两个 <td>（fragment）。各层级共用，按 level 递减视觉权重，
// 保持表格层次的高可读性：一级最醒目，二/三级逐级淡化、缩小。
const props = defineProps({
  mom: { type: Number, default: null },
  trend: { type: Array, default: null },
  level: { type: Number, default: 1 },  // 1/2/3
})

function momTxt(mom) {
  if (mom == null) return '—'
  return (mom >= 0 ? '▲' : '▼') + Math.abs(mom).toFixed(1) + '%'
}
function momCls(mom) {
  if (mom == null) return 'mom-na'
  return mom >= 0 ? 'mom-up' : 'mom-down'
}

const SPARK_W = 56, SPARK_H = 16, SPARK_PAD = 2
const spark = computed(() => {
  const t = props.trend
  if (!t || t.length < 2) return null
  const min = Math.min(...t), max = Math.max(...t)
  const span = max - min || 1
  const n = t.length
  const iw = SPARK_W - SPARK_PAD * 2, ih = SPARK_H - SPARK_PAD * 2
  const pts = t.map((v, i) => [
    SPARK_PAD + (i / (n - 1)) * iw,
    SPARK_PAD + ih - ((v - min) / span) * ih,
  ])
  const last = pts[pts.length - 1]
  return {
    points: pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '),
    cx: last[0].toFixed(1), cy: last[1].toFixed(1),
  }
})
</script>

<template>
  <td class="col-mom mom-pill" :class="[momCls(mom), `lv${level}`]">{{ momTxt(mom) }}</td>
  <td class="col-trend">
    <svg
      v-if="spark" class="spark" :class="[momCls(mom), `lv${level}`]"
      :width="SPARK_W" :height="SPARK_H" :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
    >
      <polyline :points="spark.points" fill="none" stroke-width="1.4"
                stroke-linejoin="round" stroke-linecap="round" />
      <circle :cx="spark.cx" :cy="spark.cy" r="1.7" />
    </svg>
    <span v-else class="spark-na">—</span>
  </td>
</template>

<style scoped>
/* 自带 padding/width，确保与报表其它单元格行高、列宽对齐 */
.col-mom { width: 64px; padding: 5px 12px; text-align: right; white-space: nowrap; }
.col-trend { width: 64px; padding: 5px 12px; text-align: center; }
.mom-pill { font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.mom-up   { color: #2e7d32; }
.mom-down { color: var(--danger); }
.mom-na   { color: var(--muted); font-weight: 400; }
.spark { vertical-align: middle; }
.spark polyline { stroke: currentColor; }
.spark circle { fill: currentColor; }
.spark.mom-na { color: var(--muted); opacity: .6; }
.spark-na { color: var(--muted); opacity: .5; }

/* 层级递减视觉权重，保持层次可读 */
.lv2 { opacity: .8; }
.lv3 { opacity: .58; }
.lv2.mom-pill, .lv3.mom-pill { font-weight: 600; font-size: 10px; }
svg.lv2 { transform: scale(.9); }
svg.lv3 { transform: scale(.82); }
</style>
