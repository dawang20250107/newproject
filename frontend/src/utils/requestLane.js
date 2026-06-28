// 请求竞态取消：同一「车道」内每发起新请求即取消上一条在途请求，
// 杜绝「旧请求晚到 → 覆盖新数据」的竞态（快速切换筛选/翻页时最易触发）。
//
// 用法：
//   const lane = createRequestLane()
//   const r = await api.get('/approvals', { params, signal: lane.signal() })
//   // 被取消的请求 catch 到 { __canceled:true } 或其 signal.aborted 为 true
export function createRequestLane() {
  let controller = null
  return {
    // 取一个新信号：先中止上一条在途请求
    signal() {
      if (controller) controller.abort()
      controller = new AbortController()
      return controller.signal
    },
    // 主动中止当前在途请求（如组件卸载时）
    abort() {
      if (controller) { controller.abort(); controller = null }
    },
  }
}
