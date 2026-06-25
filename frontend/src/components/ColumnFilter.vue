<script setup>
/* Excel / 金蝶风格列头筛选 + 排序的弹出控件，复用于审批管理 / 付款台账 / 应收明细。
   - type=text   → 条件模式（包含/不包含/等于/不等于/开头/结尾/为空/不为空）
                   + 选值模式（勾选该列实际出现的值；需父级提供 valuesProvider）
   - type=number → = ≠ > < ≥ ≤ 区间 / 空 / 非空
   - type=date   → 起止范围组（任一侧可空）+ 为空/不为空
   - type=enum   → 多选（在/不在）
   modelValue 形如 {op, value}（value 可为字符串或数组），无筛选时为 null。
   一元运算符（为空/不为空）不带 value，但仍算「已筛选」。
   排序通过 sort 事件上抛 'asc' | 'desc' | ''（清除）。 */
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  label:    { type: String,  required: true },
  field:    { type: String,  required: true },
  type:     { type: String,  default: 'text' },     // text | number | date | enum
  modelValue: { type: Object, default: null },       // {op, value} | null
  options:  { type: Array,   default: () => [] },     // enum: [{value,label}] 或 [string]
  single:   { type: Boolean, default: false },        // enum 单选（用于计算型状态等）
  noExclude:{ type: Boolean, default: false },        // enum 多选但隐藏「包含/排除」（派生状态桶只支持并集）
  datePresets: { type: Boolean, default: true },      // date 类型是否显示快捷区间
  sortable: { type: Boolean, default: true },
  filterable: { type: Boolean, default: true },   // false → 仅排序（计算/聚合列）
  sortField:{ type: String,  default: '' },           // 当前生效的排序字段
  sortOrder:{ type: String,  default: '' },           // 'asc' | 'desc' | ''
  // 选值清单数据源：(field) => Promise<{values:string[], truncated:bool}>。
  // 仅 text 列提供时启用「选值」模式（Excel 自动筛选）。
  valuesProvider: { type: Function, default: null },
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

// 文本「选值」模式（Excel 自动筛选）
const hasValuePicker = computed(() => props.type === 'text' && !!props.valuesProvider)
const mode = ref('values')            // 'values' | 'cond'（仅 text 且有 valuesProvider 时切换）
const valList = ref([])
const valSel = ref([])
const valSearch = ref('')
const valLoading = ref(false)
const valTruncated = ref(false)
const valShown = computed(() => {
  const kw = valSearch.value.trim().toLowerCase()
  return kw ? valList.value.filter(v => v.toLowerCase().includes(kw)) : valList.value
})
const valAllChecked = computed(() =>
  valShown.value.length > 0 && valShown.value.every(v => valSel.value.includes(v)))

const TEXT_OPS = [
  { v: 'contains', t: '包含' }, { v: 'not_contains', t: '不包含' },
  { v: 'eq', t: '等于' }, { v: 'ne', t: '不等于' },
  { v: 'startswith', t: '开头是' }, { v: 'endswith', t: '结尾是' },
  { v: 'empty', t: '为空' }, { v: 'not_empty', t: '不为空' },
]
const NUM_OPS = [
  { v: 'eq', t: '=' }, { v: 'ne', t: '≠' }, { v: 'gt', t: '>' }, { v: 'lt', t: '<' },
  { v: 'gte', t: '≥' }, { v: 'lte', t: '≤' }, { v: 'between', t: '区间' },
  { v: 'empty', t: '空' }, { v: 'not_empty', t: '非空' },
]
const NULLARY = ['empty', 'not_empty']    // 不需要 value 的一元运算符
const needsValue = computed(() => !NULLARY.includes(op.value))

const active = computed(() => {
  const m = props.modelValue
  if (!m || !m.op) return false
  if (NULLARY.includes(m.op)) return true       // 为空/不为空 即已筛选
  const val = m.value
  if (Array.isArray(val)) return val.some(x => x !== '' && x != null)
  return val !== '' && val != null
})
const sorted = computed(() => props.sortable && props.sortField === props.field && props.sortOrder)

// 归一化枚举选项：兼容 'string' / {value,label} / {v,l} 三种来源；label 缺失时回退到
// value，确保不会渲染出「没有名称的勾选框」。非数组来源一律视作空集。
const enumOpts = computed(() => {
  const src = Array.isArray(props.options) ? props.options : []
  return src.map(o => {
    if (typeof o === 'string' || typeof o === 'number') return { value: o, label: String(o) }
    if (o == null) return { value: '', label: '' }
    const value = o.value !== undefined ? o.value : o.v
    const label = o.label !== undefined ? o.label : (o.l !== undefined ? o.l : value)
    return { value, label: label == null ? '' : String(label) }
  })
})

