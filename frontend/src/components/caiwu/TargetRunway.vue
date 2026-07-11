<script setup>
// 年度目标射程图（目标分解专属图）：替代「年度目标 vs YTD实际」绝对值簇状柱
// ——绝对值下大事业部把小事业部压成看不见，且数字与下方明细表重复。
// 每行按自身年度目标归一（100% = 目标线），大小事业部同等可读：
//   实条 = YTD 达成，橙色竖线 = 时间进度（今天该走到哪），◆ = 全年预测落点。
// 一眼回答目标分解的第一问题：照这个节奏，年底谁达成、谁堵不上、差多少。
import { computed } from 'vue'
import { fmtCompact } from '../../utils/format.js'

const props = defineProps({
  rows: { type: Array, default: () => [] },   // [{bu, target, ytd, ach, projected}] target>0
  timeProgress: { type: Number, default: 0 }, // 时间进度 %
})
const emit = defineEmits(['select'])

const fmt = v => fmtCompact(v, { smallRound: true, dash: '—', trim: true })

const items = computed(() => {
  const rows = props.rows.map(r => {
    const projPct = r.projected != null && r.target ? (r.projected / r.target) * 100 : null
    const gap = r.projected != null ? r.projected - r.target : null
    return { ...r, projPct, gap }
  })
  // 预测达成最低的排最上（最该盯）；无预测的按 YTD 达成排，统一殿后
  rows.sort((a, b) => {
    if (a.projPct != null && b.projPct != null) return a.projPct - b.projPct
    if (a.projPct != null) return -1
    if (b.projPct != null) return 1
    return (a.ach ?? 999) - (b.ach ?? 999)
  })
  return rows
})
// 全体共用一个横轴刻度：max(110, 最大预测/达成)，封顶 160 防超额爆表压扁他行
const scaleMax = computed(() => Math.min(160,
  Math.max(110, ...items.value.map(r => Math.max(r.ach || 0, r.projPct || 0)))))
const pos = pct => Math.min((pct / scaleMax.value) * 100, 100)

function barClass(r) {
  if ((r.ach ?? 0) >= 100) return 'done'
  if ((r.ach ?? 0) >= props.timeProgress) return 'ontrack'
  return (props.timeProgress - (r.ach ?? 0)) > 10 ? 'behind' : 'warn'
}
</script>

<template>
  <div class="tr-root">
    <button v-for="r in items" :key="r.bu" class="tr-row" @click="emit('select', r.bu)">
      <span class="tr-bu">{{ r.bu }}</span>
      <div class="tr-track">
        <!-- 目标线（100%） -->
        <i class="tr-goal" :style="{ left: pos(100) + '%' }"></i>
        <!-- 时间进度 -->
        <i class="tr-time" :style="{ left: pos(timeProgress) + '%' }"></i>
        <!-- YTD 达成条 -->
        <i class="tr-fill" :class="barClass(r)" :style="{ width: pos(r.ach || 0) + '%' }"></i>
        <!-- 全年预测落点 -->
        <i v-if="r.projPct != null" class="tr-proj" :class="r.projPct >= 100 ? 'ok' : 'miss'"
           :style="{ left: pos(r.projPct) + '%' }" :title="`全年预测 ${fmt(r.projected)}（${r.projPct.toFixed(0)}%）`"></i>
      </div>
      <span class="tr-nums">
        <b :class="barClass(r)">{{ r.ach == null ? '—' : r.ach.toFixed(0) + '%' }}</b>
        <template v-if="r.projPct != null">
          <span class="tr-proj-txt" :class="r.gap >= 0 ? 'ok' : 'miss'">
            预测 {{ r.projPct.toFixed(0) }}%（{{ r.gap >= 0 ? '超' : '缺' }}{{ fmt(Math.abs(r.gap)) }}）
          </span>
        </template>
        <span v-else class="tr-proj-txt mute">无预测</span>
      </span>
    </button>
    <div class="tr-legend">
      <span class="tr-lg"><i class="lg-fill"></i>YTD 达成</span>
      <span class="tr-lg"><i class="lg-time"></i>时间进度 {{ timeProgress }}%</span>
      <span class="tr-lg"><i class="lg-goal"></i>年度目标 100%</span>
      <span class="tr-lg"><i class="lg-proj"></i>全年预测落点（绿=够到 / 红=堵不上）</span>
    </div>
  </div>
</template>

<style scoped>
.tr-root { padding: 2px 0; }
.tr-row {
  display: flex; align-items: center; gap: 12px; width: 100%;
  border: none; background: none; cursor: pointer; text-align: left;
  padding: 9px 8px; border-radius: 10px; transition: background .15s;
}
.tr-row:hover { background: rgba(180,140,110,0.07); }
.tr-row + .tr-row { border-top: 1px dashed rgba(150,120,100,0.16); }
.tr-bu { flex: 0 0 96px; font-size: 13px; font-weight: 700; color: var(--text); }

.tr-track {
  flex: 1; position: relative; height: 18px;
  background: rgba(0,0,0,0.045); border-radius: 9px; overflow: visible;
}
.tr-fill {
  position: absolute; left: 0; top: 0; bottom: 0; border-radius: 9px;
  min-width: 2px; transition: width .35s ease;
}
.tr-fill.done    { background: linear-gradient(90deg, #66bb6a, #2e7d32); }
.tr-fill.ontrack { background: linear-gradient(90deg, #81c784, #43a047); }
.tr-fill.warn    { background: linear-gradient(90deg, #ffc46b, #f0932b); }
.tr-fill.behind  { background: linear-gradient(90deg, #ef5350, #c62828); }
.tr-goal {
  position: absolute; top: -3px; bottom: -3px; width: 2px;
  background: rgba(60,50,42,0.65); z-index: 2;
}
.tr-time {
  position: absolute; top: -3px; bottom: -3px; width: 0;
  border-left: 2px dashed rgba(201,99,66,0.85); z-index: 2;
}
.tr-proj {
  position: absolute; top: 50%; width: 11px; height: 11px; z-index: 3;
  transform: translate(-50%, -50%) rotate(45deg);
  border: 2px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
.tr-proj.ok   { background: #2e7d32; }
.tr-proj.miss { background: #c62828; }

.tr-nums { flex: 0 0 210px; text-align: right; font-size: 12px; white-space: nowrap; }
.tr-nums b { font-size: 13.5px; font-weight: 800; }
.tr-nums b.done, .tr-nums b.ontrack { color: #2e7d32; }
.tr-nums b.warn { color: #e65100; }
.tr-nums b.behind { color: #c62828; }
.tr-proj-txt { margin-left: 8px; font-weight: 600; }
.tr-proj-txt.ok { color: #2e7d32; }
.tr-proj-txt.miss { color: #c62828; }
.tr-proj-txt.mute { color: var(--muted); font-weight: 400; }

.tr-legend {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  margin-top: 10px; font-size: 11px; color: var(--muted);
}
.tr-lg { display: inline-flex; align-items: center; gap: 5px; }
.lg-fill { width: 14px; height: 8px; border-radius: 4px; background: linear-gradient(90deg, #81c784, #43a047); }
.lg-time { width: 0; height: 12px; border-left: 2px dashed rgba(201,99,66,0.85); }
.lg-goal { width: 2px; height: 12px; background: rgba(60,50,42,0.65); }
.lg-proj { width: 9px; height: 9px; transform: rotate(45deg); background: #2e7d32; border: 2px solid #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.3); }
</style>
