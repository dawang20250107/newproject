import api from './index.js'

// 低频「参考数据」缓存（部门、字典等）：会话内共享一份，避免每个页面重复请求。
// 进行中的请求也会去重（同一 url 并发只发一次）。默认 TTL 5 分钟。
const cache = new Map()   // url -> { p: Promise, t: number }

export function cachedGet(url, ttlMs = 5 * 60 * 1000) {
  const now = Date.now()
  const hit = cache.get(url)
  if (hit && (now - hit.t) < ttlMs) return hit.p
  // 请求失败不缓存，避免把一次网络抖动钉死 TTL
  const p = api.get(url).catch((e) => { cache.delete(url); throw e })
  cache.set(url, { p, t: now })
  return p
}

// 数据变更后主动失效（不传 url 清空全部）
export function invalidateRef(url) {
  if (url) cache.delete(url)
  else cache.clear()
}