function syncDraftFromModel() {
  const m = props.modelValue
  if (props.type === 'enum') {
    op.value = m?.op === 'not_in' ? 'not_in' : 'in'
    enumSel.value = m && Array.isArray(m.value) ? [...m.value] : []
    return
  }
  if (props.type === 'date') {
    if (NULLARY.includes(m?.op)) { op.value = m.op; v1.value = ''; v2.value = ''; return }
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
  if (hasValuePicker.value && (!m || m.op === 'in' || m.op === 'not_in')) {
    mode.value = 'values'
    valSel.value = m && Array.isArray(m.value) ? [...m.value] : []
    loadValues()
  } else {
    mode.value = hasValuePicker.value ? 'cond' : 'values'
    op.value = m?.op || 'contains'
    v1.value = m && !Array.isArray(m.value) ? (m.value ?? '') : ''
  }
}

async function loadValues() {
  if (!props.valuesProvider) return
  valLoading.value = true
  try {
    const res = await props.valuesProvider(props.field)
    valList.value = res?.values || []
    valTruncated.value = !!res?.truncated
  } catch { valList.value = []; valTruncated.value = false }
  finally { valLoading.value = false }
}

async function toggle() {
  if (open.value) { open.value = false; return }
  syncDraftFromModel()
  const r = btnRef.value.getBoundingClientRect()
  const estimatedH = 300
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
  } else if (!(props.type === 'text' && mode.value === 'values')) {
    const el = document.querySelector('.colf-pop input, .colf-pop select')
    el && el.focus()
  }
}

