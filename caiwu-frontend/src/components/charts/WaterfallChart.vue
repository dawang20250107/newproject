<script setup>
import { computed } from 'vue'

const props = defineProps({
  waterfall: { type: Array, default: () => [] },
  height: { type: String, default: '380px' },
})

const chartData = computed(() => {
  const items = props.waterfall
  if (!items.length) return null

  let running = 0
  const processed = []

  for (const item of items) {
    let lo, hi
    if (item.type === 'base') {
      lo = Math.min(0, item.value)
      hi = Math.max(0, item.value)
      running = item.value
    } else if (item.type === 'total') {
      lo = Math.min(0, item.value)
      hi = Math.max(0, item.value)
    } else {
      lo = Math.min(running, running + item.value)
      hi = Math.max(running, running + item.value)
      running += item.value
    }
    processed.push({
      ...item,
      lo,
      hi,
      barType: item.type === 'base' || item.type === 'total'
        ? 'anchor'
        : item.value >= 0 ? 'increase' : 'decrease',
    })
  }

  const yMin = Math.min(0, ...processed.map(b => b.lo))
  const yMax = Math.max(0, ...processed.map(b => b.hi))
  const yRange = yMax - yMin || 1
  const pct = v => (v - yMin) / yRange * 100

  return {
    bars: processed.map(b => ({
      ...b,
      bottomPct: pct(b.lo),
      heightPct: Math.max(pct(b.hi) - pct(b.lo), 0.8),
      topPct: pct(b.hi),
    })),
    zeroLinePct: pct(0),
  }
})

function fmtAmt(v) {
  const abs = Math.abs(v)
  if (abs >= 100000000) return (v / 100000000).toFixed(2) + '亿'
  if (abs >= 10000) return (v / 10000).toFixed(2) + '万'
  if (abs >= 1000) return (v / 10000).toFixed(4) + '万'
  return v.toFixed(0)
}
</script>

<template>
  <div v-if="!chartData" class="wf-empty">暂无数据</div>
  <div v-else class="wf-root" :style="`height:${height}`">

    <!-- Chart zone -->
    <div class="wf-chart">
      <!-- Zero axis line -->
      <div
        class="wf-zero-line"
        :style="`bottom:${chartData.zeroLinePct}%`"
      ></div>

      <!-- Bar columns -->
      <div class="wf-grid">
        <div
          v-for="(bar, i) in chartData.bars"
          :key="i"
          class="wf-col"
        >
          <!-- Bar body -->
          <div
            class="wf-bar"
            :class="`wf-bar-${bar.barType}`"
            :style="`bottom:${bar.bottomPct}%;height:${bar.heightPct}%;animation-delay:${i * 0.07}s`"
          >
            <div class="wf-bar-inner">
              <div v-if="bar.barType !== 'anchor'" class="wf-shim"></div>
            </div>
          </div>

          <!-- Value label above bar -->
          <div
            class="wf-label"
            :class="`wf-label-${bar.barType}`"
            :style="`bottom:calc(${bar.topPct}% + 4px);animation-delay:${i * 0.07 + 0.2}s`"
          >
            <span v-if="bar.barType === 'increase'" class="wf-arrow">▲</span>
            <span v-if="bar.barType === 'decrease'" class="wf-arrow">▼</span>{{ fmtAmt(bar.value) }}
          </div>
        </div>
      </div>
    </div>

    <!-- Name labels -->
    <div class="wf-names">
      <div
        v-for="(bar, i) in chartData.bars"
        :key="i"
        class="wf-name"
        :class="bar.barType === 'anchor' ? 'wf-name-anchor' : ''"
      >{{ bar.name }}</div>
    </div>
  </div>
</template>

<style scoped>
/* ── Root ─────────────────────────────────────────────── */
.wf-root {
  display: flex;
  flex-direction: column;
  width: 100%;
}

/* ── Chart zone (bars live here) ──────────────────────── */
.wf-chart {
  flex: 1;
  position: relative;
  margin-top: 30px;   /* headroom so labels above tallest bar are visible */
  overflow: visible;
  min-height: 120px;
}

/* Grid of columns, fills the chart zone */
.wf-grid {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  gap: 6px;
  overflow: visible;
}

.wf-col {
  flex: 1;
  min-width: 52px;
  position: relative;
  overflow: visible;
}

/* ── Bar base styles ──────────────────────────────────── */
.wf-bar {
  position: absolute;
  left: 12%;
  right: 12%;
  min-height: 8px;
  border-radius: 6px 6px 4px 4px;
  transform-origin: bottom center;
  animation: wfBarIn 0.45s ease-out both;
}

