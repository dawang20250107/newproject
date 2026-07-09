<script setup>
// 统一时间区间预设条:预设 pchip + 自定义起止 + 清除。
// 与 日常收款/预收预付 同款交互;新页面接入只需 v-model:start / v-model:end + @change。
import { ref, watch, computed } from 'vue'

const props = defineProps({
  start: { type: String, default: '' },
  end: { type: String, default: '' },
  // 预设键集合(按需裁剪);默认含「全部」
  presets: {
    type: Array,
    default: () => ['all', 'thismonth', 'lastmonth', 'thisquarter', 'lastquarter',
                    'halfyear', 'thisyear', 'lastyear', 'year1', 'd30', 'd90'],
  },
  label: { type: String, default: '时间' },
  // 初始高亮的预设键(父组件用对应区间初始化时传入,如 'thismonth')
  initial: { type: String, default: 'all' },
})
const emit = defineEmits(['update:start', 'update:end', 'change'])

const LABELS = {
  all: '全部', today: '今天', thisweek: '本周', thismonth: '本月', lastmonth: '上月',
  thisquarter: '本季度', lastquarter: '上季度', halfyear: '近半年', thisyear: '本年',
  lastyear: '去年', year1: '近一年', d7: '近7天', d30: '近30天', d90: '近90天',
}
const chips = computed(() => props.presets.map(k => ({ k, l: LABELS[k] || k })))

function _ymd(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
function _compute(k) {
  const t = new Date(), y = t.getFullYear(), m = t.getMonth(), d = t.getDate(), day = t.getDay()
  const back = n => { const x = new Date(t); x.setDate(d - n); return x }
  const mk = (a, b) => ({ start: _ymd(a), end: _ymd(b) })
  switch (k) {
    case 'all': return { start: '', end: '' }
    case 'today': return mk(t, t)
    case 'thisweek': { const mo = new Date(t); mo.setDate(d - (day === 0 ? 6 : day - 1)); return mk(mo, t) }
    case 'thismonth': return mk(new Date(y, m, 1), t)
    case 'lastmonth': return mk(new Date(y, m - 1, 1), new Date(y, m, 0))
    case 'thisquarter': return mk(new Date(y, Math.floor(m / 3) * 3, 1), t)
    case 'lastquarter': { const qm = Math.floor(m / 3) * 3 - 3; return mk(new Date(y, qm, 1), new Date(y, qm + 3, 0)) }
    case 'halfyear': return mk(back(182), t)
    case 'thisyear': return mk(new Date(y, 0, 1), t)
    case 'lastyear': return mk(new Date(y - 1, 0, 1), new Date(y - 1, 11, 31))
    case 'year1': return mk(back(365), t)
    case 'd7': return mk(back(6), t)
    case 'd30': return mk(back(29), t)
    case 'd90': return mk(back(89), t)
  }
  return { start: '', end: '' }
}

const active = ref(props.initial)
let applying = false
function apply(k) {
  applying = true
  const r = _compute(k)
  emit('update:start', r.start)
  emit('update:end', r.end)
  active.value = k
  applying = false
  emit('change')
}
function onManual(field, v) {
  emit(field === 'start' ? 'update:start' : 'update:end', v)
  emit('change')
}
watch(() => [props.start, props.end], () => { if (!applying) active.value = '' })
</script>

<template>
  <div class="drc">
    <span class="drc-lbl">{{ label }}</span>
    <div class="drc-chips">
      <button v-for="c in chips" :key="c.k" class="drc-chip" :class="{ on: active === c.k }"
              @click="apply(c.k)">{{ c.l }}</button>
    </div>
    <div class="drc-range">
      <input :value="start" type="date" class="inp sm drc-date" @change="onManual('start', $event.target.value)" />
      <span class="drc-sep">~</span>
      <input :value="end" type="date" class="inp sm drc-date" @change="onManual('end', $event.target.value)" />
      <button v-if="start || end" class="btn btn-ghost btn-sm" @click="apply('all')">清除</button>
    </div>
  </div>
</template>

<style scoped>
.drc { display: flex; align-items: center; gap: 10px; flex-wrap: nowrap; min-width: 0; }
.drc-lbl { font-size: 12px; font-weight: 700; color: var(--muted); white-space: nowrap; flex-shrink: 0; }
.drc-chips { display: flex; gap: 5px; overflow-x: auto; scrollbar-width: none; min-width: 0; }
.drc-chips::-webkit-scrollbar { display: none; }
.drc-chip { padding: 3px 11px; border-radius: 999px; border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 12px; cursor: pointer; white-space: nowrap; transition: all .15s; flex-shrink: 0; }
.drc-chip:hover { border-color: var(--primary); color: var(--primary); }
.drc-chip.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.drc-range { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: auto; }
.drc-date { width: 132px; }
.drc-sep { color: var(--muted); font-size: 12px; }
</style>
