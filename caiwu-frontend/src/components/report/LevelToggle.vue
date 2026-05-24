<script setup>
const props = defineProps({
  modelValue: { type: Number, default: 1 },
  maxLevel: { type: Number, default: 3 },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="level-toggle">
    <button
      v-for="n in maxLevel" :key="n"
      :class="['lv-btn', { active: modelValue === n }]"
      @click="emit('update:modelValue', n)"
    >
      {{ ['一级', '二级', '三级'][n-1] }}
    </button>
  </div>
</template>

<style scoped>
.level-toggle { display: inline-flex; background: var(--bg2); border-radius: 10px; padding: 3px; gap: 2px; }
.lv-btn {
  padding: 5px 16px; border-radius: 8px; border: none; cursor: pointer;
  font-size: 12px; font-weight: 600; color: var(--muted); background: none;
  transition: all .16s;
}
.lv-btn:hover { color: var(--primary); }
.lv-btn.active { background: var(--card); color: var(--primary); box-shadow: 0 1px 4px rgba(100,60,30,.12); }
</style>
