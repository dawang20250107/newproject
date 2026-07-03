<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, CustomChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent,
  TitleComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent,
} from 'echarts/components'

echarts.use([
  CanvasRenderer, LineChart, BarChart, CustomChart, PieChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent,
  TitleComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent,
])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '340px' },
})

const chartEl = ref(null)
let instance = null
let resizeObserver = null

// 深色模式：随 html.dark 使用 echarts 内置 dark 主题（文字/轴自动可读），
// 背景强制透明以贴合站内暖色深底；主题切换事件触发重建。
const isDark = () => document.documentElement.classList.contains('dark')
const withBase = (opt) => ({ backgroundColor: 'transparent', ...opt, animation: false })

function initChart() {
  if (!chartEl.value) return
  resizeObserver?.disconnect()
  instance?.dispose()
  instance = echarts.init(chartEl.value, isDark() ? 'dark' : null, { renderer: 'canvas' })
  // 关闭入场动画：低配设备上图表渲染更轻快（非侵入，不改传入 option）
  instance.setOption(withBase(props.option))
  resizeObserver = new ResizeObserver(() => instance?.resize())
  resizeObserver.observe(chartEl.value)
}

watch(() => props.option, (val) => {
  if (instance) instance.setOption(withBase(val), { notMerge: true })
}, { deep: true })

onMounted(() => {
  initChart()
  window.addEventListener('kx-theme', initChart)
})

onUnmounted(() => {
  window.removeEventListener('kx-theme', initChart)
  resizeObserver?.disconnect()
  instance?.dispose()
})
</script>

<template>
  <div ref="chartEl" :style="`width:100%;height:${height}`" />
</template>
