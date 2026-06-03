<script setup>
import { computed } from 'vue'

const props = defineProps({
  waterfall: { type: Array, default: () => [] },
  height: { type: String, default: '380px' },
})

const chartData = computed(() => {
  const rawItems = props.waterfall
  if (!rawItems.length) return null

  // Sort intermediate factor bars: most negative first → most positive last
  const baseItem  = rawItems[0]
  const totalItem = rawItems[rawItems.length - 1]
  const middle    = rawItems.slice(1, -1)
  middle.sort((a, b) => a.value - b.value)
  const items = [baseItem, ...middle, totalItem]

  let running = 0
  const processed = []

  for (const item of items) {
    let lo, hi, after
    if (item.type === 'base') {
      lo = Math.min(0, item.value)
      hi = Math.max(0, item.value)
      running = item.value
      after = running
    } else if (item.type === 'total') {
      lo = Math.min(0, item.value)
      hi = Math.max(0, item.value)
      after = item.value
    } else {
      lo = Math.min(running, running + item.value)
      hi = Math.max(running, running + item.value)
      running += item.value
      after = running
    }
    processed.push({
      ...item,
      lo,
      hi,
      after,
      barType: item.type === 'base' || item.type === 'total'
        ? 'anchor'
        : item.value >= 0 ? 'increase' : 'decrease',
    })
  }

  const factors = processed.filter(b => b.barType !== 'anchor')
  const maxAbsDelta = Math.max(...factors.map(b => Math.abs(b.value)), 1)

  const yMin = Math.min(0, ...processed.map(b => b.lo))
  const yMax = Math.max(0, ...processed.map(b => b.hi))
  const yRange = yMax - yMin || 1
  const pct = v => (v - yMin) / yRange * 100

  const baseBar  = processed[0]
  const totalBar = processed[processed.length - 1]

  return {
    bars: processed.map((b, i) => ({
      ...b,
      bottomPct: pct(b.lo),
      heightPct: Math.max(pct(b.hi) - pct(b.lo), 0.8),
      topPct: pct(b.hi),
      // cap level for anchor T-markers: the actual value position
      capPct: b.barType === 'anchor'
        ? (b.value >= 0 ? pct(b.hi) : pct(b.lo))
        : null,
      connectorPct: i < processed.length - 1 ? pct(b.after) : null,
      intensity: b.barType === 'anchor' ? 1 : Math.max(0.28, Math.abs(b.value) / maxAbsDelta),
    })),
    zeroLinePct: pct(0),
    baseRefPct:   pct(baseBar.value),
    baseRefValue: baseBar.value,
    totalRefPct:   pct(totalBar.value),
    totalRefValue: totalBar.value,
  }
})

function barColorStyle(barType, intensity) {
  if (barType === 'anchor') return {}
  const t = intensity
  const a1 = (0.36 + 0.50 * t).toFixed(2)
  const a2 = (0.40 + 0.52 * t).toFixed(2)
  if (barType === 'increase') {
    return { background: `linear-gradient(175deg, rgba(213,55,55,${a1}) 0%, rgba(168,22,22,${a2}) 100%)` }
  }
  return { background: `linear-gradient(175deg, rgba(32,140,72,${a1}) 0%, rgba(16,100,48,${a2}) 100%)` }
}

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
      <!-- Zero axis line — distinct dark line -->
      <div class="wf-zero-line" :style="`bottom:${chartData.zeroLinePct}%`"></div>

      <!-- Start / end reference lines -->
      <div class="wf-ref wf-ref-base" :style="`bottom:${chartData.baseRefPct}%`">
        <span class="wf-ref-tag">起点 {{ fmtAmt(chartData.baseRefValue) }}</span>
      </div>
      <div class="wf-ref wf-ref-total" :style="`bottom:${chartData.totalRefPct}%`">
        <span class="wf-ref-tag">终点 {{ fmtAmt(chartData.totalRefValue) }}</span>
      </div>

      <!-- Bar columns -->
      <div class="wf-grid">
        <div v-for="(bar, i) in chartData.bars" :key="i" class="wf-col">

          <!-- Staircase connector to the next column -->
          <div v-if="bar.connectorPct != null" class="wf-connector" :style="`bottom:${bar.connectorPct}%`"></div>

          <!-- Anchor bars: T-shaped marker (thin stem + wide cap) -->
          <template v-if="bar.barType === 'anchor'">
            <div
              class="wf-t-stem"
              :style="`bottom:${bar.bottomPct}%;height:${bar.heightPct}%;animation-delay:${i*0.07}s`"
            ></div>
            <div
              class="wf-t-cap"
              :style="`bottom:calc(${bar.capPct}% - 3px);animation-delay:${i*0.07}s`"
            ></div>
          </template>

          <!-- Factor bars -->
          <div
            v-else
            class="wf-bar"
            :class="`wf-bar-${bar.barType}`"
            :style="[
              {
                bottom: `${bar.bottomPct}%`,
                height: `${bar.heightPct}%`,
                animationDelay: `${i * 0.07}s`,
              },
              barColorStyle(bar.barType, bar.intensity),
            ]"
          >
            <div class="wf-bar-inner">
              <div class="wf-shim"></div>
            </div>
          </div>

          <!-- Value label — factor bars only; anchors show their value in the
               reference-line tag, so a separate label here would overlap it -->
          <div
            v-if="bar.barType !== 'anchor'"
            class="wf-label"
            :class="`wf-label-${bar.barType}`"
            :style="`bottom:calc(${bar.topPct}% + 10px);animation-delay:${i * 0.07 + 0.2}s`"
          >
            <svg v-if="bar.barType === 'increase'" class="wf-arr" viewBox="0 0 7 10" fill="none" width="7" height="10">
              <path d="M3.5 9V2.5M1 5L3.5 2.5L6 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <svg v-else-if="bar.barType === 'decrease'" class="wf-arr" viewBox="0 0 7 10" fill="none" width="7" height="10">
              <path d="M3.5 1V7.5M1 5L3.5 7.5L6 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            {{ fmtAmt(bar.value) }}
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

