<script setup>
// 金额展示（系统级复用）：页面上显示缩略值（如 1234.6万），hover 提示精确到分的完整值。
// 财务核对必须能看到精确数——所有 fmtCompact/万元缩略的 KPI、合计、汇总栏都应套本组件。
// 用法：<Amt :v="row.amount" :fmt="fmtWan" />  fmt 缺省用 fmtCompact 默认档。
import { computed } from 'vue'
import { fmtCompact } from '../utils/format.js'

const props = defineProps({
  v: { type: [Number, String], default: 0 },
  fmt: { type: Function, default: null },     // 缩略格式化函数（页面自带的 fmtWan/fmtAmt 等）
  prefix: { type: String, default: '' },      // 展示前缀（如 +/−，已含在 fmt 里则不传）
})

const num = computed(() => {
  const n = parseFloat(props.v)
  return isNaN(n) ? null : n
})
const shown = computed(() => {
  const f = props.fmt || (x => fmtCompact(x))
  return props.prefix + f(props.v)
})
// 精确值：千分位 + 两位小数；空值不出提示
const exact = computed(() => (num.value == null ? ''
  : '¥' + num.value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })))
</script>

<template>
  <span class="amt-x" :title="exact">{{ shown }}</span>
</template>

<style scoped>
.amt-x { font-variant-numeric: tabular-nums; cursor: default; }
</style>