function apply() {
  let payload = null
  if (props.type === 'enum') {
    payload = enumSel.value.length ? { op: op.value === 'not_in' ? 'not_in' : 'in', value: [...enumSel.value] } : null
  } else if (props.type === 'text' && hasValuePicker.value && mode.value === 'values') {
    payload = valSel.value.length ? { op: 'in', value: [...valSel.value] } : null
  } else if (NULLARY.includes(op.value)) {
    payload = { op: op.value, value: '' }
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
  valSel.value = []
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

function toggleVal(val) {
  const i = valSel.value.indexOf(val)
  if (i >= 0) valSel.value.splice(i, 1)
  else valSel.value.push(val)
}
function toggleValAll() {
  if (valAllChecked.value) {
    const shown = new Set(valShown.value)
    valSel.value = valSel.value.filter(v => !shown.has(v))
  } else {
    const set = new Set(valSel.value)
    valShown.value.forEach(v => set.add(v))
    valSel.value = [...set]
  }
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
function applyPreset(k) { const [s, e] = presetRange(k); op.value = 'between'; v1.value = s; v2.value = e; apply() }

function setSort(order) {
  // 再次点击同方向 = 取消排序
  emit('sort', props.sortOrder === order && props.sortField === props.field ? '' : order)
  open.value = false
}
function switchMode(m) {
  mode.value = m
  if (m === 'values' && !valList.value.length) loadValues()
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
    <button v-if="sortable || filterable" ref="btnRef" :data-colf="field" class="colf-btn" :class="{ on: active || sorted }"
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
        <!-- 文本：选值 / 条件 模式切换（仅在提供 valuesProvider 时显示切换条）-->
        <template v-if="type === 'text'">
          <div v-if="hasValuePicker" class="colf-modetab">
            <button type="button" :class="{ act: mode === 'values' }" @click="switchMode('values')">选值</button>
            <button type="button" :class="{ act: mode === 'cond' }" @click="switchMode('cond')">条件</button>
          </div>

          <!-- 选值模式：Excel 自动筛选 -->
          <template v-if="hasValuePicker && mode === 'values'">
            <input v-model="valSearch" class="colf-in" placeholder="搜索值…" />
            <div v-if="valLoading" class="colf-vmsg">加载中…</div>
            <template v-else>
              <label v-if="valShown.length" class="colf-chk colf-chk-all">
                <input type="checkbox" :checked="valAllChecked" @change="toggleValAll" />
                <span>全选（{{ valSel.length }}/{{ valList.length }}）</span>
              </label>
              <div class="colf-enum">
                <label v-for="val in valShown" :key="val" class="colf-chk">
                  <input type="checkbox" :checked="valSel.includes(val)" @change="toggleVal(val)" />
                  <span :title="val">{{ val }}</span>
                </label>
                <div v-if="!valShown.length" class="colf-vmsg">无匹配值</div>
              </div>
              <div v-if="valTruncated" class="colf-vmsg colf-vmsg-warn">值过多，仅列前 500 个，请用「条件」模式</div>
            </template>
          </template>

          <!-- 条件模式：运算符 + 输入 -->
          <template v-else>
            <select v-model="op" class="colf-op">
              <option v-for="o in TEXT_OPS" :key="o.v" :value="o.v">{{ o.t }}</option>
            </select>
            <input v-if="needsValue" v-model="v1" class="colf-in" placeholder="输入关键字" @keyup.enter="apply" />
          </template>
        </template>

        <!-- 数字 -->
        <template v-else-if="type === 'number'">
          <div class="colf-ops">
            <button v-for="o in NUM_OPS" :key="o.v" type="button"
                    :class="{ act: op === o.v }" @click="op = o.v">{{ o.t }}</button>
          </div>
          <template v-if="needsValue">
            <template v-if="op === 'between'">
              <div class="colf-range">
                <input v-model="v1" class="colf-in" type="number" placeholder="最小" @keyup.enter="apply" />
                <span class="colf-tilde">~</span>
                <input v-model="v2" class="colf-in" type="number" placeholder="最大" @keyup.enter="apply" />
              </div>
            </template>
            <input v-else v-model="v1" class="colf-in" type="number" placeholder="数值" @keyup.enter="apply" />
          </template>
        </template>

        <!-- 日期范围 -->
        <template v-else-if="type === 'date'">
          <div v-if="datePresets" class="colf-chips">
            <button v-for="p in DATE_PRESETS" :key="p.k" type="button" @click="applyPreset(p.k)">{{ p.t }}</button>
            <button type="button" :class="{ act: op === 'empty' }" @click="op = 'empty'">为空</button>
            <button type="button" :class="{ act: op === 'not_empty' }" @click="op = 'not_empty'">不为空</button>
          </div>
          <div v-if="needsValue" class="colf-range colf-range-date">
            <input v-model="v1" class="colf-in" type="date" @keyup.enter="apply" />
            <span class="colf-tilde">~</span>
            <input v-model="v2" class="colf-in" type="date" @keyup.enter="apply" />
          </div>
        </template>

        <!-- 枚举多选 -->
        <template v-else-if="type === 'enum'">
          <div v-if="!single && !noExclude" class="colf-match-row">
            <span class="colf-match-lbl">匹配：</span>
            <button type="button" :class="{ act: op !== 'not_in' }" @click="op = 'in'">包含</button>
            <button type="button" :class="{ act: op === 'not_in' }" @click="op = 'not_in'">排除</button>
          </div>
          <div class="colf-enum">
            <label v-for="(o, i) in enumOpts" :key="i" class="colf-chk">
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

/* 选值 / 条件 模式切换条（文本型） */
.colf-modetab { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.colf-modetab button {
  flex: 1; padding: 5px 0; border: none; background: transparent; cursor: pointer;
  color: var(--muted); font-size: 11.5px; font-weight: 600;
}
.colf-modetab button.act { background: var(--primary); color: #fff; }

/* 枚举列「匹配：包含 / 排除」行 */
.colf-match-row { display: flex; align-items: center; gap: 4px; }
.colf-match-lbl { font-size: 11px; color: var(--muted); flex-shrink: 0; }
.colf-match-row button {
  padding: 2px 10px; border: 1px solid var(--border); border-radius: 10px;
  background: transparent; cursor: pointer; color: var(--muted); font-size: 11px;
}
.colf-match-row button.act { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.08); }

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
.colf-chips button.act { border-color: var(--primary); color: #fff; background: var(--primary); }
.colf-enum { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.colf-chk { display: flex; align-items: center; gap: 7px; padding: 4px 4px; border-radius: 5px; cursor: pointer; }
.colf-chk:hover { background: rgba(201,99,66,0.06); }
.colf-chk input { margin: 0; flex-shrink: 0; width: auto; }
.colf-chk span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.colf-chk-all { font-weight: 700; border-bottom: 1px dashed var(--border); border-radius: 0; padding-bottom: 5px; }
.colf-vmsg { font-size: 11px; color: var(--muted); padding: 4px 2px; }
.colf-vmsg-warn { color: #bf360c; }

.colf-foot { display: flex; gap: 6px; padding-top: 6px; border-top: 1px solid var(--border); }
.colf-clear, .colf-apply { flex: 1; padding: 6px 0; border-radius: 6px; cursor: pointer; font-size: 12px; }
.colf-clear { border: 1px solid var(--border); background: transparent; color: var(--muted); }
.colf-apply { border: 1px solid var(--primary); background: var(--primary); color: #fff; }
</style>
