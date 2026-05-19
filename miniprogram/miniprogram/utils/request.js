const config = require('./config.js');

/**
 * 封装 wx.request，统一处理错误和响应
 * @param {string} path - API 路径（相对地址）
 * @param {object} data - 请求参数
 * @param {string} method - 请求方法，默认 GET
 * @param {object} opts - 额外选项
 * @param {boolean} opts.silent - 是否静默请求（不显示 loading/toast）
 */
function request(path, data = {}, method = 'GET', opts = {}) {
  const url = config.API_BASE + path;
  const silent = opts.silent || false;

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      data,
      method,
      header: {
        'Content-Type': 'application/json',
      },
      success(res) {
        if (res.statusCode === 200 && res.data) {
          if (res.data.code === 0) {
            resolve(res.data.data);
          } else if (res.data.code !== undefined) {
            if (!silent) wx.showToast({ title: res.data.error || '请求失败', icon: 'none' });
            reject(new Error(res.data.error || 'API Error'));
          } else {
            // 后端直接返回数组/对象（兼容 DRF 列表接口）
            resolve(res.data);
          }
        } else if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
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

/**
 * GET 请求（静默模式，不自动 showLoading）
 */
function get(path, data, opts) {
  return request(path, data, 'GET', opts || {});
}

/**
 * POST 请求
 */
function post(path, data, opts) {
  return request(path, data, 'POST', opts || {});
}

module.exports = {
  request,
  get,
  post,
  API_BASE: config.API_BASE,
};
