// 共享 ECharts 样式工具。统一暖色坐标轴风格，并彻底解决三类裁切问题：
//   1) 纵轴单位名（达成率% / 回款率%）定位不当被容器边缘裁掉；
//   2) 旋转的横轴类目标签与底部图例互相遮挡；
//   3) 横向条形图类目名（项目/负责人）被截断且无完整信息。
// 所有看板（驾驶舱、指标、应收分析、现金流、预算、走势）共用这套配置。

export const AXIS_COLOR = '#9b8070'
export const AXIS_LINE = '#d4c4b4'
export const SPLIT_LINE = 'rgba(180,140,110,.15)'

/** 紧凑金额格式（万/亿），用于坐标轴刻度。 */
export function axisMoney(v) {
  const n = Math.abs(v)
  if (n >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (n >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v
}

/**
 * 数值轴。传 name 时单位名固定在轴顶端、贴轴线方向排布，配合 gridFor({nameTop:true})
 * 预留的 40px 顶部空间，确保「达成率%」「回款率%」永不被裁切。
 * @param {object} o { name, formatter, min, max, position:'left'|'right' }
 */
export function valueAxis(o = {}) {
  const { name = '', formatter, min, max, position = 'left' } = o
  const ax = {
    type: 'value',
    axisLabel: { color: AXIS_COLOR, fontSize: 10, formatter },
    splitLine: { lineStyle: { color: SPLIT_LINE } },
  }
  if (name) {
    ax.name = name
    ax.nameLocation = 'end'
    ax.nameGap = 12
    ax.nameTextStyle = {
      color: AXIS_COLOR, fontSize: 11, fontWeight: 600,
      align: position === 'right' ? 'right' : 'left',
    }
  }
  if (min != null) ax.min = min
  if (max != null) ax.max = max
  if (position === 'right') ax.position = 'right'
  return ax
}

/**
 * 类目轴（横向 X）。拥挤时（类目数 > threshold）自动旋转，必须搭配 gridFor 预留底部空间。
 * @param {string[]} names
 * @param {object} o { threshold=4, rotate=28 }
 */
export function catAxis(names, o = {}) {
  const { threshold = 4, rotate = 28 } = o
  return {
    type: 'category',
    data: names,
    axisLine: { lineStyle: { color: AXIS_LINE } },
    axisTick: { show: false },
    axisLabel: {
      color: AXIS_COLOR, fontSize: 11, interval: 0,
      rotate: names.length > threshold ? rotate : 0,
    },
  }
}

/**
 * 纵向类目轴（横向条形图），如项目名/负责人。给足宽度并截断超长名，
 * 完整名通过 tooltip 展示（调用方 tooltip 已默认显示类目）。
 */
export function catAxisVertical(o = {}) {
  const { width = 110 } = o
  return {
    type: 'category',
    axisLine: { lineStyle: { color: AXIS_LINE } },
    axisTick: { show: false },
    axisLabel: { color: AXIS_COLOR, fontSize: 11, width, overflow: 'truncate' },
  }
}

/**
 * 统一 grid。按是否有顶端轴名 / 底部图例 / 旋转类目，预留恰当边距，配合 containLabel。
 * @param {string[]} names 用于判断是否旋转
 * @param {object} o { nameTop=false, legend=true, threshold=4, right=24, left=16, vertical=false }
 */
export function gridFor(names = [], o = {}) {
  const { nameTop = false, legend = true, threshold = 4, right = 24, left = 16, vertical = false } = o
  const rotated = !vertical && names.length > threshold
  return {
    top: nameTop ? 42 : 24,
    right,
    left,
    bottom: (legend ? 40 : 12) + (rotated ? 18 : 0),
    containLabel: true,
  }
}

/** 底部图例，居中、可滚动、间距统一。 */
export function bottomLegend(extra = {}) {
  return { bottom: 0, type: 'scroll', itemGap: 16, textStyle: { fontSize: 11, color: '#6b5a4a' }, ...extra }
}

// ── 麦肯锡式数值标签 ──────────────────────────────────────────────────────────
// 咨询级图表的核心：让读者直接读数，而非靠悬浮或坐标轴反推。所有带标签的系列都配
// hideOverlap，密集图表（如 12 个月 × 多系列）自动隐藏会重叠的标签，保持清爽。

export const LABEL_COLOR = '#5f4d3d'
const LABEL_FONT = 10.5

/** 防重叠布局：挂到任何带数值标签的系列上，拥挤时自动取舍、必要时纵向微移。 */
export const HIDE_OVERLAP = { hideOverlap: true, moveOverlap: 'shiftY' }

/** 纵向柱：标签居柱顶。 */
export function topLabel(formatter, extra = {}) {
  return {
    show: true, position: 'top', distance: 3,
    fontSize: LABEL_FONT, fontWeight: 600, color: LABEL_COLOR,
    formatter, ...extra,
  }
}

/** 横向条：标签在右端。 */
export function rightLabel(formatter, extra = {}) {
  return {
    show: true, position: 'right', distance: 5,
    fontSize: LABEL_FONT, fontWeight: 600, color: LABEL_COLOR,
    formatter, ...extra,
  }
}

/** 堆叠段内：白字居中，小段靠 hideOverlap 自动隐藏，避免压字。 */
export function insideLabel(formatter, extra = {}) {
  return {
    show: true, position: 'inside',
    fontSize: 10, fontWeight: 600, color: '#fff',
    textBorderColor: 'rgba(0,0,0,0.18)', textBorderWidth: 2,
    formatter, ...extra,
  }
}

/** 折线末端直接标注（咨询式 direct labeling）：在最后一个点右侧标值，
 *  比逐点标签更干净；多线时配 grid 右留白避免裁切。带白描边保证压线可读。 */
export function endLabel(formatter, extra = {}) {
  return {
    show: true, distance: 6,
    fontSize: LABEL_FONT, fontWeight: 700,
    textBorderColor: '#fff', textBorderWidth: 3,
    formatter, ...extra,
  }
}

/** 统一 tooltip 外观：白底、细边、柔和投影、圆角，全站一致。 */
export const TOOLTIP = {
  backgroundColor: 'rgba(255,255,255,0.97)',
  borderColor: 'rgba(0,0,0,0.08)', borderWidth: 1,
  textStyle: { fontSize: 12, color: '#3a2f28' },
  padding: [8, 12],
  extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,0.10);border-radius:8px;',
}
