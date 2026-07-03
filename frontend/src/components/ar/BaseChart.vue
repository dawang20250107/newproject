<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart, FunnelChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent,
  MarkLineComponent, MarkAreaComponent, MarkPointComponent,
  DataZoomComponent, VisualMapComponent, GraphicComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, LineChart, PieChart, ScatterChart, FunnelChart,
  GridComponent, TooltipComponent, LegendComponent,
  MarkLineComponent, MarkAreaComponent, MarkPointComponent,
  DataZoomComponent, VisualMapComponent, GraphicComponent,
  CanvasRenderer])

const props = defineProps({
  option: { type: Object, default: null },
  height: { type: String, default: '320px' },
})
const emit = defineEmits(['click'])

const el = ref(null)
let chart = null
let ro = null

function init() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, isDark() ? 'dark' : null, { renderer: 'canvas' })
  chart.on('click', p => emit('click', p))
  // 关闭入场动画：低配设备上图表渲染更轻快（非侵入，不改传入 option）
  if (props.option) chart.setOption(withBase(props.option))
}

// 深色模式：随 html.dark 用 echarts dark 主题，背景透明；主题切换重建
const isDark = () => document.documentElement.classList.contains('dark')
const withBase = (opt) => ({ backgroundColor: 'transparent', ...opt, animation: false })

function resize() {
  chart?.resize()
}

onMounted(() => {
  init()
  window.addEventListener('kx-theme', init)
  ro = new ResizeObserver(resize)
  if (el.value) ro.observe(el.value)
})

onUnmounted(() => {
  window.removeEventListener('kx-theme', init)
  ro?.disconnect()
  chart?.dispose()
  chart = null
})

watch(() => props.option, opt => {
  if (!opt || !chart) return
  chart.setOption(withBase(opt), { notMerge: false, replaceMerge: ['series'] })
}, { deep: true })
</script>

<template>
  <div ref="el" :style="`width:100%;height:${height}`"></div>
</template>
