"""钉钉审批流对接 — 事件订阅回调接收（HTTP 推送模式）。

职责：
1) 通过 URL 验证（钉钉保存回调地址时会推 EventType=check_url，须回加密的 "success"）；
2) 接收审批实例状态变更事件（bpms_instance_change），把钉钉的同意/拒绝结果
   回写到系统的 ApprovalRecord（按 dingtalk_instance_id 关联）。

加解密与企业微信/钉钉同一套方案：AES-256-CBC + PKCS7(block=32)，
明文结构 = 16 随机字节 + 4 字节大端长度 + 正文 + key(企业内部应用=AppKey)。
签名 = sha1(sorted([token, timestamp, nonce, encrypt]))。

安全：token / aes_key / key 仅从环境变量（settings）读取，源码不内置任何密钥。
"""
import base64
import hashlib
import json
import logging
import os
import struct
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

_PKCS7_BLOCK = 32


class DingTalkCrypto:
    """钉钉事件订阅回调加解密。key = 企业内部应用 AppKey（个别后台配置用 CorpId，
    此时通过 DINGTALK_CALLBACK_KEY 覆盖）。"""

    def __init__(self, token, aes_key_b64, key):
        self.token = token or ''
        self.key = key or ''
        # EncodingAESKey 43 位，补 '=' 后 base64 解出 32 字节（AES-256）
        self.aes_key = base64.b64decode((aes_key_b64 or '') + '=')
        self.iv = self.aes_key[:16]

    def signature(self, timestamp, nonce, encrypt):
        arr = sorted([self.token, str(timestamp), str(nonce), encrypt])
        return hashlib.sha1(''.join(arr).encode('utf-8')).hexdigest()

    def _cipher(self):
        return Cipher(algorithms.AES(self.aes_key), modes.CBC(self.iv))

    def decrypt(self, encrypt_b64):
        ct = base64.b64decode(encrypt_b64)
        dec = self._cipher().decryptor()
        plain = dec.update(ct) + dec.finalize()
        pad = plain[-1]
        if pad < 1 or pad > _PKCS7_BLOCK:
            pad = 0
        plain = plain[:len(plain) - pad]
        msg_len = struct.unpack('>I', plain[16:20])[0]
        return plain[20:20 + msg_len].decode('utf-8')

    def encrypt(self, text):
        text_b = text.encode('utf-8')
        raw = os.urandom(16) + struct.pack('>I', len(text_b)) + text_b + self.key.encode('utf-8')
        amount = _PKCS7_BLOCK - (len(raw) % _PKCS7_BLOCK)
        amount = amount or _PKCS7_BLOCK
        raw = raw + bytes([amount]) * amount
        enc = self._cipher().encryptor()
        return base64.b64encode(enc.update(raw) + enc.finalize()).decode('utf-8')

    def encrypt_response(self, text, timestamp=None, nonce=None):
        """把明文（如 "success"）加密成钉钉要求的回包结构。"""
        encrypt = self.encrypt(text)
        timestamp = str(timestamp or int(time.time() * 1000))
        nonce = str(nonce or base64.b16encode(os.urandom(6)).decode('ascii'))
        return {
            'msg_signature': self.signature(timestamp, nonce, encrypt),
            'encrypt': encrypt,
            'timeStamp': timestamp,
            'nonce': nonce,
        }


def _crypto():
    return DingTalkCrypto(
        settings.DINGTALK_CALLBACK_TOKEN,
        settings.DINGTALK_AES_KEY,
        settings.DINGTALK_CALLBACK_KEY,
    )


def _handle_event(event):
    """处理钉钉审批事件（best-effort，绝不因业务异常影响回包"success"）。
    审批实例状态变更 bpms_instance_change：type=finish + result=agree/refuse
    → 回写系统审批状态（按 dingtalk_instance_id 关联；未关联则忽略）。"""
    try:
        event_type = event.get('EventType')
        if event_type != 'bpms_instance_change':
            return
        # finish 才是最终结果；start 只是发起，不动系统状态
        if event.get('type') != 'finish':
            return
        instance_id = event.get('processInstanceId') or ''
        if not instance_id:
            return
        result = event.get('result')          # agree / refuse
        status = {'agree': 'approved', 'refuse': 'rejected'}.get(result)
        if not status:
            return
        from paikuan.models import ApprovalRecord
        rec = ApprovalRecord.objects.filter(
            dingtalk_instance_id=instance_id, deleted_at__isnull=True).first()
        if not rec:
            logger.info('dingtalk event: no ApprovalRecord for instance %s', instance_id)
            return
        if rec.status != status:
            rec.status = status
            rec.save(update_fields=['status'])
            logger.info('dingtalk approval %s → %s (rec #%s)', instance_id, status, rec.id)
    except Exception as ex:   # noqa: BLE001 — 回调必须稳，业务失败只记录
        logger.error('dingtalk event handling failed: %s', ex)


@csrf_exempt
def dingtalk_callback(request):
    """钉钉事件订阅 HTTP 回调入口：/api/pk/dingtalk/callback"""
    if request.method != 'POST':
        # 便于人工/浏览器点开时不误判为坏链接
        return JsonResponse({'ok': True, 'msg': 'dingtalk callback endpoint'}, status=200)
    if not (settings.DINGTALK_CALLBACK_TOKEN and settings.DINGTALK_AES_KEY):
        logger.warning('dingtalk callback hit but not configured (token/aes_key missing)')
        return JsonResponse({'error': '钉钉回调未配置'}, status=503)

    msg_signature = request.GET.get('msg_signature') or request.GET.get('signature') or ''
    timestamp = request.GET.get('timestamp', '')
    nonce = request.GET.get('nonce', '')
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'error': 'bad body'}, status=400)
    encrypt = body.get('encrypt', '')
    if not encrypt:
        return JsonResponse({'error': 'missing encrypt'}, status=400)

    crypto = _crypto()
    if crypto.signature(timestamp, nonce, encrypt) != msg_signature:
        logger.warning('dingtalk callback signature mismatch')
        return JsonResponse({'error': 'signature mismatch'}, status=401)
    try:
        event = json.loads(crypto.decrypt(encrypt))
    except Exception as ex:   # noqa: BLE001
        logger.error('dingtalk callback decrypt failed: %s', ex)
        return JsonResponse({'error': 'decrypt failed'}, status=400)

    # check_url 只需回 success；其余事件先处理业务再回 success
    if event.get('EventType') and event.get('EventType') != 'check_url':
        _handle_event(event)
    # 钉钉要求返回加密后的 "success"（3 秒内）
    return JsonResponse(crypto.encrypt_response('success'))
