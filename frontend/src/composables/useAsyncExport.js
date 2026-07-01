import { ref } from 'vue'
import api from '../api/index.js'
import { downloadBlob } from '../utils/download.js'
import { useToast } from './useToast.js'

// 异步导出：建后台任务 → 轮询状态 → 完成自动下载。供审批/付款列表共用。
// 用法：
//   const { exporting, startExport } = useAsyncExport()
//   startExport('approvals', buildParams())
export function useAsyncExport() {
  const toast = useToast()
  const exporting = ref(false)
  let timer = null

  function stop() { if (timer) { clearTimeout(timer); timer = null } }

  async function poll(id) {
    try {
      const r = await api.get(`/exports/${id}`)
      const job = r.data
      if (job.status === 'done') {
        stop(); exporting.value = false
        const blob = await api.get(`/exports/${id}/download`, { responseType: 'blob' })
        downloadBlob(blob, job.filename || '导出.xlsx')
        toast.success(`后台导出完成（${job.row_count || 0} 行），已开始下载`)
        return
      }
      if (job.status === 'failed') {
        stop(); exporting.value = false
        toast.error(job.error || '后台导出失败')
        return
      }
      timer = setTimeout(() => poll(id), 1500)
    } catch (e) {
      stop(); exporting.value = false
      toast.error(e?.msg || e?.error || '导出任务查询失败')
    }
  }

  async function startExport(kind, params) {
    if (exporting.value) { toast.warn('已有导出任务进行中，请稍候'); return }
    exporting.value = true
    // 后台导出走 POST，active-dept 范围不会被请求拦截器自动注入到 body，
    // 故在此显式带上当前会话的事业部范围，保证后台重建 queryset 口径一致。
    const body = { ...(params || {}) }
    try {
      const raw = JSON.parse(localStorage.getItem('pk_active_depts') || '[]')
      if (Array.isArray(raw) && raw.length > 0 && !body.depts && !body.dept) {
        body.depts = raw.join(',')
      }
    } catch {}
    try {
      const r = await api.post('/exports', { kind, params: body })
      const job = r.data
      toast.info('已转后台导出，完成后将自动下载（可继续操作）')
      poll(job.id)
    } catch (e) {
      exporting.value = false
      toast.error(e?.msg || e?.error || '创建导出任务失败')
    }
  }

  return { exporting, startExport, stop }
}
