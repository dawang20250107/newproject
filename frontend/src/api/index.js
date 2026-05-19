import axios from 'axios'

// 后端 API 基础地址（通过 Nginx 代理）
const BASE = '/api'

// 创建 axios 实例
const http = axios.create({
  baseURL: BASE,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

// 响应拦截器：统一处理错误
http.interceptors.response.use(
  r => r.data,
  err => Promise.reject(err)
)

// ─── 看板 ───────────────────────────────────────────────────
export const fetchKPI = () => http.get('/dashboard/kpi/')
export const fetchAbnormalRanking = () => http.get('/dashboard/abnormal-ranking/')
export const fetchManagerComparison = () => http.get('/dashboard/manager-comparison/')
export const fetchUnpaidDistribution = () => http.get('/dashboard/unpaid-distribution/')
export const fetchManagerDetail = (manager) => http.get('/dashboard/manager-detail/', { params: { manager } })
export const fetchMonthlyReceivedPaid = (p) => http.get('/dashboard/monthly-received-paid/', { params: p })

export default http
