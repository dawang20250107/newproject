<script setup>
// 经营节奏卡：年初/数据稀疏时（已发布月数 ≤2）替代「经营趋势全景」。
// 12 格月度轴只有一两格有柱时，时间轴大图讲不出趋势——改为逐月叙事：
// 每个已发布月一行（收入/毛利双条 + 净利 + 净利率），配自动结论。
import { computed } from 'vue'
import { fmtCompact } from '../../utils/format.js'

const props = defineProps({
  rows: { type: Array, default: () => [] },   // [{label, rev, gross, prof, margin, target}] 仅已发布月
  totalMonths: { type: Number, default: 12 },
})

const fmt = v => fmtCompact(v, { smallRound: true, dash: '—', trim: true })
const sign = v => (v >= 0 ? '+' : '−') + fmt(Math.abs(v))
const maxVal = computed(() => Math.max(1, ...props.rows.map(r => Math.max(r.rev, Math.abs(r.gross)))))

// 自动结论：最新月概况 + 环比方向（≥2 个月时）+ 目标对照
const conclusion = computed(() => {
  const rs = props.rows
  if (!rs.length) return ''
  const last = rs[rs.length - 1]
  const parts = [`最新 ${last.label}：收入 ${fmt(last.rev)}、经营毛利 ${fmt(last.gross)}`]
  if (last.margin != null) parts.push(`净利率 ${last.margin.toFixed(1)}%`)
  if (rs.length >= 2) {
    const prev = rs[rs.length - 2]
    if (prev.rev) {
      const chg = ((last.rev - prev.rev) / Math.abs(prev.rev)) * 100
      parts.push(`收入环比${chg >= 0 ? '增长' : '下降'} ${Math.abs(chg).toFixed(0)}%`)
    }
  } else {
    parts.push('单月数据，节奏待后续月份验证')
  }
  if (last.target) {
    const r = (last.rev / last.target) * 100
    parts.push(`当月目标达成 ${r.toFixed(0)}%`)
  }
  return parts.join('；')
})
</script>

<template>
  <div class="ps-root">
    <div class="ps-head">已发布 {{ rows.length }}/{{ totalMonths }} 个月 · 数据积累后自动切换趋势全景图</div>
    <div v-for="r in rows" :key="r.label" class="ps-row">
      <span class="ps-lbl">{{ r.label }}</span>
      <div class="ps-bars">
        <div class="ps-bar-line">
          <i class="ps-bar rev" :style="{ width: (Math.max(r.rev, 0) / maxVal) * 100 + '%' }"></i>
          <span class="ps-val">收入 {{ fmt(r.rev) }}</span>
        </div>
        <div class="ps-bar-line">
          <i class="ps-bar" :class="r.gross >= 0 ? 'gross' : 'gross-neg'"
             :style="{ width: (Math.abs(r.gross) / maxVal) * 100 + '%' }"></i>
          <span class="ps-val" :class="{ neg: r.gross < 0 }">毛利 {{ fmt(r.gross) }}</span>
        </div>
      </div>
      <span class="ps-prof" :class="r.prof >= 0 ? 'pos' : 'neg'">
        净利 {{ sign(r.prof) }}<small v-if="r.margin != null">（{{ r.margin.toFixed(1) }}%）</small>
      </span>
    </div>
    <div v-if="conclusion" class="ps-conclusion">{{ conclusion }}</div>
  </div>
</template>

<style scoped>
.ps-root { padding: 4px 2px; }
.pos { color: #2e7d32; }
.neg { color: #c62828; }
.ps-head { font-size: 11.5px; color: var(--muted); margin-bottom: 10px; }
.ps-row {
  display: flex; align-items: center; gap: 14px;
  padding: 10px 8px; border-radius: 10px;
}
.ps-row:hover { background: rgba(180,140,110,0.06); }
.ps-row + .ps-row { border-top: 1px dashed rgba(150,120,100,0.18); }
.ps-lbl { flex: 0 0 44px; font-size: 15px; font-weight: 800; color: var(--text); }
.ps-bars { flex: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.ps-bar-line { display: flex; align-items: center; gap: 8px; }
.ps-bar { display: block; height: 12px; border-radius: 6px; min-width: 3px; transition: width .35s ease; }
.ps-bar.rev { background: linear-gradient(90deg, #81c784, #2e7d32); }
.ps-bar.gross { background: linear-gradient(90deg, #4db6ac, #00897b); }
.ps-bar.gross-neg { background: linear-gradient(90deg, #ef5350, #c62828); }
.ps-val { font-size: 12px; color: var(--muted); font-weight: 600; white-space: nowrap; }
.ps-val.neg { color: #c62828; }
.ps-prof { flex: 0 0 auto; font-size: 13px; font-weight: 800; text-align: right; }
.ps-prof small { font-weight: 600; opacity: 0.8; }
.ps-conclusion {
  margin-top: 12px; padding-top: 10px; border-top: 1px dashed rgba(150,120,100,0.25);
  font-size: 12.5px; color: var(--muted); line-height: 1.7;
}
</style>
