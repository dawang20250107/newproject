<script setup>
// 资金故事卡：数据稀疏时替代时间轴图表的叙事呈现。
// 设计原则：数据少讲结论（大数字 + 一句话），数据多讲结构（完整图表）。
// 组成：① 流入→流出→净额 大数字行 + 自动结论
//       ② 单行资金流条（桑基简化版：两条等比条对读，净留存/消耗存量补齐差额）
//       ③ 有效月迷你行（仅画发生现金流的月份，点击定位月度明细）
import { computed } from 'vue'
import { fmtCompact } from '../../utils/format.js'

const props = defineProps({
  inflows: { type: Array, default: () => [] },   // [{name, value, color}] 已滤零
  outflows: { type: Array, default: () => [] },
  net: { type: Number, default: 0 },
  cumulativeEnd: { type: Number, default: null },
  months: { type: Array, default: () => [] },    // [{ym, label, inflow, outflow, net}] 仅有效月
  totalMonths: { type: Number, default: 0 },
  budgetColl: { type: Number, default: 0 },      // 收款预算（有则显示达成对照）
  budgetPay: { type: Number, default: 0 },
  collAchieve: { type: Number, default: null },  // 实收/收款预算 %
  payAchieve: { type: Number, default: null },
})
const emit = defineEmits(['month-click'])

const fmtWan = v => fmtCompact(v, { smallRound: true, dash: '0', trim: true })
const sign = v => (v >= 0 ? '+' : '−') + fmtWan(Math.abs(v))

const inTotal = computed(() => props.inflows.reduce((a, s) => a + s.value, 0))
const outTotal = computed(() => props.outflows.reduce((a, s) => a + s.value, 0))
const scaleMax = computed(() => Math.max(inTotal.value, outTotal.value, 1))

// 两条等长可对读：净流出时流入条补「消耗存量」段，净流入时流出条补「净留存」段
const inSegs = computed(() => {
  const segs = props.inflows.map(s => ({ ...s, pct: (s.value / scaleMax.value) * 100 }))
  if (props.net < 0) segs.push({ name: '消耗存量', value: -props.net, gap: true, pct: (-props.net / scaleMax.value) * 100 })
  return segs
})
const outSegs = computed(() => {
  const segs = props.outflows.map(s => ({ ...s, pct: (s.value / scaleMax.value) * 100 }))
  if (props.net > 0) segs.push({ name: '净留存', value: props.net, keep: true, pct: (props.net / scaleMax.value) * 100 })
  return segs
})
const legendSegs = computed(() => [...inSegs.value, ...outSegs.value])

// 自动结论：主要来源 / 主要去向 / 预收依赖预警
const conclusion = computed(() => {
  const parts = []
  const topIn = [...props.inflows].sort((a, b) => b.value - a.value)[0]
  const topOut = [...props.outflows].sort((a, b) => b.value - a.value)[0]
  if (topIn && inTotal.value) parts.push(`流入主要来自「${topIn.name}」（占 ${((topIn.value / inTotal.value) * 100).toFixed(0)}%）`)
  if (topOut && outTotal.value) parts.push(`流出以「${topOut.name}」为主（占 ${((topOut.value / outTotal.value) * 100).toFixed(0)}%）`)
  const adv = props.inflows.find(s => s.name === '预收款')
  if (adv && inTotal.value && adv.value / inTotal.value > 0.5) parts.push('⚠ 流入过半依赖预收，关注后续交付兑现')
  return parts.join('；')
})

const monthMax = computed(() => Math.max(1, ...props.months.map(m => Math.max(m.inflow, m.outflow))))
function segColor(s) {
  if (s.gap) return 'repeating-linear-gradient(45deg, rgba(198,40,40,.55) 0 6px, rgba(198,40,40,.35) 6px 12px)'
  if (s.keep) return 'linear-gradient(180deg, #42a5f5, #1565c0)'
  return s.color
}
</script>

