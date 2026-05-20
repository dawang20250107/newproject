function _app() { return getApp() }

function _doRequest(path, options, token) {
  const a = _app()
  return new Promise((resolve, reject) => {
    wx.request({
      url: a.globalData.apiBase + path,
      method: options.method || 'GET',
      data: options.data,
      header: Object.assign(
        { 'Content-Type': 'application/json' },
        token ? { 'Authorization': 'Bearer ' + token } : {}
      ),
      success: (r) => {
        if (r.statusCode >= 200 && r.statusCode < 300) resolve(r.data)
        else reject({ statusCode: r.statusCode, data: r.data })
      },
      fail: reject,
    })
  })
}

async function request(path, options = {}) {
  const a = _app()
  let token = a.globalData.token
  try {
    return await _doRequest(path, options, token)
  } catch (err) {
    if (err && err.statusCode === 401) {
      // 清除过期 token，强制重新走 wx.login 换新 token
      a.globalData.token = ''
      wx.removeStorageSync('kxt_token')
      token = await a._silentLogin()
      return _doRequest(path, options, token)
    }
    throw err
  }
}

module.exports = { request }
