<script setup>
import { ref } from 'vue'
import {
  DIM_FIELDS, DATE_FIELDS, AMT_FIELDS, DATE_RANGES, AMT_OPS,
} from '../../composables/arConditions.js'

// Power BI 式筛选面板：顶部 且/或 切换 + 统一条件列表 + ＋添加条件 菜单。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },   // conditions
  match: { type: String, default: 'all' },           // 'all'(且) | 'any'(或)
  accessibleDepts: { type: Array, default: () => [] },
  years: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'update:match', 'change', 'close'])

const months = Array.from({ length: 12 }, (_, i) => i + 1)
const addMenu = ref(false)

function commit(list) { emit('update:modelValue', list); emit('change') }
function setMatch(m) { emit('update:match', m); emit('change') }
function patch() { commit(props.modelValue.slice()) }
function removeAt(i) { const l = props.modelValue.slice(); l.splice(i, 1); commit(l) }

function addDim(field) {
  const f = DIM_FIELDS.find(x => x.field === field)
  let value = ''
  if (f.kind === 'dept') value = props.accessibleDepts[0] || ''
  else if (f.kind === 'year') value = props.years[0] || ''
  else if (f.kind === 'month') value = 1
  else if (f.kind === 'select') value = f.opts[0].v
  commit([...props.modelValue, { t: 'dim', field, value }]); addMenu.value = false
}
function addDate(field) {
  commit([...props.modelValue, { t: 'date', field, range: 'this_month', exclude: false, start: '', end: '' }])
  addMenu.value = false
}
function addAmt(field) {
  commit([...props.modelValue, { t: 'amt', field, op: 'ne0', value: '', min: '', max: '' }])
  addMenu.value = false
}

const dimKind = field => (DIM_FIELDS.find(f => f.field === field) || {}).kind
const dimOpts = field => (DIM_FIELDS.find(f => f.field === field) || {}).opts || []
const fieldLabel = (list, field) => (list.find(f => f.field === field) || {}).label || field
</script>

<template>
  <div class="fp">
    <div class="fp-head">
      <div class="fp-match">
        满足
        <button class="seg" :class="{ on: match === 'all' }" @click="setMatch('all')">全部（且）</button>
        <button class="seg" :class="{ on: match === 'any' }" @click="setMatch('any')">任一（或）</button>
        条件
      </div>
      <button class="fp-close" title="关闭" @click="emit('close')">✕</button>
    </div>

    <div class="fp-body">
      <div v-if="!modelValue.length" class="fp-empty">尚无筛选条件，点下方「＋ 添加条件」。</div>

      <div v-for="(c, i) in modelValue" :key="i" class="fp-row" :class="c.t">
        <span class="fp-conn" v-if="i > 0">{{ match === 'any' ? '或' : '且' }}</span>
        <span class="fp-conn ghost" v-else>　</span>

        <!-- 维度 -->
        <template v-if="c.t === 'dim'">
          <span class="fp-field">{{ fieldLabel(DIM_FIELDS, c.field) }}</span>
          <select v-if="dimKind(c.field) === 'dept'" v-model="c.value" class="fp-sel" @change="patch()">
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <select v-else-if="dimKind(c.field) === 'year'" v-model.number="c.value" class="fp-sel" @change="patch()">
            <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
          </select>
          <select v-else-if="dimKind(c.field) === 'month'" v-model.number="c.value" class="fp-sel" @change="patch()">
            <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
          </select>
          <select v-else-if="dimKind(c.field) === 'select'" v-model="c.value" class="fp-sel" @change="patch()">
            <option v-for="o in dimOpts(c.field)" :key="o.v" :value="o.v">{{ o.l }}</option>
          </select>
          <input v-else v-model="c.value" class="fp-inp" :placeholder="c.field === 'q' ? '项目/负责人/编号' : '输入'" @input="patch()" />
        </template>

        <!-- 日期 -->
        <template v-else-if="c.t === 'date'">
          <span class="fp-field">{{ fieldLabel(DATE_FIELDS, c.field) }}</span>
          <button class="fp-neg" :class="{ on: c.exclude }" :title="c.exclude ? '不含（排除该区间）' : '含（落在该区间）'"
            @click="c.exclude = !c.exclude; patch()">{{ c.exclude ? '不含' : '含' }}</button>
          <select v-model="c.range" class="fp-sel" @change="patch()">
            <option v-for="r in DATE_RANGES" :key="r.v" :value="r.v">{{ r.l }}</option>
          </select>
          <template v-if="c.range === 'custom'">
            <input v-model="c.start" type="date" class="fp-date" @change="patch()" />
            <span class="fp-dash">~</span>
            <input v-model="c.end" type="date" class="fp-date" @change="patch()" />
          </template>
        </template>

        <!-- 金额 -->
        <template v-else>
          <span class="fp-field">{{ fieldLabel(AMT_FIELDS, c.field) }}</span>
          <select v-model="c.op" class="fp-sel" @change="patch()">
            <option v-for="o in AMT_OPS" :key="o.v" :value="o.v">{{ o.l }}</option>
          </select>
          <input v-if="['gt','lt','eq'].includes(c.op)" v-model="c.value" type="number" class="fp-num" placeholder="数值" @input="patch()" />
          <template v-else-if="c.op === 'between'">
            <input v-model="c.min" type="number" class="fp-num" placeholder="下限" @input="patch()" />
            <span class="fp-dash">~</span>
            <input v-model="c.max" type="number" class="fp-num" placeholder="上限" @input="patch()" />
          </template>
        </template>

        <button class="fp-x" title="移除" @click="removeAt(i)">✕</button>
      </div>
    </div>

    <div class="fp-foot">
      <div class="fp-add-wrap">
        <button class="fp-add" :class="{ on: addMenu }" @click="addMenu = !addMenu">＋ 添加条件</button>
        <div v-if="addMenu" class="fp-backdrop" @click="addMenu = false"></div>
        <div v-if="addMenu" class="fp-menu">
          <div class="fp-menu-grp">维度</div>
          <button v-for="f in DIM_FIELDS" :key="f.field" class="fp-menu-item" @click="addDim(f.field)">{{ f.label }}</button>
          <div class="fp-menu-grp">日期</div>
          <button v-for="f in DATE_FIELDS" :key="f.field" class="fp-menu-item" @click="addDate(f.field)">{{ f.label }}</button>
          <div class="fp-menu-grp">金额</div>
          <button v-for="f in AMT_FIELDS" :key="f.field" class="fp-menu-item" @click="addAmt(f.field)">{{ f.label }}</button>
        </div>
      </div>
      <button v-if="modelValue.length" class="fp-clear" @click="commit([])">清空全部</button>
    </div>
  </div>
