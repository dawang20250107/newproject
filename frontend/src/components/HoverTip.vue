<script setup>
// 跟随鼠标的长文本浮层，配合 useHoverTip 使用：<HoverTip :tip="tip" />
defineProps({ tip: { type: Object, required: true } })
</script>

<template>
  <Teleport to="body">
    <Transition name="tip-fade">
      <div v-if="tip.show" class="cell-tooltip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">{{ tip.text }}</div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cell-tooltip {
  position: fixed; z-index: 9000; max-width: 320px; padding: 10px 14px; border-radius: 12px;
  background: rgba(36, 18, 10, 0.94); color: #f3e7dc; font-size: 13px; line-height: 1.55;
  white-space: normal; word-break: break-word; box-shadow: 0 10px 30px rgba(20, 8, 4, 0.4);
  border: 1px solid rgba(255,255,255,0.1); pointer-events: none; backdrop-filter: blur(6px);
}
.tip-fade-enter-active, .tip-fade-leave-active { transition: opacity 0.14s ease; }
.tip-fade-enter-from, .tip-fade-leave-to { opacity: 0; }
</style>
