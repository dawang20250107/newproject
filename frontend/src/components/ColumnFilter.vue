<script setup>
/* Excel 风格列头筛选 + 排序的弹出控件，复用于审批管理 / 付款台账。
   - type=text   → 包含 / 等于
   - type=number → = > < ≥ ≤ 区间
   - type=date   → 起止范围组（任一侧可空）
   - type=enum   → 多选（任一命中）
   modelValue 形如 {op, value}（value 可为字符串或二元数组），无筛选时为 null。
   排序通过 sort 事件上抛 'asc' | 'desc' | ''（清除）。 */
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  label:    { type: String,  required: true },
  field:    { type: String,  required: true },
  type:     { type: String,  default: 'text' },     // text | number | date | enum
  modelValue: { type: Object, default: null },       // {op, value} | null
  options:  { type: Array,   default: () => [] },     // enum: [{value,label}] 或 [string]
  single:   { type: Boolean, default: false },        // enum 单选（用于计算型状态等）
  datePresets: { type: Boolean, default: true },      // date 类型是否显示快捷区间
  sortable: { type: Boolean, default: true },
  filterable: { type: Boolean, default: true },   // false → 仅排序（计算/聚合列）
  sortField:{ type: String,  default: '' },           // 当前生效的排序字段
  sortOrder:{ type: String,  default: '' },           // 'asc' | 'desc' | ''
})
const emit = defineEmits(['update:modelValue', 'sort'])

const open = ref(false)
const pos = ref({ top: 0, left: 0 })
const btnRef = ref(null)

// 弹层内的草稿态
const op = ref('contains')
const v1 = ref('')
const v2 = ref('')
const enumSel = ref([])

const NUM_OPS = [
  { v: 'eq', t: '=' }, { v: 'gt', t: '>' }, { v: 'lt', t: '<' },
  { v: 'gte', t: '≥' }, { v: 'lte', t: '≤' }, { v: 'between', t: '区间' },
]

const active = computed(() => {
  const m = props.modelValue
  if (!m || !m.op) return false
  const val = m.value
  if (Array.isArray(val)) return val.some(x => x !== '' && x != null)
  return val !== '' && val != null
})
const sorted = computed(() => props.sortable && props.sortField === props.field && props.sortOrder)

const enumOpts = computed(() =>
  props.options.map(o => (typeof o === 'string' ? { value: o, label: o } : o)))

function syncDraftFromModel() {
  const m = props.modelValue
  if (props.type === 'enum') {
    enumSel.value = m && Array.isArray(m.value) ? [...m.value] : []
    return
  }
  if (props.type === 'date') {
    op.value = 'between'
    v1.value = m && Array.isArray(m.value) ? (m.value[0] || '') : ''
    v2.value = m && Array.isArray(m.value) ? (m.value[1] || '') : ''
    return
  }
  if (props.type === 'number') {
    op.value = m?.op || 'eq'
    if (op.value === 'between') {
      v1.value = m && Array.isArray(m.value) ? (m.value[0] || '') : ''
      v2.value = m && Array.isArray(m.value) ? (m.value[1] || '') : ''
    } else {
      v1.value = m && !Array.isArray(m.value) ? (m.value ?? '') : ''
      v2.value = ''
    }
    return
  }
  // text
  op.value = m?.op || 'contains'
  v1.value = m && !Array.isArray(m.value) ? (m.value ?? '') : ''
}

async function toggle() {
  if (open.value) { open.value = false; return }
  syncDraftFromModel()
  const r = btnRef.value.getBoundingClientRect()
  const estimatedH = 280
  let top = r.bottom + 6
  if (top + estimatedH > window.innerHeight - 12) {
    top = r.top - estimatedH - 6
    if (top < 8) top = 8
  }
  let left = r.right - 240
  if (left < 8) left = 8
  pos.value = { top, left }
  open.value = true
  await nextTick()
  if (props.type === 'enum') {
    const first = document.querySelector('.colf-pop input[type="checkbox"]')
    first && first.focus()
  } else {
    const el = document.querySelector('.colf-pop input, .colf-pop select')
    el && el.focus()
  }
}

function apply() {
  let payload = null
  if (props.type === 'enum') {
    payload = enumSel.value.length ? { op: 'in', value: [...enumSel.value] } : null
  } else if (props.type === 'date') {
    payload = (v1.value || v2.value) ? { op: 'between', value: [v1.value, v2.value] } : null
  } else if (props.type === 'number') {
    if (op.value === 'between') {
      payload = (v1.value !== '' || v2.value !== '') ? { op: 'between', value: [v1.value, v2.value] } : null
    } else {
      payload = v1.value !== '' ? { op: op.value, value: v1.value } : null
    }
  } else {
    payload = v1.value !== '' ? { op: op.value, value: v1.value } : null
  }
  emit('update:modelValue', payload)
  open.value = false
}

