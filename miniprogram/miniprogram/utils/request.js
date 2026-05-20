function _app() { return getApp() }

function _doRequest(path, options, token) {
  const cloudEnv = _app().globalData.cloudEnv
  return new Promise((resolve, reject) => {
    wx.cloud.callContainer({
      config: { env: cloudEnv },
      path,
      method: options.method || 'GET',
      header: Object.assign(
        { 'content-type': 'application/json' },
        token ? { 'Authorization': 'Bearer ' + token } : {}
      ),
      data: options.data,
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
      // token 失效，重新登录后重试一次
      token = await a._silentLogin()
      return _doRequest(path, options, token)
    }
    throw err
  }
}

module.exports = { request }