<template>
  <div class="cs-root">
    <!-- ① 大数字结论行 -->
    <div class="cs-numline">
      <span class="cs-chip cs-in">流入 <b>{{ fmtWan(inTotal) }}</b></span>
      <span class="cs-arr">−</span>
      <span class="cs-chip cs-out">流出 <b>{{ fmtWan(outTotal) }}</b></span>
      <span class="cs-arr">=</span>
      <span class="cs-net" :class="net >= 0 ? 'pos' : 'neg'">
        {{ sign(net) }}<small>{{ net >= 0 ? '净造血' : '净失血' }}</small>
      </span>
    </div>
    <div v-if="collAchieve != null || payAchieve != null" class="cs-budget">
      <span v-if="collAchieve != null" class="cs-bd">
        收款达成 <b :class="collAchieve >= 100 ? 'pos' : 'warn'">{{ collAchieve.toFixed(0) }}%</b>
        <small>预算 {{ fmtWan(budgetColl) }}</small>
      </span>
      <span v-if="payAchieve != null" class="cs-bd">
        付款执行 <b :class="payAchieve > 100 ? 'warn' : ''">{{ payAchieve.toFixed(0) }}%</b>
        <small>预算 {{ fmtWan(budgetPay) }}</small>
      </span>
    </div>
    <div v-if="conclusion || cumulativeEnd != null" class="cs-conclusion">
      {{ conclusion }}<template v-if="cumulativeEnd != null"><template v-if="conclusion">；</template>期末资金池
        <b :class="cumulativeEnd >= 0 ? 'pos' : 'neg'">{{ sign(cumulativeEnd) }}</b></template>
    </div>

    <!-- ② 单行资金流条 -->
    <div class="cs-flow">
      <div class="cs-bar-row">
        <span class="cs-bar-lbl">流入</span>
        <div class="cs-bar">
          <div v-if="!inSegs.length" class="cs-seg-none">本期无流入</div>
          <div v-for="s in inSegs" :key="s.name" class="cs-seg"
               :style="{ width: s.pct + '%', background: segColor(s) }"
               :title="`${s.name} ${fmtWan(s.value)}`">
            <span v-if="s.pct > 18" class="cs-seg-lbl">{{ s.name }} {{ fmtWan(s.value) }}</span>
          </div>
        </div>
      </div>
      <div class="cs-bar-row">
        <span class="cs-bar-lbl">流出</span>
        <div class="cs-bar">
          <div v-if="!outSegs.length" class="cs-seg-none">本期无流出</div>
          <div v-for="s in outSegs" :key="s.name" class="cs-seg"
               :style="{ width: s.pct + '%', background: segColor(s) }"
               :title="`${s.name} ${fmtWan(s.value)}`">
            <span v-if="s.pct > 18" class="cs-seg-lbl">{{ s.name }} {{ fmtWan(s.value) }}</span>
          </div>
        </div>
      </div>
      <div class="cs-legend">
        <span v-for="s in legendSegs" :key="s.name" class="cs-lg">
          <i :style="{ background: segColor(s) }"></i>{{ s.name }} {{ fmtWan(s.value) }}
        </span>
      </div>
    </div>

    <!-- ③ 有效月迷你行 -->
    <div v-if="months.length" class="cs-months">
      <div class="cs-months-head">发生现金流的月份（{{ months.length }}/{{ totalMonths }}）· 点击定位明细</div>
      <button v-for="m in months" :key="m.ym" class="cs-month"
              :title="`${m.label}：流入 ${fmtWan(m.inflow)} · 流出 ${fmtWan(m.outflow)} · 净 ${sign(m.net)}`"
              @click="emit('month-click', m.ym)">
        <span class="cs-m-lbl">{{ m.label }}</span>
        <span class="cs-m-bars">
          <i class="mi" :style="{ width: (m.inflow / monthMax) * 100 + '%' }"></i>
          <i class="mo" :style="{ width: (m.outflow / monthMax) * 100 + '%' }"></i>
        </span>
        <span class="cs-m-net" :class="m.net >= 0 ? 'pos' : 'neg'">{{ sign(m.net) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.cs-root { padding: 6px 2px 2px; }
.pos { color: #2e7d32; }
.neg { color: #c62828; }

/* ① 大数字行 */
.cs-numline { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.cs-chip {
  display: inline-flex; align-items: baseline; gap: 7px;
  padding: 9px 16px; border-radius: 12px; font-size: 13px; color: var(--muted);
}
.cs-chip b { font-size: 22px; font-weight: 800; letter-spacing: -0.3px; }
.cs-in  { background: rgba(46,125,50,0.08); }
.cs-in b { color: #2e7d32; }
.cs-out { background: rgba(230,81,0,0.08); }
.cs-out b { color: #e65100; }
.cs-arr { font-size: 18px; color: var(--muted); font-weight: 600; }
.cs-net {
  display: inline-flex; align-items: baseline; gap: 8px;
  font-size: 30px; font-weight: 900; letter-spacing: -0.5px;
}
.cs-net small { font-size: 13px; font-weight: 700; opacity: 0.85; }
.cs-conclusion { margin-top: 10px; font-size: 12.5px; color: var(--muted); line-height: 1.7; }
.cs-conclusion b { font-weight: 800; }
.warn { color: #e65100; }

/* 预算达成对照 chips */
.cs-budget { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; }
.cs-bd {
  display: inline-flex; align-items: baseline; gap: 6px;
  font-size: 12px; color: var(--muted);
  padding: 4px 10px; border-radius: 9px; background: rgba(180,140,110,0.07);
}
.cs-bd b { font-size: 14px; font-weight: 800; }
.cs-bd small { font-size: 11px; opacity: 0.8; }

.cs-seg-none {
  flex: 1; display: flex; align-items: center; justify-content: center;
  font-size: 11.5px; color: var(--muted);
  background: repeating-linear-gradient(45deg, rgba(0,0,0,.03) 0 8px, transparent 8px 16px);
}

/* ② 资金流条 */
.cs-flow { margin-top: 16px; }
.cs-bar-row { display: flex; align-items: center; gap: 10px; }
.cs-bar-row + .cs-bar-row { margin-top: 8px; }
.cs-bar-lbl { flex: 0 0 30px; font-size: 12px; color: var(--muted); font-weight: 600; text-align: right; }
.cs-bar { flex: 1; display: flex; height: 30px; border-radius: 8px; overflow: hidden; background: rgba(0,0,0,0.03); }
.cs-seg {
  height: 100%; min-width: 2px; display: flex; align-items: center; justify-content: center;
  transition: width .35s ease;
}
.cs-seg + .cs-seg { border-left: 2px solid rgba(255,255,255,0.85); }
.cs-seg-lbl {
  font-size: 11px; font-weight: 700; color: #fff; white-space: nowrap;
  text-shadow: 0 1px 2px rgba(0,0,0,0.25); padding: 0 6px;
}
.cs-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 8px 0 0 40px; }
.cs-lg { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--muted); }
.cs-lg i { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }

/* ③ 有效月迷你行 */
.cs-months { margin-top: 18px; border-top: 1px dashed rgba(150,120,100,0.25); padding-top: 12px; }
.cs-months-head { font-size: 11.5px; color: var(--muted); margin-bottom: 8px; }
.cs-month {
  display: flex; align-items: center; gap: 10px; width: 100%;
  border: none; background: none; cursor: pointer; text-align: left;
  padding: 5px 8px; border-radius: 8px; transition: background .15s;
}
.cs-month:hover { background: rgba(180,140,110,0.08); }
.cs-m-lbl { flex: 0 0 44px; font-size: 12px; font-weight: 700; color: var(--text); }
.cs-m-bars { flex: 1; display: flex; flex-direction: column; gap: 3px; }
.cs-m-bars i { display: block; height: 8px; border-radius: 4px; min-width: 2px; transition: width .35s ease; }
.cs-m-bars .mi { background: linear-gradient(90deg, #81c784, #2e7d32); }
.cs-m-bars .mo { background: linear-gradient(90deg, #ffa726, #e65100); }
.cs-m-net { flex: 0 0 88px; text-align: right; font-size: 12.5px; font-weight: 800; }
</style>