/* ── Chart zone ───────────────────────────────────────── */
.wf-chart {
  flex: 1;
  position: relative;
  margin-top: 32px;
  overflow: visible;
  min-height: 120px;
}

/* Grid of columns */
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

/* ── Increase bar (A股红) ─────────────────────────────── */
.wf-bar-increase {
  background: linear-gradient(175deg, rgba(213,55,55,0.86) 0%, rgba(168,22,22,0.92) 100%);
  border: 1px solid rgba(255,135,135,0.28);
  box-shadow:
    0 6px 20px rgba(195,35,35,0.44),
    inset 0 1px 0 rgba(255,195,195,0.52),
    0 0 18px rgba(195,35,35,0.22),
    0 0 0 1px rgba(210,55,55,0.28);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* ── Decrease bar (A股绿) ─────────────────────────────── */
.wf-bar-decrease {
  background: linear-gradient(175deg, rgba(32,140,72,0.86) 0%, rgba(16,100,48,0.92) 100%);
  border: 1px solid rgba(90,225,140,0.26);
  box-shadow:
    0 6px 20px rgba(25,135,65,0.44),
    inset 0 1px 0 rgba(110,245,165,0.48),
    0 0 18px rgba(25,135,65,0.22),
    0 0 0 1px rgba(40,162,85,0.28);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* ── Shimmer overlay (装饰性微光，已禁用以省性能) ──────────── */
.wf-shim { display: none; }

/* ── T-shaped anchor marker ───────────────────────────── */
.wf-t-stem {
  position: absolute;
  left: 50%;
  width: 3px;
  margin-left: -1.5px;
  background: rgba(118,104,94,0.72);
  border-radius: 2px;
  transform-origin: bottom center;
  animation: wfBarIn 0.45s ease-out both;
}

.wf-t-cap {
  position: absolute;
  left: 4%;
  right: 4%;
  height: 6px;
  background: rgba(100,88,78,0.9);
  border-radius: 4px;
  transform-origin: center;
  animation: wfCapIn 0.45s ease-out both;
}

@keyframes wfCapIn {
  from { opacity: 0; transform: scaleX(0.25); }
  to   { opacity: 1; transform: scaleX(1); }
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
  pointer-events: none;
  animation: wfLabelIn 0.35s ease-out both;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
}
.wf-label-anchor   { color: rgba(80,68,58,0.9); }
.wf-label-increase { color: #b71c1c; }
.wf-label-decrease { color: #1b6e35; }

.wf-arr { flex-shrink: 0; display: block; }

@keyframes wfLabelIn {
  from { opacity: 0; transform: translateX(-50%) translateY(6px); }
  to   { opacity: 1; transform: translateX(-50%) translateY(0); }
}

/* ── Zero axis line — bold and distinct from connectors ── */
.wf-zero-line {
  position: absolute;
  left: 0; right: 0;
  height: 2px;
  background: rgba(55,48,42,0.62);
  z-index: 2;
  pointer-events: none;
}

/* ── Start / end reference lines ──────────────────────── */
.wf-ref {
  position: absolute;
  left: 0; right: 0;
  height: 0;
  border-top: 1.5px dashed;
  z-index: 4;
  pointer-events: none;
}
.wf-ref-base  { border-color: rgba(96,125,170,0.6); }
.wf-ref-total { border-color: rgba(176,98,98,0.62); }
.wf-ref-tag {
  position: absolute;
  left: 2px;
  bottom: 2px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  padding: 1px 6px;
  border-radius: 5px;
  white-space: nowrap;
  background: rgba(255,255,255,0.85);
  -webkit-backdrop-filter: blur(2px);
  backdrop-filter: blur(2px);
}
.wf-ref-base  .wf-ref-tag { color: #3f5a86; }
.wf-ref-total .wf-ref-tag { color: #9c4242; }

/* ── Staircase connectors (behind bars, span into next col) ── */
.wf-connector {
  position: absolute;
  left: 88%;
  width: calc(24% + 6px);
  height: 0;
  border-top: 1px solid rgba(150,140,130,0.5);
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
