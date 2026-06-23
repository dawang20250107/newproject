<script setup>
// 单条筛选条件编辑器（维度 / 日期 / 金额）。被 FilterPanel 在顶层与条件组内复用，
// 保证编辑控件单一来源。就地修改 cond 对象后 emit('change')，由父组件统一提交。
import {
  DIM_FIELDS, DATE_FIELDS, AMT_FIELDS, DATE_RANGES, AMT_OPS,
} from '../../composables/arConditions.js'

const props = defineProps({
  cond: { type: Object, required: true },
  accessibleDepts: { type: Array, default: () => [] },
  years: { type: Array, default: () => [] },
})
const emit = defineEmits(['change', 'remove'])

const months = Array.from({ length: 12 }, (_, i) => i + 1)
const dimKind = field => (DIM_FIELDS.find(f => f.field === field) || {}).kind
const dimOpts = field => (DIM_FIELDS.find(f => f.field === field) || {}).opts || []
const fieldLabel = (list, field) => (list.find(f => f.field === field) || {}).label || field
function patch() { emit('change') }
</script>

<template>
  <div class="fl-row" :class="cond.t">
    <!-- 维度 -->
    <template v-if="cond.t === 'dim'">
      <span class="fl-field">{{ fieldLabel(DIM_FIELDS, cond.field) }}</span>
      <select v-if="dimKind(cond.field) === 'dept'" v-model="cond.value" class="fl-sel" @change="patch()">
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
      <select v-else-if="dimKind(cond.field) === 'year'" v-model.number="cond.value" class="fl-sel" @change="patch()">
        <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
      </select>
      <select v-else-if="dimKind(cond.field) === 'month'" v-model.number="cond.value" class="fl-sel" @change="patch()">
        <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
      </select>
      <!-- 运作年月：区间(start~end) + 含/不含 -->
      <template v-else-if="dimKind(cond.field) === 'ym'">
        <button class="fl-neg" :class="{ on: cond.exclude }"
          :title="cond.exclude ? '不含（排除该年月区间）' : '含（落在该年月区间）'"
          @click="cond.exclude = !cond.exclude; patch()">{{ cond.exclude ? '不含' : '含' }}</button>
        <input v-model="cond.value" type="month" class="fl-date" @change="patch()" />
        <span class="fl-dash">~</span>
        <input v-model="cond.end" type="month" class="fl-date" placeholder="同起" @change="patch()" />
      </template>
      <select v-else-if="dimKind(cond.field) === 'select'" v-model="cond.value" class="fl-sel" @change="patch()">
        <option v-for="o in dimOpts(cond.field)" :key="o.v" :value="o.v">{{ o.l }}</option>
      </select>
      <input v-else v-model="cond.value" class="fl-inp" placeholder="输入" @input="patch()" />
    </template>

    <!-- 日期 -->
    <template v-else-if="cond.t === 'date'">
      <span class="fl-field">{{ fieldLabel(DATE_FIELDS, cond.field) }}</span>
      <button class="fl-neg" :class="{ on: cond.exclude }"
        :title="cond.exclude ? '不含（排除该区间）' : '含（落在该区间）'"
        @click="cond.exclude = !cond.exclude; patch()">{{ cond.exclude ? '不含' : '含' }}</button>
      <select v-model="cond.range" class="fl-sel" @change="patch()">
        <option v-for="r in DATE_RANGES" :key="r.v" :value="r.v">{{ r.l }}</option>
      </select>
      <template v-if="cond.range === 'custom'">
        <input v-model="cond.start" type="date" class="fl-date" @change="patch()" />
        <span class="fl-dash">~</span>
        <input v-model="cond.end" type="date" class="fl-date" @change="patch()" />
      </template>
    </template>

    <!-- 金额 -->
    <template v-else>
      <span class="fl-field">{{ fieldLabel(AMT_FIELDS, cond.field) }}</span>
      <select v-model="cond.op" class="fl-sel" @change="patch()">
        <option v-for="o in AMT_OPS" :key="o.v" :value="o.v">{{ o.l }}</option>
      </select>
      <input v-if="['gt','lt','eq','ne'].includes(cond.op)" v-model="cond.value" type="number" class="fl-num" placeholder="数值" @input="patch()" />
      <template v-else-if="cond.op === 'between'">
        <input v-model="cond.min" type="number" class="fl-num" placeholder="下限" @input="patch()" />
        <span class="fl-dash">~</span>
        <input v-model="cond.max" type="number" class="fl-num" placeholder="上限" @input="patch()" />
      </template>
    </template>

    <button class="fl-x" title="移除" @click="emit('remove')">✕</button>
  </div>
</template>

<style scoped>
.fl-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; flex: 1; min-width: 0; }
.fl-field { font-weight: 700; font-size: 13px; min-width: 56px; }
.fl-sel, .fl-date, .fl-num, .fl-inp {
  border: 1px solid var(--border); border-radius: 7px; padding: 6px 10px; font-size: 13.5px; background: #fff;
  height: 34px; box-sizing: border-box;
}
.fl-sel { min-width: 120px; }
.fl-date { min-width: 130px; }
.fl-num { width: 96px; } .fl-inp { min-width: 150px; flex: 1; } .fl-dash { color: var(--muted); }
.fl-neg {
  border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; font-size: 11px;
  font-weight: 700; cursor: pointer; background: #fff; color: var(--muted);
}
.fl-neg.on { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.06); }
.fl-x { margin-left: auto; border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 12px; }
.fl-x:hover { color: #c62828; }
</style>
