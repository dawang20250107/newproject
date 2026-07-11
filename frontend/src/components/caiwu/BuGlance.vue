<script setup>
// 事业部速览：可见事业部 ≤2 时替代驾驶舱的四张结构图（收入构成饼图、
// 毛利贡献条、当月收入/毛利柱、YTD达成率柱）——一两个主体撑不起
// 构成图和对比图，改为每个事业部一行叙事：收入/毛利双条 + 净利 +
// YTD达成对时间进度的「跑赢/落后」判断。点击行下钻。
import { computed } from 'vue'
import { fmtCompact } from '../../utils/format.js'

const props = defineProps({
  rows: { type: Array, default: () => [] },   // buMatrix 行：{bu, rev, gross, prof, share, grossMargin, ytdRate, loss}
  timeProgress: { type: Number, default: 0 }, // 时间进度 %
})
const emit = defineEmits(['drill'])

const fmt = v => fmtCompact(v, { smallRound: true, dash: '—', trim: true })
const sign = v => (v == null ? '—' : (v >= 0 ? '+' : '−') + fmt(Math.abs(v)))
const maxVal = computed(() => Math.max(1, ...props.rows.map(r => Math.max(r.rev || 0, Math.abs(r.gross || 0)))))

// YTD达成 vs 时间进度：跑赢/落后多少个百分点
function pace(r) {
  if (r.ytdRate == null) return { text: '未设目标', cls: 'mute' }
  const d = r.ytdRate - props.timeProgress
  if (d >= 0) return { text: `跑赢时间 +${d.toFixed(0)}pp`, cls: 'pos' }
  return { text: `落后时间 ${d.toFixed(0)}pp`, cls: d >= -10 ? 'warn' : 'neg' }
}
const SHARE_COLORS = ['#2e7d32', '#1565c0']
</script>

<template>
  <div class="bg-root">
    <!-- 双事业部时的收入分成条 -->
    <div v-if="rows.length > 1" class="bg-share">
      <span class="bg-share-lbl">收入占比</span>
      <div class="bg-share-bar">
        <div v-for="(r, i) in rows" :key="r.bu" class="bg-share-seg"
             :style="{ width: (r.share || 0) + '%', background: SHARE_COLORS[i % 2] }"
             :title="`${r.bu} ${r.share == null ? '—' : r.share.toFixed(0) + '%'}`">
          <span v-if="(r.share || 0) > 15" class="bg-share-txt">{{ r.bu }} {{ r.share == null ? '' : r.share.toFixed(0) + '%' }}</span>
        </div>
      </div>
    </div>

    <button v-for="r in rows" :key="r.bu" class="bg-row" @click="emit('drill', r.bu)">
      <span class="bg-bu">{{ r.bu }}<i class="bg-drill">下钻 ›</i></span>
      <div class="bg-bars">
        <div class="bg-bar-line">
          <i class="bg-bar rev" :style="{ width: (Math.max(r.rev || 0, 0) / maxVal) * 100 + '%' }"></i>
          <span class="bg-val">收入 {{ fmt(r.rev) }}</span>
        </div>
        <div class="bg-bar-line">
          <i class="bg-bar" :class="(r.gross ?? 0) >= 0 ? 'gross' : 'gross-neg'"
             :style="{ width: (Math.abs(r.gross || 0) / maxVal) * 100 + '%' }"></i>
          <span class="bg-val" :class="{ neg: (r.gross ?? 0) < 0 }">
            毛利 {{ fmt(r.gross) }}<small v-if="r.grossMargin != null">（{{ r.grossMargin.toFixed(1) }}%）</small>
          </span>
        </div>
      </div>
      <span class="bg-prof" :class="(r.prof ?? 0) >= 0 ? 'pos' : 'neg'">净利 {{ sign(r.prof) }}</span>
      <span class="bg-pace" :class="pace(r).cls">
        <template v-if="r.ytdRate != null">YTD {{ r.ytdRate.toFixed(0) }}% · </template>{{ pace(r).text }}
      </span>
    </button>
  </div>
</template>

<style scoped>
.bg-root { padding: 2px; }
.pos { color: #2e7d32; }
.neg { color: #c62828; }
.warn { color: #e65100; }
.mute { color: var(--muted); }

.bg-share { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.bg-share-lbl { flex: 0 0 auto; font-size: 12px; color: var(--muted); font-weight: 600; }
.bg-share-bar { flex: 1; display: flex; height: 24px; border-radius: 7px; overflow: hidden; background: rgba(0,0,0,0.03); }
.bg-share-seg { height: 100%; min-width: 2px; display: flex; align-items: center; justify-content: center; }
.bg-share-seg + .bg-share-seg { border-left: 2px solid rgba(255,255,255,0.85); }
.bg-share-txt { font-size: 11px; font-weight: 700; color: #fff; white-space: nowrap; text-shadow: 0 1px 2px rgba(0,0,0,0.25); padding: 0 6px; }

.bg-row {
  display: flex; align-items: center; gap: 14px; width: 100%;
  border: none; background: none; cursor: pointer; text-align: left;
  padding: 12px 8px; border-radius: 10px; transition: background .15s;
}
.bg-row:hover { background: rgba(180,140,110,0.07); }
.bg-row + .bg-row { border-top: 1px dashed rgba(150,120,100,0.18); }
.bg-bu { flex: 0 0 96px; font-size: 14px; font-weight: 800; color: var(--text); }
.bg-drill { font-style: normal; font-size: 10.5px; color: var(--muted); font-weight: 500; margin-left: 5px; opacity: 0; transition: opacity .15s; }
.bg-row:hover .bg-drill { opacity: 1; }
.bg-bars { flex: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.bg-bar-line { display: flex; align-items: center; gap: 8px; }
.bg-bar { display: block; height: 12px; border-radius: 6px; min-width: 3px; transition: width .35s ease; }
.bg-bar.rev { background: linear-gradient(90deg, #81c784, #2e7d32); }
.bg-bar.gross { background: linear-gradient(90deg, #4db6ac, #00897b); }
.bg-bar.gross-neg { background: linear-gradient(90deg, #ef5350, #c62828); }
.bg-val { font-size: 12px; color: var(--muted); font-weight: 600; white-space: nowrap; }
.bg-val.neg { color: #c62828; }
.bg-val small { font-weight: 600; opacity: 0.85; }
.bg-prof { flex: 0 0 auto; font-size: 13px; font-weight: 800; }
.bg-pace { flex: 0 0 150px; text-align: right; font-size: 12px; font-weight: 700; }
</style>
