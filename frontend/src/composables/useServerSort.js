import { ref } from 'vue'

/**
 * 服务端排序状态机：点同一列循环 升序 → 降序 → 取消。
 * sort.value 形如 ''｜'key'｜'-key'，可直接作为后端 sort 参数下发。
 *
 * @param {Function} onChange 排序变化后的回调（通常是重新拉取首页数据）
 */
export function useServerSort(onChange) {
  const sort = ref('')

  function toggle(key) {
    if (sort.value === key) sort.value = '-' + key
    else if (sort.value === '-' + key) sort.value = ''
    else sort.value = key
    onChange && onChange()
  }

  // 返回当前列方向：'asc'｜'desc'｜''
  function dir(key) {
    if (sort.value === key) return 'asc'
    if (sort.value === '-' + key) return 'desc'
    return ''
  }

  return { sort, toggle, dir }
}