function clear() {
  emit('update:modelValue', null)
  open.value = false
}

function toggleEnum(val) {
  if (props.single) {
    enumSel.value = enumSel.value.includes(val) ? [] : [val]
    return
  }
  const i = enumSel.value.indexOf(val)
  if (i >= 0) enumSel.value.splice(i, 1)
  else enumSel.value.push(val)
}

// 日期快捷区间（组件内自算，不依赖业务页面）
const DATE_PRESETS = [
  { k: 'this_month', t: '本月' }, { k: 'last_month', t: '上月' },
  { k: 'this_quarter', t: '本季' }, { k: 'this_year', t: '本年' },
  { k: 'last30', t: '近30天' }, { k: 'last90', t: '近90天' },
]
function _iso(d) { return d.toISOString().slice(0, 10) }
function presetRange(k) {
  const now = new Date(); const y = now.getFullYear(); const m = now.getMonth()
  if (k === 'this_month') return [_iso(new Date(y, m, 1)), _iso(new Date(y, m + 1, 0))]
  if (k === 'last_month') return [_iso(new Date(y, m - 1, 1)), _iso(new Date(y, m, 0))]
  if (k === 'this_quarter') { const q = Math.floor(m / 3); return [_iso(new Date(y, q * 3, 1)), _iso(new Date(y, q * 3 + 3, 0))] }
  if (k === 'this_year') return [_iso(new Date(y, 0, 1)), _iso(new Date(y, 11, 31))]
  if (k === 'last30') { const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 29); return [_iso(s), _iso(e)] }
  if (k === 'last90') { const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 89); return [_iso(s), _iso(e)] }
  return ['', '']
}
function applyPreset(k) { const [s, e] = presetRange(k); v1.value = s; v2.value = e; apply() }

function setSort(order) {
  // 再次点击同方向 = 取消排序
  emit('sort', props.sortOrder === order && props.sortField === props.field ? '' : order)
  open.value = false
}

