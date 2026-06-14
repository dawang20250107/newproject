<script setup>
// 业财 AI 助手品牌标识：暖色渐变机器人头 + 深色面罩 + 发光眼 + 天线火花。
// 可缩放、随主色协调；每个实例用唯一渐变 id，避免多处复用时 id 冲突。
// light: 浅色变体，用于品牌橙色按钮等深底场景，保证对比度。
const props = defineProps({
  size: { type: [Number, String], default: 24 },
  light: { type: Boolean, default: false },
})
const uid = 'aim' + Math.random().toString(36).slice(2, 8)
const stops = props.light
  ? ['#ffffff', '#ffe2c8', '#ffcaa0']
  : ['#f2b06c', '#d8744d', '#bd5438']
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 32 32" fill="none" class="ai-mark" aria-hidden="true">
    <defs>
      <linearGradient :id="uid" x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
        <stop offset="0" :stop-color="stops[0]" />
        <stop offset=".5" :stop-color="stops[1]" />
        <stop offset="1" :stop-color="stops[2]" />
      </linearGradient>
    </defs>
    <!-- 天线火花 -->
    <line x1="16" y1="6.6" x2="16" y2="3.6" :stroke="`url(#${uid})`" stroke-width="2" stroke-linecap="round" />
    <circle cx="16" cy="2.7" r="1.9" :fill="`url(#${uid})`" />
    <!-- 侧耳 -->
    <rect x="2.3" y="13" width="2.7" height="6.2" rx="1.35" :fill="`url(#${uid})`" />
    <rect x="27" y="13" width="2.7" height="6.2" rx="1.35" :fill="`url(#${uid})`" />
    <!-- 头部 -->
    <rect x="5" y="6.8" width="22" height="18.4" rx="7.2" :fill="`url(#${uid})`" />
    <!-- 顶部柔光高光 -->
    <rect x="5" y="6.8" width="22" height="9" rx="7.2" fill="#fff" opacity=".15" />
    <!-- 面罩 -->
    <rect x="8.4" y="10.8" width="15.2" height="10" rx="5" fill="#3a1d12" opacity=".9" />
    <!-- 发光眼 + 微笑 -->
    <circle cx="12.8" cy="15.6" r="1.85" fill="#ffdcb4" />
    <circle cx="19.2" cy="15.6" r="1.85" fill="#ffdcb4" />
    <rect x="13.6" y="18.2" width="4.8" height="1.25" rx=".62" fill="#ffdcb4" opacity=".5" />
  </svg>
</template>

<style scoped>
.ai-mark { display: inline-block; vertical-align: middle; }
</style>