.wf-bar-inner {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  overflow: hidden;
}

/* ── Anchor bar (gray glass — base/total periods) ─────── */
.wf-bar-anchor {
  background: linear-gradient(
    175deg,
    rgba(178, 163, 151, 0.84) 0%,
    rgba(138, 123, 112, 0.9) 100%
  );
  border: 1px solid rgba(255, 255, 255, 0.22);
  box-shadow:
    0 8px 24px rgba(0, 0, 0, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.38),
    0 0 0 1px rgba(160, 145, 132, 0.22);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* ── Increase bar (A股红 — factor that improved profit) ── */
.wf-bar-increase {
  background: linear-gradient(
    175deg,
    rgba(213, 55, 55, 0.86) 0%,
    rgba(168, 22, 22, 0.92) 100%
  );
  border: 1px solid rgba(255, 135, 135, 0.28);
  box-shadow:
    0 6px 20px rgba(195, 35, 35, 0.44),
    inset 0 1px 0 rgba(255, 195, 195, 0.52),
    0 0 18px rgba(195, 35, 35, 0.22),
    0 0 0 1px rgba(210, 55, 55, 0.28);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* ── Decrease bar (A股绿 — factor that hurt profit) ────── */
.wf-bar-decrease {
  background: linear-gradient(
    175deg,
    rgba(32, 140, 72, 0.86) 0%,
    rgba(16, 100, 48, 0.92) 100%
  );
  border: 1px solid rgba(90, 225, 140, 0.26);
  box-shadow:
    0 6px 20px rgba(25, 135, 65, 0.44),
    inset 0 1px 0 rgba(110, 245, 165, 0.48),
    0 0 18px rgba(25, 135, 65, 0.22),
    0 0 0 1px rgba(40, 162, 85, 0.28);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* ── Shimmer marquee overlay ──────────────────────────── */
.wf-shim {
  position: absolute;
  left: 0;
  right: 0;
  height: 52%;
  background: linear-gradient(
    to bottom,
    transparent 0%,
    rgba(255, 255, 255, 0.33) 50%,
    transparent 100%
  );
  pointer-events: none;
}

.wf-bar-increase .wf-shim {
  animation: wfShimUp 2.4s ease-in-out infinite;
}
.wf-bar-decrease .wf-shim {
  animation: wfShimDown 2.4s ease-in-out infinite;
}

@keyframes wfShimUp {
  0%   { transform: translateY(200%); opacity: 0; }
  18%  { opacity: 1; }
  82%  { opacity: 1; }
  100% { transform: translateY(-130%); opacity: 0; }
}
@keyframes wfShimDown {
  0%   { transform: translateY(-130%); opacity: 0; }
  18%  { opacity: 1; }
  82%  { opacity: 1; }
  100% { transform: translateY(200%); opacity: 0; }
}

/* ── Bar entry animation ──────────────────────────────── */
@keyframes wfBarIn {
  from { opacity: 0; transform: scaleY(0.18); }
  to   { opacity: 1; transform: scaleY(1); }
}

/* ── Value labels ─────────────────────────────────────── */
.wf-label {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  text-align: center;
  pointer-events: none;
  animation: wfLabelIn 0.35s ease-out both;
}
.wf-label-anchor { color: rgba(118, 104, 94, 0.92); }
.wf-label-increase { color: #b71c1c; }
.wf-label-decrease { color: #1b6e35; }

.wf-arrow {
  font-size: 8px;
  vertical-align: middle;
  margin-right: 1px;
}

@keyframes wfLabelIn {
  from { opacity: 0; transform: translateX(-50%) translateY(6px); }
  to   { opacity: 1; transform: translateX(-50%) translateY(0); }
}

/* ── Zero axis line ───────────────────────────────────── */
.wf-zero-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 1.5px;
  background: rgba(158, 140, 126, 0.42);
  z-index: 2;
  pointer-events: none;
}

/* ── Name row ─────────────────────────────────────────── */
.wf-names {
  height: 48px;
  display: flex;
  align-items: flex-start;
  padding-top: 7px;
  gap: 6px;
  overflow: visible;
}

.wf-name {
  flex: 1;
  min-width: 52px;
  text-align: center;
  font-size: 11px;
  color: var(--muted);
  word-break: break-all;
  line-height: 1.3;
  padding: 0 1px;
}

.wf-name-anchor {
  font-weight: 600;
  color: var(--text);
  opacity: 0.78;
}

/* ── Empty state ──────────────────────────────────────── */
.wf-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--muted);
  font-size: 14px;
}
</style>
