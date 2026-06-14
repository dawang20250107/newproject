// 调用后端 SSE 流式 AI 接口，逐帧把 reasoning / answer 增量回调出去。
// 与 api/caiwu.js 共享 pk_token 鉴权；错误在开流前以 JSON 返回时会被解析抛出。
//
// 用法：
//   await streamAiAnalysis('/cockpit/ai-analysis/stream', body, {
//     onReasoning: d => reasoning.value += d,
//     onAnswer:    d => text.value += d,
//     onError:     m => err.value = m,
//   })
export async function streamAiAnalysis(path, body, { onReasoning, onAnswer, onError, onTool, onToolDone } = {}) {
  const token = localStorage.getItem('pk_token')
  const resp = await fetch(`/api/cw${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) {
    let msg = `AI 分析失败（${resp.status}）`
    try { const j = await resp.json(); msg = j.error || j.msg || msg } catch { /* not json */ }
    throw new Error(msg)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 2)
      if (!frame.startsWith('data:')) continue
      const payload = frame.slice(5).trim()
      if (!payload) continue
      let evt
      try { evt = JSON.parse(payload) } catch { continue }
      if (evt.type === 'reasoning') onReasoning && onReasoning(evt.delta)
      else if (evt.type === 'answer') onAnswer && onAnswer(evt.delta)
      else if (evt.type === 'tool') onTool && onTool(evt)
      else if (evt.type === 'tool_done') onToolDone && onToolDone(evt)
      else if (evt.type === 'error') onError && onError(evt.error || 'AI 分析失败')
    }
  }
}