</template>

<style scoped>
.fp { width: 520px; max-width: 94vw; display: flex; flex-direction: column; max-height: 70vh; }
.fp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; border-bottom: 1px solid var(--border);
}
.fp-match { font-size: 13px; color: var(--text); display: flex; align-items: center; gap: 6px; }
.seg {
  border: 1px solid var(--border); background: #fff; cursor: pointer;
  font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 7px; color: var(--muted);
}
.seg.on { border-color: var(--primary); background: rgba(201,99,66,0.08); color: var(--primary); }
.fp-close { border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 14px; }

.fp-body { padding: 10px 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.fp-empty { color: var(--muted); font-size: 13px; padding: 8px 0; }
.fp-row {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  padding: 6px 8px; border-radius: 9px; border: 1px solid var(--border);
}
.fp-row.dim  { background: rgba(120,120,120,0.04); }
.fp-row.date { background: rgba(122,159,212,0.07); border-color: rgba(122,159,212,0.4); }
.fp-row.amt  { background: rgba(201,99,66,0.06); border-color: rgba(201,99,66,0.4); }
.fp-conn { font-size: 11px; font-weight: 800; color: var(--primary); width: 18px; text-align: center; }
.fp-conn.ghost { color: transparent; }
.fp-field { font-weight: 700; font-size: 13px; }
.fp-sel, .fp-date, .fp-num, .fp-inp {
  border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; font-size: 13px; background: #fff;
}
.fp-sel { min-width: 104px; }                /* 加宽下拉，长选项(部门/责任阶段)不挤 */
.fp-date { min-width: 130px; }
.fp-num { width: 90px; } .fp-inp { min-width: 160px; flex: 1; } .fp-dash { color: var(--muted); }
.fp-neg {
  border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; font-size: 11px;
  font-weight: 700; cursor: pointer; background: #fff; color: var(--muted);
}
.fp-neg.on { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.06); }
.fp-x { margin-left: auto; border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 12px; }
.fp-x:hover { color: #c62828; }

.fp-foot {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; border-top: 1px solid var(--border);
}
.fp-add-wrap { position: relative; }
.fp-add {
  border: 1px dashed var(--primary); border-radius: 8px; padding: 5px 12px;
  font-size: 13px; font-weight: 700; cursor: pointer; background: transparent; color: var(--primary);
}
.fp-add.on, .fp-add:hover { background: rgba(201,99,66,0.07); }
.fp-clear { border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 12px; }
.fp-clear:hover { color: #c62828; }
.fp-backdrop { position: fixed; inset: 0; z-index: 60; }
.fp-menu {
  position: absolute; bottom: calc(100% + 4px); left: 0; z-index: 61;
  min-width: 150px; max-height: 320px; overflow-y: auto; padding: 6px;
  border-radius: 10px; background: #fff; border: 1px solid var(--border); box-shadow: 0 12px 32px rgba(0,0,0,0.16);
}
.fp-menu-grp { font-size: 11px; color: var(--muted); font-weight: 700; padding: 6px 8px 2px; }
.fp-menu-item {
  display: block; width: 100%; text-align: left; border: none; background: transparent;
  padding: 6px 8px; border-radius: 6px; font-size: 13px; cursor: pointer; color: var(--text);
}
.fp-menu-item:hover { background: rgba(201,99,66,0.08); color: var(--primary); }
</style>
