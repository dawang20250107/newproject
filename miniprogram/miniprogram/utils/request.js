const app = getApp ? getApp() : null

function _app() { return app || getApp() }

function _doRequest(path, options, token) {
  const a = _app()
  return new Promise((resolve, reject) => {
    wx.request({
      url: a.globalData.apiBase + path,
      method: options.method || 'GET',
      data: options.data,
      header: Object.assign(
        { 'Content-Type': 'application/json' },
        token ? { 'Authorization': 'Bearer ' + token } : {},
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
      // token失效，重新登录后重试一次
      token = await a._silentLogin(true)
      return _doRequest(path, options, token)
    }
    throw err
  }
}

module.exports = { request }
