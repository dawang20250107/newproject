<script setup>
// 统一的「加载中 / 空数据 / 错误」占位。各页面原本各自手写
// <div class="empty"><div class="icon">…</div>…</div>，图标与文案不一致，
// 这里收敛成一个组件，沿用全局 .empty 样式。
//
// 用法：
//   <EmptyState loading />                       → ⏳ 加载中…
//   <EmptyState empty />                         → 📭 暂无数据
//   <EmptyState empty text="暂无回款记录" />      → 📭 暂无回款记录
//   <EmptyState :error="loadErr" />              → ⚠️ {{ loadErr }}
//   <EmptyState icon="🎉" text="今日暂无计划付款" />
defineProps({
  loading: { type: Boolean, default: false },
  empty: { type: Boolean, default: false },
  error: { type: String, default: '' },
  icon: { type: String, default: '' },
  text: { type: String, default: '' },
})
</script>

<template>
  <div class="empty" :style="error ? 'color:#c62828' : ''">
    <div class="icon">{{ icon || (error ? '⚠️' : loading ? '⏳' : '📭') }}</div>
    <slot>{{ error || text || (loading ? '加载中…' : '暂无数据') }}</slot>
  </div>
</template>
