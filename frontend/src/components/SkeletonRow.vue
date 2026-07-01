<script setup>
defineProps({ cols: { type: Number, default: 6 } })
</script>
<template>
  <tr class="skeleton-row">
    <td v-for="i in cols" :key="i">
      <span class="skeleton" :style="{ width: i === 1 ? '60%' : i % 3 === 0 ? '40%' : '75%' }">&nbsp;</span>
    </td>
  </tr>
</template>
<style scoped>
.skeleton-row td { padding: var(--td-py, 10px) var(--td-px, 12px); }
.skeleton { display: inline-block; height: 13px; border-radius: 6px;
  background: linear-gradient(90deg, rgba(201,99,66,0.07) 25%, rgba(201,99,66,0.15) 50%, rgba(201,99,66,0.07) 75%);
  background-size: 200% 100%; animation: sk-shimmer 1.4s infinite; }
@keyframes sk-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
:global(html.perf-lite) .skeleton { animation: none; background: rgba(201,99,66,0.09); }
</style>
