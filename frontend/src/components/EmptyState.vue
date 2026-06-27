<script setup>
// 统一的「加载中 / 空数据 / 错误 / 无搜索结果 / 无权限」占位插画体系。
// 各页面原本各自手写 emoji + 文案，图标与文案不一致，这里收敛为一套
// 线性 SVG 插画（暖陶土色系，与全局设计统一）。
//
// 向后兼容旧 API：
//   <EmptyState loading />                       → 加载中…（含动效）
//   <EmptyState empty />                         → 暂无数据
//   <EmptyState empty text="暂无回款记录" />      → 自定义文案
//   <EmptyState :error="loadErr" />              → 错误插画 + 错误文案
//   <EmptyState icon="🎉" text="今日暂无计划付款" />  → 兼容旧 emoji
//
// 新增能力：
//   <EmptyState variant="search" text="未找到匹配记录" />   → 无搜索结果
//   <EmptyState variant="forbidden" text="无访问权限" />     → 无权限
//   <EmptyState ... ><button>新建</button></EmptyState>     → 操作插槽（actions）
import { computed } from 'vue'

const props = defineProps({
  loading: { type: Boolean, default: false },
  empty: { type: Boolean, default: false },
  error: { type: String, default: '' },
  icon: { type: String, default: '' },        // 兼容旧 emoji，传入则优先显示
  text: { type: String, default: '' },
  // 'auto' | 'empty' | 'loading' | 'error' | 'search' | 'forbidden'
  variant: { type: String, default: 'auto' },
  size: { type: String, default: 'md' },       // 'sm' | 'md'
})

// 解析最终状态：显式 variant 优先，否则由 loading/error/empty 推导
const kind = computed(() => {
  if (props.variant !== 'auto') return props.variant
  if (props.error) return 'error'
  if (props.loading) return 'loading'
  return 'empty'
})

const message = computed(() => {
  if (props.error) return props.error
  if (props.text) return props.text
  return { loading: '加载中…', empty: '暂无数据', search: '未找到匹配的记录',
           forbidden: '暂无访问权限', error: '加载失败' }[kind.value] || '暂无数据'
})
</script>

<template>
  <div class="estate" :class="[`estate-${kind}`, `estate-${size}`]">
    <!-- 兼容：显式传入 emoji 时仍按旧样式渲染 -->
    <div v-if="icon" class="estate-emoji">{{ icon }}</div>

    <!-- 加载：旋转环 + 暖色渐变 -->
    <svg v-else-if="kind === 'loading'" class="estate-art estate-spin" viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="19" stroke="var(--border)" stroke-width="4"/>
      <path d="M43 24a19 19 0 0 0-19-19" stroke="url(#esg)" stroke-width="4" stroke-linecap="round"/>
      <defs><linearGradient id="esg" x1="24" y1="5" x2="43" y2="24" gradientUnits="userSpaceOnUse">
        <stop stop-color="#e0845c"/><stop offset="1" stop-color="#c96342"/>
      </linearGradient></defs>
    </svg>

    <!-- 错误：警示三角 + 圆底 -->
    <svg v-else-if="kind === 'error'" class="estate-art" viewBox="0 0 80 64" fill="none">
      <ellipse cx="40" cy="56" rx="30" ry="4" fill="rgba(198,40,40,0.08)"/>
      <path d="M40 14 64 50H16L40 14Z" fill="rgba(198,40,40,0.07)" stroke="#c62828" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 30v10" stroke="#c62828" stroke-width="3" stroke-linecap="round"/>
      <circle cx="40" cy="45.5" r="1.9" fill="#c62828"/>
    </svg>

    <!-- 无搜索结果：放大镜 + 虚线 -->
    <svg v-else-if="kind === 'search'" class="estate-art" viewBox="0 0 80 64" fill="none">
      <ellipse cx="40" cy="57" rx="28" ry="4" fill="rgba(201,99,66,0.07)"/>
      <circle cx="35" cy="28" r="16" fill="rgba(201,99,66,0.05)" stroke="var(--primary)" stroke-width="2.4"/>
      <path d="M46.5 39.5 58 51" stroke="var(--primary)" stroke-width="3" stroke-linecap="round"/>
      <path d="M29 28h12M35 22v12" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" opacity="0.4" stroke-dasharray="2 3"/>
    </svg>

    <!-- 无权限：盾牌锁 -->
    <svg v-else-if="kind === 'forbidden'" class="estate-art" viewBox="0 0 80 64" fill="none">
      <ellipse cx="40" cy="57" rx="26" ry="4" fill="rgba(138,116,100,0.08)"/>
      <path d="M40 8 60 16v14c0 12-8.5 20-20 24-11.5-4-20-12-20-24V16L40 8Z"
            fill="rgba(138,116,100,0.06)" stroke="var(--muted)" stroke-width="2.4" stroke-linejoin="round"/>
      <rect x="33" y="29" width="14" height="11" rx="2" stroke="var(--muted)" stroke-width="2.2"/>
      <path d="M36 29v-3a4 4 0 0 1 8 0v3" stroke="var(--muted)" stroke-width="2.2"/>
    </svg>

    <!-- 空数据：文件箱（默认） -->
    <svg v-else class="estate-art" viewBox="0 0 80 64" fill="none">
      <ellipse cx="40" cy="57" rx="28" ry="4" fill="rgba(201,99,66,0.07)"/>
      <path d="M18 22h17l5 6h22v22a4 4 0 0 1-4 4H22a4 4 0 0 1-4-4V22Z"
            fill="rgba(201,99,66,0.05)" stroke="var(--primary-light)" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M18 30h44" stroke="var(--primary-light)" stroke-width="2" opacity="0.5"/>
      <path d="M31 41h18" stroke="var(--primary-light)" stroke-width="2" stroke-linecap="round" opacity="0.4"/>
    </svg>

    <div class="estate-text"><slot>{{ message }}</slot></div>
    <div v-if="$slots.actions" class="estate-actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.estate {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 52px 24px; color: var(--muted); gap: 4px;
}
.estate-sm { padding: 24px 16px; }
.estate-art { width: 80px; height: 64px; margin-bottom: 10px; }
.estate-sm .estate-art { width: 56px; height: 44px; margin-bottom: 6px; }
.estate-emoji { font-size: 42px; margin-bottom: 12px; line-height: 1; }
.estate-text { font-size: 14px; line-height: 1.6; max-width: 360px; }
.estate-sm .estate-text { font-size: 13px; }
.estate-error .estate-text { color: #c62828; }
.estate-actions { margin-top: 14px; }

/* 加载旋转 */
.estate-spin { animation: estate-rot 0.85s linear infinite; }
@keyframes estate-rot { to { transform: rotate(360deg); } }
/* 性能模式下停掉动画 */
:global(html.perf-lite) .estate-spin { animation: none; }
</style>
