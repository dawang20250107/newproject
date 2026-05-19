/**
 * KXT 微信小程序 代码上传脚本
 * 使用方法：node upload.js
 *
 * 首次使用前，请确保：
 *   - 已在微信公众平台 (mp.weixin.qq.com) 生成并下载私钥文件
 *   - 私钥路径已在下方 PRIVATE_KEY_PATH 中配置
 */

const path = require('path');
const fs = require('fs');

// ─── 修复 Node.js v25 兼容性问题 ──────────────────────────
// miniprogram-ci 使用 util.promisify 处理 request 库，
// Node v25 的 promisify 内部实现变更导致 proxy 错误
const origPromisify = require('util').promisify;
require('util').promisify = function(fn) {
  try {
    return origPromisify(fn);
  } catch (e) {
    // 降级：手动包装为 Promise
    return function(...args) {
      return new Promise((resolve, reject) => {
        fn(...args, (err, ...results) => {
          if (err) reject(err);
          else resolve(results.length > 1 ? results : results[0]);
        });
      });
    };
  }
};

const ci = require('miniprogram-ci');

// ─── 配置 ───────────────────────────────────────────────────
const APPID = 'wx67248c26cfe8f21b';
const PROJECT_PATH = __dirname;
const MINIPROGRAM_ROOT = 'miniprogram';
const PRIVATE_KEY_PATH = 'D:\\edge下载\\private.wx67248c26cfe8f21b (1).key';
const VERSION = '2.0.0';
const DESC = '修复自动同步首次触发延迟问题';

// ─── 验证私钥文件 ───────────────────────────────────────────
if (!fs.existsSync(PRIVATE_KEY_PATH)) {
  console.error(`❌ 私钥文件不存在: ${PRIVATE_KEY_PATH}`);
  console.error('   请从微信公众平台 (mp.weixin.qq.com) → 开发 → 开发管理 → 开发设置');
  console.error('   下载小程序代码上传密钥后，修改脚本中的 PRIVATE_KEY_PATH');
  process.exit(1);
}

// ─── 执行上传 ───────────────────────────────────────────────
(async () => {
  try {
    console.log('📦 正在创建上传项目...');

    const project = new ci.Project({
      appid: APPID,
      type: 'miniProgram',
      projectPath: PROJECT_PATH,
      privateKeyPath: PRIVATE_KEY_PATH,
      ignores: ['node_modules/**/*'],
    });

    console.log(`📤 正在上传到微信... (版本: ${VERSION})`);

    const result = await ci.upload({
      project,
      version: VERSION,
      desc: DESC,
      setting: {
        es6: true,
        es7: true,
        minify: true,
        autoPrefixWXSS: true,
        ignoreUploadUnusedFiles: true,
      },
      onProgressUpdate: (info) => {
        if (info.status === 'uploading') {
          console.log(`  ⏫ 上传进度: ${info.uploading || 0}%`);
        }
      },
    });

    console.log(`✅ 上传成功!`);
    console.log(`   版本号: v${VERSION}`);
    console.log(`   更新说明: ${DESC}`);
  } catch (err) {
    console.error('❌ 上传失败:', err.message || err);
    if (err.message?.includes('privateKey')) {
      console.error('   私钥文件可能无效，请重新在微信公众平台生成');
    }
    process.exit(1);
  }
})();
