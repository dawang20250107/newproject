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
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.on('click', p => emit('click', p))
  // 关闭入场动画：低配设备上图表渲染更轻快（非侵入，不改传入 option）
  if (props.option) chart.setOption({ ...props.option, animation: false })
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  init()
  ro = new ResizeObserver(resize)
  if (el.value) ro.observe(el.value)
})

onUnmounted(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})

watch(() => props.option, opt => {
  if (!opt || !chart) return
  chart.setOption({ ...opt, animation: false }, { notMerge: false, replaceMerge: ['series'] })
}, { deep: true })
</script>

<template>
  <div ref="el" :style="`width:100%;height:${height}`"></div>
</template>
