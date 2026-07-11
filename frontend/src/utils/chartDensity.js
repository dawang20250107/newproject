// 数据密度感知：让图表按数据量选择呈现形态，而不是把稀疏数据硬塞进
// 为密集数据设计的图表里（12 格月度轴只有 1 格有柱 = 装饰大于信息）。
//
// 三档约定：
//   empty  — 无任何有效数据，走各页原有空态
//   sparse — 有效期数 ≤ sparseMax：放弃时间轴大图，切换为叙事卡（讲结论）
//   dense  — 数据足够密：完整图表（讲结构）
//
// 试点：现金流分析（资金故事卡）；验证后推广驾驶舱/应收分析/预算。

/**
 * 找出「有效期」下标：同一下标上任一序列非零即算有效。
 * @param {Array<Array<number>|undefined>} arrays 多个等长（或缺省）的按期序列
 * @returns {number[]} 有效下标列表
 */
export function activeIndices(arrays) {
  const len = Math.max(0, ...arrays.map(a => a?.length || 0))
  const idx = []
  for (let i = 0; i < len; i++) {
    if (arrays.some(a => a && Math.abs(a[i] || 0) > 1e-9)) idx.push(i)
  }
  return idx
}

/**
 * 密度分档。
 * @param {number} activeCount 有效期数
 * @param {object} [opts] { sparseMax=2 } 叙事卡阈值
 * @returns {'empty'|'sparse'|'dense'}
 */
export function densityOf(activeCount, opts = {}) {
  const { sparseMax = 2 } = opts
  if (!activeCount) return 'empty'
  return activeCount <= sparseMax ? 'sparse' : 'dense'
}
