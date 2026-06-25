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
.skeleton-row td { padding: 10px 12px; }
.skeleton { display: inline-block; height: 14px; border-radius: 6px; background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%); background-size: 200% 100%; animation: sk-shimmer 1.4s infinite; }
@keyframes sk-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
</style>
