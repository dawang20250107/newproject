<script setup>
import { ref } from 'vue'

// BI 式条件构建器：日期(相对区间/自定义 + 含/不含) 与 金额(运算符) 两类条件，
// 可任意叠加。v-model 绑定条件数组，直接序列化为后端 conditions(JSON) 参数。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'change'])

const DATE_FIELDS = [
  { field: 'due_date', label: '应收到期' },
  { field: 'payment_date', label: '回款日期' },
  { field: 'invoice_date', label: '开票日期' },
  { field: 'reconciliation_date', label: '对账日期' },
]
const AMT_FIELDS = [
  { field: 'estimated_amount', label: '预估金额' },
  { field: 'outstanding_amount', label: '未收金额' },
  { field: 'tax_amount', label: '税额' },
  { field: 'actual_invoice_amount', label: '开票额' },
  { field: 'account_diff_adjustment', label: '账实差额' },
]
const DATE_RANGES = [
  { v: 'this_week', l: '本周' }, { v: 'this_month', l: '本月' }, { v: 'last_month', l: '上月' },
  { v: 'next_month', l: '下月' }, { v: 'this_year', l: '本年' }, { v: 'last_year', l: '去年' },
  { v: 'custom', l: '自定义' },
]
const AMT_OPS = [
  { v: 'ne0', l: '≠0' }, { v: 'eq0', l: '=0' }, { v: 'gt0', l: '>0' }, { v: 'lt0', l: '<0' },
  { v: 'gt', l: '>' }, { v: 'lt', l: '<' }, { v: 'between', l: '区间' },
]

const labelOf = (list, field) => (list.find(f => f.field === field) || {}).label || field
const menuOpen = ref(false)

function update(list) {
  emit('update:modelValue', list)
  emit('change')
}
function addDate(field) {
  update([...props.modelValue, { t: 'date', field, range: 'this_month', exclude: false, start: '', end: '' }])
  menuOpen.value = false
}
function addAmt(field) {
  update([...props.modelValue, { t: 'amt', field, op: 'ne0', value: '', min: '', max: '' }])
  menuOpen.value = false
}
function removeAt(i) {
  const list = props.modelValue.slice(); list.splice(i, 1); update(list)
}
// 就地修改某条件字段后回传（v-model 子项不可直接 emit，统一走这里）
function patch() { update(props.modelValue.slice()) }
</script>

<template>
  <div class="cb">
    <!-- 已添加条件 -->
    <div v-for="(c, i) in modelValue" :key="i" class="cb-chip" :class="c.t">
      <template v-if="c.t === 'date'">
        <span class="cb-field">{{ labelOf(DATE_FIELDS, c.field) }}</span>
        <button class="cb-neg" :class="{ on: c.exclude }" :title="c.exclude ? '不含（排除该区间）' : '含（落在该区间）'"
          @click="c.exclude = !c.exclude; patch()">{{ c.exclude ? '不含' : '含' }}</button>
        <select v-model="c.range" class="cb-sel" @change="patch()">
          <option v-for="r in DATE_RANGES" :key="r.v" :value="r.v">{{ r.l }}</option>
        </select>
        <template v-if="c.range === 'custom'">
          <input v-model="c.start" type="date" class="cb-date" @change="patch()" />
          <span class="cb-dash">~</span>
          <input v-model="c.end" type="date" class="cb-date" @change="patch()" />
        </template>
      </template>
      <template v-else>
        <span class="cb-field">{{ labelOf(AMT_FIELDS, c.field) }}</span>
        <select v-model="c.op" class="cb-sel" @change="patch()">
          <option v-for="o in AMT_OPS" :key="o.v" :value="o.v">{{ o.l }}</option>
        </select>
        <input v-if="['gt','lt','eq'].includes(c.op)" v-model="c.value" type="number" class="cb-num"
          placeholder="数值" @input="patch()" />
        <template v-else-if="c.op === 'between'">
          <input v-model="c.min" type="number" class="cb-num" placeholder="下限" @input="patch()" />
          <span class="cb-dash">~</span>
          <input v-model="c.max" type="number" class="cb-num" placeholder="上限" @input="patch()" />
        </template>
      </template>
      <button class="cb-x" title="移除" @click="removeAt(i)">✕</button>
    </div>

    <!-- 添加按钮 + 菜单 -->
    <div class="cb-add-wrap">
      <button class="cb-add" :class="{ on: menuOpen }" @click="menuOpen = !menuOpen">＋ 条件</button>
      <div v-if="menuOpen" class="cb-backdrop" @click="menuOpen = false"></div>
      <div v-if="menuOpen" class="cb-menu">
        <div class="cb-menu-grp">日期</div>
        <button v-for="f in DATE_FIELDS" :key="f.field" class="cb-menu-item" @click="addDate(f.field)">{{ f.label }}</button>
        <div class="cb-menu-grp">金额</div>
        <button v-for="f in AMT_FIELDS" :key="f.field" class="cb-menu-item" @click="addAmt(f.field)">{{ f.label }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cb { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }

.cb-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 4px 3px 8px; border-radius: 8px; font-size: 12px;
  border: 1px solid var(--border); background: var(--glass, #fff);
}
.cb-chip.date { border-color: rgba(122,159,212,0.5); background: rgba(122,159,212,0.07); }
.cb-chip.amt  { border-color: rgba(201,99,66,0.45); background: rgba(201,99,66,0.06); }
.cb-field { font-weight: 700; }
.cb-sel, .cb-date, .cb-num {
  border: 1px solid var(--border); border-radius: 6px; padding: 2px 4px;
  font-size: 12px; background: #fff;
}
.cb-num { width: 64px; }
.cb-dash { color: var(--muted); }
.cb-neg {
  border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px;
  font-size: 11px; font-weight: 700; cursor: pointer; background: #fff; color: var(--muted);
}
.cb-neg.on { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.06); }
.cb-x { border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 12px; padding: 0 2px; }
.cb-x:hover { color: #c62828; }

.cb-add-wrap { position: relative; }
.cb-add {
  border: 1px dashed var(--border); border-radius: 8px; padding: 4px 10px;
  font-size: 12px; font-weight: 700; cursor: pointer; background: transparent; color: var(--primary);
}
.cb-add.on, .cb-add:hover { border-color: var(--primary); background: rgba(201,99,66,0.06); }
.cb-backdrop { position: fixed; inset: 0; z-index: 40; }
.cb-menu {
  position: absolute; top: calc(100% + 4px); left: 0; z-index: 41;
  min-width: 132px; padding: 6px; border-radius: 10px;
  background: #fff; border: 1px solid var(--border); box-shadow: 0 10px 30px rgba(0,0,0,0.14);
}
.cb-menu-grp { font-size: 11px; color: var(--muted); font-weight: 700; padding: 4px 8px 2px; }
.cb-menu-item {
  display: block; width: 100%; text-align: left; border: none; background: transparent;
  padding: 6px 8px; border-radius: 6px; font-size: 13px; cursor: pointer; color: var(--text);
}
.cb-menu-item:hover { background: rgba(201,99,66,0.08); color: var(--primary); }
</style>
