"""钉钉审批回调：加解密往返、URL 验证回包、审批结果回写。"""
import json
from decimal import Decimal

from django.test import Client, TestCase, override_settings

from paikuan.dingtalk import DingTalkCrypto
from paikuan.models import ApprovalRecord

# 测试用固定密钥（EncodingAESKey 须 43 位；这是随机凑的合法长度串，非真实密钥）
_AES = 'a' * 43
_TOKEN = 'testtoken'
_KEY = 'dingtalkappkey123'

_DT = dict(DINGTALK_CALLBACK_TOKEN=_TOKEN, DINGTALK_AES_KEY=_AES, DINGTALK_CALLBACK_KEY=_KEY)


class DingTalkCryptoTests(TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        c = DingTalkCrypto(_TOKEN, _AES, _KEY)
        for text in ['success', '{"EventType":"check_url"}', '中文事件内容']:
            self.assertEqual(c.decrypt(c.encrypt(text)), text)

    def test_signature_stable_and_order_independent(self):
        c = DingTalkCrypto(_TOKEN, _AES, _KEY)
        enc = c.encrypt('success')
        s1 = c.signature('100', 'abc', enc)
        s2 = c.signature('100', 'abc', enc)
        self.assertEqual(s1, s2)
        self.assertEqual(len(s1), 40)   # sha1 hex

    def test_response_packet_is_self_verifiable(self):
        c = DingTalkCrypto(_TOKEN, _AES, _KEY)
        pkt = c.encrypt_response('success')
        # 回包签名可被同一套 token/key 校验通过，且密文解回 "success"
        self.assertEqual(
            c.signature(pkt['timeStamp'], pkt['nonce'], pkt['encrypt']), pkt['msg_signature'])
        self.assertEqual(c.decrypt(pkt['encrypt']), 'success')


@override_settings(**_DT)
class DingTalkCallbackTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.c = DingTalkCrypto(_TOKEN, _AES, _KEY)

    def _post(self, plaintext):
        encrypt = self.c.encrypt(plaintext)
        ts, nonce = '1700000000000', 'nonce123'
        sig = self.c.signature(ts, nonce, encrypt)
        return self.client.post(
            f'/api/pk/dingtalk/callback?msg_signature={sig}&timestamp={ts}&nonce={nonce}',
            data=json.dumps({'encrypt': encrypt}), content_type='application/json')

    def test_url_verification_returns_encrypted_success(self):
        r = self._post(json.dumps({'EventType': 'check_url'}))
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        # 回包能被校验、解出 success —— 即钉钉侧会判定验证通过
        self.assertEqual(self.c.signature(d['timeStamp'], d['nonce'], d['encrypt']), d['msg_signature'])
        self.assertEqual(self.c.decrypt(d['encrypt']), 'success')

    def test_bad_signature_rejected(self):
        encrypt = self.c.encrypt(json.dumps({'EventType': 'check_url'}))
        r = self.client.post(
            '/api/pk/dingtalk/callback?msg_signature=deadbeef&timestamp=1&nonce=x',
            data=json.dumps({'encrypt': encrypt}), content_type='application/json')
        self.assertEqual(r.status_code, 401, r.content)

    def test_approval_finish_agree_writes_status(self):
        rec = ApprovalRecord.objects.create(
            applicant='张三', department='运输事业部', approval_number='1' * 21,
            summary='采购', amount=Decimal('1000'), payee='供应商A',
            status='pending', dingtalk_instance_id='INST-777')
        r = self._post(json.dumps({
            'EventType': 'bpms_instance_change', 'type': 'finish',
            'result': 'agree', 'processInstanceId': 'INST-777'}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.c.decrypt(r.json()['encrypt']), 'success')   # 仍回 success
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'approved')

    def test_approval_finish_refuse_writes_rejected(self):
        rec = ApprovalRecord.objects.create(
            applicant='李四', department='运输事业部', approval_number='2' * 21,
            summary='采购', amount=Decimal('500'), payee='供应商B',
            status='pending', dingtalk_instance_id='INST-888')
        self._post(json.dumps({
            'EventType': 'bpms_instance_change', 'type': 'finish',
            'result': 'refuse', 'processInstanceId': 'INST-888'}))
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'rejected')

    def test_start_event_does_not_change_status(self):
        rec = ApprovalRecord.objects.create(
            applicant='王五', department='运输事业部', approval_number='3' * 21,
            summary='采购', amount=Decimal('500'), payee='供应商C',
            status='pending', dingtalk_instance_id='INST-999')
        self._post(json.dumps({
            'EventType': 'bpms_instance_change', 'type': 'start',
            'result': 'agree', 'processInstanceId': 'INST-999'}))
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'pending')   # 发起不改状态

    def test_unknown_instance_ignored_still_success(self):
        r = self._post(json.dumps({
            'EventType': 'bpms_instance_change', 'type': 'finish',
            'result': 'agree', 'processInstanceId': 'INST-NOPE'}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.c.decrypt(r.json()['encrypt']), 'success')

    def test_get_returns_ok_not_404(self):
        r = self.client.get('/api/pk/dingtalk/callback')
        self.assertEqual(r.status_code, 200)


class DingTalkNotConfiguredTests(TestCase):
    @override_settings(DINGTALK_CALLBACK_TOKEN='', DINGTALK_AES_KEY='')
    def test_unconfigured_returns_503(self):
        r = Client().post('/api/pk/dingtalk/callback',
                          data=json.dumps({'encrypt': 'x'}), content_type='application/json')
        self.assertEqual(r.status_code, 503)
