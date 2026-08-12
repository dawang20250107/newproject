<script setup>
// 经营全景 Mekko（驾驶舱专属图）：柱宽 = 当月收入规模，柱内分段 = 每一元
// 收入的去向（成本 / 期间费用 / 净利），柱顶 = 净利率。
// 一张图同时回答三个问题：节奏怎么走（宽度序列）、收入怎么变成利润（分段）、
// 质量有没有恶化（绿段厚度与净利率走势）。替代原「经营趋势全景」双轴组合图
// 与「利润形成瀑布」对读卡（后者与比率条信息重复）。
// 亏损月：成本+费用超过收入，分段按支出归一化，柱顶红标亏损率。
import { computed } from 'vue'
import { fmtCompact } from '../../utils/format.js'

const props = defineProps({
  months: { type: Array, default: () => [] },  // [{label, rev, gross, prof, target}]，label 可为月份或事业部
  height: { type: String, default: '300px' },
  hint: { type: String, default: '柱宽 = 当月收入规模 · 悬浮看明细 · 点击月份可下钻' },
})
const emit = defineEmits(['month-click'])

const fmt = v => fmtCompact(v, { smallRound: true, dash: '—', trim: true })

const cols = computed(() => {
  const rows = props.months.filter(m => (m.rev || 0) > 0)
  const totalRev = rows.reduce((s, m) => s + m.rev, 0) || 1
  return rows.map(m => {
    const cost = m.rev - (m.gross ?? 0)
    const expense = (m.gross ?? 0) - (m.prof ?? 0)
    const prof = m.prof ?? 0
    const margin = (prof / m.rev) * 100
    const loss = prof < 0
    // 盈利月按收入归一化；亏损月按总支出归一化（成本+费用撑满柱身，亏损红标）
    const denom = loss ? cost + expense : m.rev
    const seg = v => Math.max((v / (denom || 1)) * 100, 0)
    return {
      ...m, cost, expense, prof, margin, loss,
      widthPct: Math.max((m.rev / totalRev) * 100, 3),
      costPct: seg(cost), expPct: seg(expense), profPct: loss ? 0 : seg(prof),
      rate: m.target ? (m.rev / m.target) * 100 : null,
    }
  })
})
const widthSum = computed(() => cols.value.reduce((s, c) => s + c.widthPct, 0) || 1)

function colTitle(c) {
  const lines = [
    `${c.label}：收入 ${fmt(c.rev)}${c.rate != null ? `（目标达成 ${c.rate.toFixed(0)}%）` : ''}`,
    `成本 ${fmt(c.cost)}（${((c.cost / c.rev) * 100).toFixed(0)}%）`,
    `期间费用 ${fmt(c.expense)}（${((c.expense / c.rev) * 100).toFixed(0)}%）`,
    `${c.loss ? '亏损' : '净利'} ${fmt(Math.abs(c.prof))}（${c.margin.toFixed(1)}%）`,
  ]
  return lines.join('\n')
}
</script>

