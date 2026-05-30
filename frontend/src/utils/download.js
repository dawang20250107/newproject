// 统一的浏览器文件下载。各页面原本各自实现一遍 createObjectURL→a.click→revoke，
// 这里收敛成一份，确保始终 revokeObjectURL（避免 blob 句柄泄漏）。

/**
 * 触发浏览器下载一个 Blob。
 * @param {Blob} blob 文件内容
 * @param {string} filename 下载文件名
 */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
