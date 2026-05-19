<template>
  <div class="kpi-card" :class="`kpi-card--${color}`">
    <!-- Top gradient bar -->
    <div class="kpi-top-bar"></div>

    <div class="kpi-top">
      <div class="kpi-icon-wrap">
        <span v-html="icon" class="kpi-icon"></span>
      </div>
      <div class="kpi-trend" :class="trendClass">
        <svg v-if="trend > 0" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="18,15 12,9 6,15"/></svg>
        <svg v-else-if="trend < 0" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6,9 12,15 18,9"/></svg>
        {{ Math.abs(trend) }}%
      </div>
    </div>

    <div class="kpi-value" ref="valueEl">{{ displayValue }}</div>
    <div class="kpi-label">{{ label }}</div>
    <div class="kpi-sub" v-if="sub">{{ sub }}</div>

    <!-- Decorative radial glow -->
    <div class="kpi-radial"></div>
    <!-- Subtle grid pattern -->
    <div class="kpi-grid-pattern"></div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'

const props = defineProps({
  value:   { type: [Number, String], default: 0 },
  label:   { type: String, required: true },
  sub:     { type: String, default: '' },
  prefix:  { type: String, default: '¥' },
  color:   { type: String, default: 'blue' },
  trend:   { type: Number, default: 0 },
  icon:    { type: String, default: '' },
  animate: { type: Boolean, default: true },
})

const displayValue = ref(props.animate ? '—' : formatNum(props.value))
const valueEl = ref(null)

function formatNum(v) {
  if (typeof v === 'string') return v
  const n = Number(v) || 0
  if (n >= 10000) return props.prefix + (n / 10000).toFixed(2) + '万'
  return props.prefix + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const trendClass = computed(() => {
  if (props.trend > 0) return 'up'
  if (props.trend < 0) return 'down'
  return 'neutral'
})

onMounted(() => {
  if (!props.animate) { displayValue.value = formatNum(props.value); return }
  const target = Number(props.value) || 0
  const duration = 1400
  const start = performance.now()
  const ease = t => 1 - Math.pow(1 - t, 3)
  function step(now) {
    const progress = Math.min((now - start) / duration, 1)
    const current = target * ease(progress)
    displayValue.value = formatNum(current)
    if (progress < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
})

watch(() => props.value, v => {
  displayValue.value = formatNum(v)
})
</script>

<style scoped>
.kpi-card {
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: 22px 24px 20px;
  box-shadow: var(--shadow-card);
  border: 1px solid rgba(0,0,0,0.05);
  position: relative;
  overflow: hidden;
  transition: box-shadow var(--transition-normal), transform var(--transition-normal);
}
.kpi-card:hover {
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-3px);
}

/* Colored top gradient bar */
.kpi-top-bar {
  position: absolute; top: 0; left: 0; right: 0;
  height: 3px; border-radius: var(--radius-xl) var(--radius-xl) 0 0;
}
.kpi-card--blue   .kpi-top-bar { background: linear-gradient(90deg, #fff3b0, #f5d36c, #d4af37); }
.kpi-card--green  .kpi-top-bar { background: linear-gradient(90deg, #6ee7b7, #10b981, #059669); }
.kpi-card--orange .kpi-top-bar { background: linear-gradient(90deg, #fcd34d, #f59e0b, #d97706); }
.kpi-card--red    .kpi-top-bar { background: linear-gradient(90deg, #fca5a5, #ef4444, #dc2626); }
.kpi-card--purple .kpi-top-bar { background: linear-gradient(90deg, #c4b5fd, #8b5cf6, #7c3aed); }

.kpi-top {
  display: flex; align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}
.kpi-icon-wrap {
  width: 46px; height: 46px;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
}
.kpi-card--blue   .kpi-icon-wrap { background: rgba(212,175,55,0.1); color: #d4af37; }
.kpi-card--green  .kpi-icon-wrap { background: rgba(16,185,129,0.1); color: #10b981; }
.kpi-card--orange .kpi-icon-wrap { background: rgba(245,158,11,0.1); color: #f59e0b; }
.kpi-card--red    .kpi-icon-wrap { background: rgba(239,68,68,0.1); color: #ef4444; }
.kpi-card--purple .kpi-icon-wrap { background: rgba(139,92,246,0.1); color: #8b5cf6; }

.kpi-icon { display: flex; }
.kpi-trend {
  font-size: 12px; font-weight: 600;
  padding: 4px 9px; border-radius: 100px;
  display: flex; align-items: center; gap: 3px;
}
.kpi-trend.up      { background: var(--badge-success-bg); color: var(--badge-success-text); }
.kpi-trend.down    { background: var(--badge-danger-bg);  color: var(--badge-danger-text); }
.kpi-trend.neutral { background: var(--badge-neutral-bg); color: var(--badge-neutral-text); }

.kpi-value {
  font-size: 30px; font-weight: 800;
  color: var(--text-primary);
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  margin-bottom: 6px;
}
.kpi-label {
  font-size: 13px; font-weight: 500;
  color: var(--text-secondary);
}
.kpi-sub {
  font-size: 11px; color: var(--text-muted);
  margin-top: 3px;
}

/* Decorative radial glow */
.kpi-radial {
  position: absolute;
  right: -24px; bottom: -24px;
  width: 120px; height: 120px;
  border-radius: 50%;
  opacity: 0.06;
  pointer-events: none;
  transition: opacity var(--transition-normal);
}
.kpi-card:hover .kpi-radial { opacity: 0.1; }
.kpi-card--blue   .kpi-radial { background: radial-gradient(circle, #d4af37, transparent 70%); }
.kpi-card--green  .kpi-radial { background: radial-gradient(circle, #10b981, transparent 70%); }
.kpi-card--orange .kpi-radial { background: radial-gradient(circle, #f59e0b, transparent 70%); }
.kpi-card--red    .kpi-radial { background: radial-gradient(circle, #ef4444, transparent 70%); }
.kpi-card--purple .kpi-radial { background: radial-gradient(circle, #8b5cf6, transparent 70%); }

/* Subtle dot grid pattern */
.kpi-grid-pattern {
  position: absolute; inset: 0;
  background-image: radial-gradient(circle, rgba(0,0,0,0.06) 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.4;
  pointer-events: none;
  border-radius: var(--radius-xl);
}
</style>
