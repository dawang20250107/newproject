<script setup>
const props = defineProps({ status: String })
const map = { settled: ['✅ 已付清', 'badge-settled'], partial: ['⚡ 部分付款', 'badge-partial'], pending: ['⏳ 待付款', 'badge-pending'], adjusted: ['📋 计划调整', 'badge-adjusted'] }
const [label, cls] = map[props.status] || ['—', '']
</script>
<template>
  <span :class="['badge', cls]">{{ label }}</span>
</template>
