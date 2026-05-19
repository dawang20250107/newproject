const config = require('./config.js');

function request(path, data = {}, method = 'GET', opts = {}) {
  const url = config.API_BASE + path;
  const silent = opts.silent || false;
  const token = wx.getStorageSync('kxt_token');

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      data,
      method,
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      success(res) {
        if (res.statusCode === 401) {
          wx.removeStorageSync('kxt_token');
          // Silent re-login for miniprogram
          const app = getApp();
          if (app && app._silentLogin) {
            app._silentLogin().then(() => {
              // Retry once after re-login
              request(path, data, method, { ...opts, _retry: true }).then(resolve).catch(reject);
            }).catch(reject);
          } else {
            reject(new Error('未登录'));
          }
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          if (res.data && res.data.code === 0) {
            resolve(res.data.data);
          } else if (res.data && res.data.code !== undefined) {
            if (!silent) wx.showToast({ title: res.data.error || '请求失败', icon: 'none' });
            reject(new Error(res.data.error || 'API Error'));
          } else {
            resolve(res.data);
          }
        } else {
          if (!silent) wx.showToast({ title: `请求失败 (${res.statusCode})`, icon: 'none' });
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      },
      fail(err) {
        if (!silent) wx.showToast({ title: '网络异常，请检查网络', icon: 'none' });
        reject(err);
      },
    });
  });
}

function get(path, data, opts) { return request(path, data, 'GET', opts || {}); }
function post(path, data, opts) { return request(path, data, 'POST', opts || {}); }
function put(path, data, opts) { return request(path, data, 'PUT', opts || {}); }

module.exports = { request, get, post, put, API_BASE: config.API_BASE };