function onDocClick(e) {
  if (!open.value) return
  if (e.target.closest('.colf-pop') || e.target.closest(`[data-colf="${props.field}"]`)) return
  open.value = false
}
function onKey(e) { if (e.key === 'Escape') open.value = false }
watch(open, (o) => {
  if (o) { document.addEventListener('mousedown', onDocClick); document.addEventListener('keydown', onKey) }
  else { document.removeEventListener('mousedown', onDocClick); document.removeEventListener('keydown', onKey) }
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocClick); document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <span class="colf">
    <span class="colf-label">{{ label }}</span>
    <button ref="btnRef" :data-colf="field" class="colf-btn" :class="{ on: active || sorted }"
            type="button" @click.stop="toggle" :title="active ? '已筛选' : '筛选 / 排序'">
      <span class="colf-funnel">⏷</span>
      <span v-if="sorted" class="colf-sortmark">{{ sortOrder === 'asc' ? '▲' : '▼' }}</span>
    </button>

    <Teleport to="body">
      <div v-if="open" class="colf-pop" :style="{ top: pos.top + 'px', left: pos.left + 'px' }">
        <div v-if="sortable" class="colf-sort" :class="{ 'colf-sort-only': !filterable }">
          <button type="button" :class="{ act: sortField === field && sortOrder === 'asc' }" @click="setSort('asc')">▲ 升序</button>
          <button type="button" :class="{ act: sortField === field && sortOrder === 'desc' }" @click="setSort('desc')">▼ 降序</button>
          <button v-if="!filterable" type="button" class="colf-close" @click="open = false">✕</button>
        </div>

        <template v-if="filterable">
        <!-- 文本 -->
        <template v-if="type === 'text'">
          <select v-model="op" class="colf-op">
            <option value="contains">包含</option>
            <option value="eq">等于</option>
          </select>
          <input v-model="v1" class="colf-in" placeholder="输入关键字" @keyup.enter="apply" />
        </template>

        <!-- 数字 -->
        <template v-else-if="type === 'number'">
          <div class="colf-ops">
            <button v-for="o in NUM_OPS" :key="o.v" type="button"
                    :class="{ act: op === o.v }" @click="op = o.v">{{ o.t }}</button>
          </div>
          <template v-if="op === 'between'">
            <div class="colf-range">
              <input v-model="v1" class="colf-in" type="number" placeholder="最小" @keyup.enter="apply" />
              <span class="colf-tilde">~</span>
              <input v-model="v2" class="colf-in" type="number" placeholder="最大" @keyup.enter="apply" />
            </div>
          </template>
          <input v-else v-model="v1" class="colf-in" type="number" placeholder="数值" @keyup.enter="apply" />
        </template>

        <!-- 日期范围 -->
        <template v-else-if="type === 'date'">
          <div v-if="datePresets" class="colf-chips">
            <button v-for="p in DATE_PRESETS" :key="p.k" type="button" @click="applyPreset(p.k)">{{ p.t }}</button>
          </div>
          <div class="colf-range colf-range-date">
            <input v-model="v1" class="colf-in" type="date" @keyup.enter="apply" />
            <span class="colf-tilde">~</span>
            <input v-model="v2" class="colf-in" type="date" @keyup.enter="apply" />
          </div>
        </template>

        <!-- 枚举多选 -->
        <template v-else-if="type === 'enum'">
          <div class="colf-enum">
            <label v-for="o in enumOpts" :key="o.value" class="colf-chk">
              <input type="checkbox" :checked="enumSel.includes(o.value)" @change="toggleEnum(o.value)" />
              <span>{{ o.label }}</span>
            </label>
          </div>
        </template>

        <div class="colf-foot">
          <button type="button" class="colf-clear" @click="clear">清除</button>
          <button type="button" class="colf-apply" @click="apply">应用</button>
        </div>
        </template>
      </div>
    </Teleport>
  </span>
</template>

<style scoped>
.colf { display: inline-flex; align-items: center; gap: 3px; }
.colf-label { white-space: nowrap; }
.colf-btn {
  display: inline-flex; align-items: center; gap: 1px;
  border: none; background: transparent; cursor: pointer;
  color: var(--muted); font-size: 9px; padding: 1px 2px; border-radius: 4px;
  line-height: 1; opacity: 0.55;
}
.colf-btn:hover { opacity: 1; background: rgba(201,99,66,0.1); }
.colf-btn.on { color: var(--primary); opacity: 1; }
.colf-funnel { font-size: 9px; }
.colf-sortmark { font-size: 8px; }

.colf-pop {
  position: fixed; z-index: 4000; width: 240px;
  background: #fffdfa; border: 1px solid #d9ccbd;
  border-radius: 8px; box-shadow: 0 8px 26px rgba(80,50,25,0.22);
  padding: 10px; display: flex; flex-direction: column; gap: 8px;
  font-size: 12px; color: var(--text);
  -webkit-backdrop-filter: none; backdrop-filter: none;
  max-height: 80vh; overflow-y: auto;
}
.colf-sort { display: flex; gap: 6px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.colf-sort.colf-sort-only { border-bottom: none; padding-bottom: 0; }
.colf-sort button {
  flex: 1; padding: 5px 0; border: 1px solid var(--border); border-radius: 6px;
  background: transparent; cursor: pointer; color: var(--muted); font-size: 11.5px;
}
.colf-sort button.act { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.08); }
.colf-close {
  flex: 0 0 auto; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: transparent; cursor: pointer; color: var(--muted); font-size: 10px; line-height: 1;
}
.colf-close:hover { border-color: var(--danger); color: var(--danger); }

.colf-op, .colf-in {
  width: 100%; box-sizing: border-box; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: 6px; font-size: 12px;
  background: #fff; color: var(--text);
}
.colf-ops { display: flex; flex-wrap: wrap; gap: 4px; }
.colf-ops button {
  min-width: 30px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px;
  background: transparent; cursor: pointer; color: var(--muted); font-size: 12px;
}
.colf-ops button.act { border-color: var(--primary); color: #fff; background: var(--primary); }
.colf-range { display: flex; align-items: center; gap: 6px; }
.colf-range .colf-in { width: auto; flex: 1; min-width: 0; }
.colf-range-date { flex-direction: column; align-items: stretch; }
.colf-range-date .colf-tilde { text-align: center; }
.colf-tilde { color: var(--muted); }

.colf-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.colf-chips button {
  padding: 3px 8px; border: 1px solid var(--border); border-radius: 12px;
  background: transparent; cursor: pointer; color: var(--muted); font-size: 11px;
}
.colf-chips button:hover { border-color: var(--primary); color: var(--primary); }
.colf-enum { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.colf-chk { display: flex; align-items: center; gap: 7px; padding: 4px 4px; border-radius: 5px; cursor: pointer; }
.colf-chk:hover { background: rgba(201,99,66,0.06); }
.colf-chk input { margin: 0; }

.colf-foot { display: flex; gap: 6px; padding-top: 6px; border-top: 1px solid var(--border); }
.colf-clear, .colf-apply { flex: 1; padding: 6px 0; border-radius: 6px; cursor: pointer; font-size: 12px; }
.colf-clear { border: 1px solid var(--border); background: transparent; color: var(--muted); }
.colf-apply { border: 1px solid var(--primary); background: var(--primary); color: #fff; }
</style>
