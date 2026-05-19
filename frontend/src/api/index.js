import axios from 'axios'
import router from '@/router/index.js'

const BASE = '/api'

const http = axios.create({
  baseURL: BASE,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

// Request interceptor: attach JWT token
http.interceptors.request.use(config => {
  const token = localStorage.getItem('kxt_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Response interceptor: handle 401, unwrap data
http.interceptors.response.use(
  r => r.data,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('kxt_token')
      localStorage.removeItem('kxt_user')
      router.push('/login')
    }
    return Promise.reject(err)
  }
)

// ─── 看板 ───────────────────────────────────────────────────
export const fetchKPI = () => http.get('/dashboard/kpi/')
export const fetchAbnormalRanking = () => http.get('/dashboard/abnormal-ranking/')
export const fetchManagerComparison = () => http.get('/dashboard/manager-comparison/')
export const fetchUnpaidDistribution = () => http.get('/dashboard/unpaid-distribution/')
export const fetchManagerDetail = (manager) => http.get('/dashboard/manager-detail/', { params: { manager } })
export const fetchMonthlyReceivedPaid = (p) => http.get('/dashboard/monthly-received-paid/', { params: p })

// ─── 认证 ───────────────────────────────────────────────────
export const auth = {
  login: (username, password) =>
    http.post('/auth/login', { username, password }),
  logout: () => {
    localStorage.removeItem('kxt_token')
    localStorage.removeItem('kxt_user')
  },
}

// ─── 日报 ───────────────────────────────────────────────────
export const report = {
  get: (date) => http.get(`/daily-report/${date}`),
  save: (date, data) => http.put(`/daily-report/${date}`, data),
  list: (year, month) => http.get('/daily-report/list', { params: { year, month } }),
  week: (date) => http.get('/daily-report/week', { params: { date } }),
}

export default http