<template>
  <div v-if="!cols.length" class="mk-empty">暂无已发布的收入数据</div>
  <div v-else class="mk-root" :style="`height:${height}`">
    <div class="mk-canvas">
      <div v-for="c in cols" :key="c.label" class="mk-col"
           :style="{ width: (c.widthPct / widthSum) * 100 + '%' }"
           :title="colTitle(c)"
           @click="emit('month-click', c)">
        <!-- 柱顶净利率 -->
        <div class="mk-margin" :class="c.loss ? 'neg' : 'pos'">
          {{ c.loss ? '' : '+' }}{{ c.margin.toFixed(c.widthPct > 8 ? 1 : 0) }}%
        </div>
        <!-- 柱身：自上而下 净利(绿) / 费用(琥珀) / 成本(赭) -->
        <div class="mk-body" :class="{ loss: c.loss }">
          <div v-if="!c.loss" class="mk-seg mk-prof" :style="{ height: c.profPct + '%' }">
            <span v-if="c.profPct > 9 && c.widthPct > 7" class="mk-seg-lbl">净利 {{ fmt(c.prof) }}</span>
          </div>
          <div class="mk-seg mk-exp" :style="{ height: c.expPct + '%' }">
            <span v-if="c.expPct > 9 && c.widthPct > 7" class="mk-seg-lbl">费用 {{ fmt(c.expense) }}</span>
          </div>
          <div class="mk-seg mk-cost" :style="{ height: c.costPct + '%' }">
            <span v-if="c.costPct > 12 && c.widthPct > 7" class="mk-seg-lbl">成本 {{ fmt(c.cost) }}</span>
          </div>
        </div>
        <!-- 底部：月份 + 收入规模 -->
        <div class="mk-foot">
          <div class="mk-mo">{{ c.label }}</div>
          <div v-if="c.widthPct > 6" class="mk-rev">{{ fmt(c.rev) }}</div>
        </div>
      </div>
    </div>
    <div class="mk-legend">
      <span class="mk-lg"><i class="mk-i-prof"></i>净利</span>
      <span class="mk-lg"><i class="mk-i-exp"></i>期间费用</span>
      <span class="mk-lg"><i class="mk-i-cost"></i>成本</span>
      <span class="mk-lg"><i class="mk-i-loss"></i>亏损月（红框+红字）</span>
      <span class="mk-hint">{{ hint }}</span>
    </div>
  </div>
</template>

<style scoped>
.mk-root { display: flex; flex-direction: column; width: 100%; }
.mk-canvas {
  flex: 1; display: flex; align-items: stretch; gap: 3px;
  min-height: 140px; padding-top: 18px;
}
.mk-col {
  display: flex; flex-direction: column; min-width: 0; cursor: pointer;
  transition: filter .15s;
}
.mk-col:hover { filter: brightness(1.06); }

.mk-margin {
  height: 16px; line-height: 16px; text-align: center;
  font-size: 10.5px; font-weight: 800; white-space: nowrap; overflow: visible;
}
.mk-margin.pos { color: #2e7d32; }
.mk-margin.neg { color: #c62828; }

.mk-body {
  flex: 1; display: flex; flex-direction: column;
  border-radius: 5px 5px 0 0; overflow: hidden;
  background: rgba(0,0,0,0.02);
}
.mk-body.loss { box-shadow: inset 0 0 0 2px rgba(198,40,40,0.75); }

.mk-seg { position: relative; min-height: 0; transition: height .35s ease; }
.mk-prof { background: linear-gradient(180deg, #66bb6a, #2e7d32); }
.mk-exp  { background: linear-gradient(180deg, #ffc46b, #f0932b); }
.mk-cost { background: linear-gradient(180deg, #c8a288, #9a7259); }
.mk-seg + .mk-seg { border-top: 2px solid rgba(255,255,255,0.85); }
.mk-seg-lbl {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 10.5px; font-weight: 700; color: #fff; white-space: nowrap;
  text-shadow: 0 1px 2px rgba(0,0,0,0.28); overflow: hidden;
}

.mk-foot { height: 30px; padding-top: 4px; text-align: center; }
.mk-mo { font-size: 11px; font-weight: 700; color: var(--text); line-height: 1.2; }
.mk-rev { font-size: 10px; color: var(--muted); line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.mk-legend {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  margin-top: 8px; font-size: 11px; color: var(--muted);
}
.mk-lg { display: inline-flex; align-items: center; gap: 5px; }
.mk-lg i { width: 10px; height: 10px; border-radius: 3px; }
.mk-i-prof { background: #2e7d32; }
.mk-i-exp { background: #f0932b; }
.mk-i-cost { background: #9a7259; }
.mk-i-loss { background: none; box-shadow: inset 0 0 0 2px rgba(198,40,40,0.75); }
.mk-hint { margin-left: auto; }

.mk-empty {
  display: flex; align-items: center; justify-content: center;
  height: 180px; color: var(--muted); font-size: 13px;
}
</style>
