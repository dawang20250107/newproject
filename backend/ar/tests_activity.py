"""端到端测试：催款工作台 —— ARActivity / ARAttachment / quick-edit /
collection-log 兼容垫片 / 计数器对账命令。

覆盖正常路径 + 权限 + 计数器一致性 + 单一数据源（旧接口与新接口读写同一张
ARActivity 表）。文件上传走临时 MEDIA_ROOT，测试结束自动清理。
"""
import io
import json
import os
import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from ar.models import (ARProject, ARRecord, ARActivity, ARAttachment)
from paikuan.models import PaikuanUser
from paikuan.views import make_token, _invalidate_perm_cache

_TMP_MEDIA = tempfile.mkdtemp(prefix='ar_test_media_')


@override_settings(MEDIA_ROOT=_TMP_MEDIA, X_ACCEL_REDIRECT_BASE='')
class ActivityWorkbenchTests(TestCase):
    dept = '劳务事业部'
    other_dept = '运输事业部'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.admin = self._make_user('13900000901', role='super_admin')
        self.project = self._make_project()
        self.record = self._make_record(self.project)

    def tearDown(self):
        _invalidate_perm_cache()

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _make_user(self, phone, role='operator', departments=None):
        u = PaikuanUser(phone=phone, name=f'U{phone[-3:]}', role=role,
                        job_title='finance_director',
                        departments=departments or [self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456')
        u.save()
        return u

    def _make_project(self, delivery_dept=None):
        return ARProject.objects.create(
            customer_name='Contract A', short_name='Project A',
            delivery_dept=delivery_dept or self.dept, sub_dept='Sub A',
            business_mode='Mode A', customer_level='A级', sales_contact='Sales A',
            project_manager='PM A', has_contract='有', contract_date=date(2026, 1, 1),
            reconciliation_days=10, invoice_wait_days=5, post_invoice_days=15,
            invoice_mode='全额', invoice_type='专票', tax_rate=Decimal('0.0600'))

    def _make_record(self, project):
        return ARRecord.objects.create(
            project=project, operation_year=2026, operation_month=5,
            estimated_amount=Decimal('1000.00'))

    def _auth(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(user)}'}

    def _post(self, url, payload, user):
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json', **self._auth(user))

    def _put(self, url, payload, user):
        return self.client.put(url, data=json.dumps(payload),
                               content_type='application/json', **self._auth(user))

    def _patch(self, url, payload, user):
        return self.client.patch(url, data=json.dumps(payload),
                                 content_type='application/json', **self._auth(user))

    def _record_counts(self):
        r = ARRecord.objects.get(pk=self.record.id)
        return r.activity_count, r.attachment_count

    def _png_bytes(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (40, 30), (200, 100, 50)).save(buf, 'PNG')
        return buf.getvalue()

    # ── ARActivity CRUD ──────────────────────────────────────────────────────
    def test_activity_create_list_edit_delete_and_counter(self):
        rid = self.record.id
        base = f'/api/pk/ar/records/{rid}/activity'

        # create
        resp = self._post(base, {'stage': 'collection', 'act_type': 'call',
                                 'note': '打了催款电话', 'status': 'in_progress',
                                 'contact_person': '王会计'}, self.admin)
        self.assertEqual(resp.status_code, 200, resp.content)
        act = resp.json()['data']
        self.assertEqual(act['stage'], 'collection')
        self.assertTrue(act['can_edit'])
        self.assertEqual(self._record_counts()[0], 1)   # activity_count -> 1

        # list (combined shape)
        lst = self.client.get(base, **self._auth(self.admin)).json()['data']
        self.assertEqual(len(lst['activities']), 1)
        self.assertEqual(lst['attachments'], [])

        # stage filter: a different stage returns empty
        f = self.client.get(base, {'stage': 'invoice'}, **self._auth(self.admin)).json()['data']
        self.assertEqual(f['activities'], [])

        # edit
        up = self._put(f'{base}/{act["id"]}', {'note': '改：已承诺本周回款',
                                               'status': 'resolved'}, self.admin)
        self.assertEqual(up.status_code, 200, up.content)
        self.assertEqual(up.json()['data']['note'], '改：已承诺本周回款')
        self.assertEqual(up.json()['data']['status'], 'resolved')

        # delete -> counter back to 0
        d = self.client.delete(f'{base}/{act["id"]}', **self._auth(self.admin))
        self.assertEqual(d.status_code, 200, d.content)
        self.assertEqual(self._record_counts()[0], 0)
        self.assertFalse(ARActivity.objects.filter(pk=act['id']).exists())

    def test_activity_validation_errors(self):
        base = f'/api/pk/ar/records/{self.record.id}/activity'
        self.assertEqual(self._post(base, {'note': ''}, self.admin).status_code, 400)
        self.assertEqual(self._post(base, {'stage': 'bogus', 'note': 'x'}, self.admin).status_code, 400)
        self.assertEqual(self._post(base, {'act_type': 'bogus', 'note': 'x'}, self.admin).status_code, 400)
        self.assertEqual(self._post(base, {'status': 'bogus', 'note': 'x'}, self.admin).status_code, 400)

    def test_activity_edit_delete_requires_owner(self):
        base = f'/api/pk/ar/records/{self.record.id}/activity'
        # admin creates
        act = self._post(base, {'note': '我的记录'}, self.admin).json()['data']
        # a non-super user in same dept can read but not edit/delete others' entries
        other = self._make_user('13900000902', role='operator')
        self.assertEqual(self._put(f'{base}/{act["id"]}', {'note': 'x'}, other).status_code, 403)
        self.assertEqual(
            self.client.delete(f'{base}/{act["id"]}', **self._auth(other)).status_code, 403)

    def test_activity_cross_dept_access_denied(self):
        other_proj = self._make_project(delivery_dept=self.other_dept)
        other_rec = self._make_record(other_proj)
        user = self._make_user('13900000903', role='operator', departments=[self.dept])
        base = f'/api/pk/ar/records/{other_rec.id}/activity'
        self.assertEqual(self.client.get(base, **self._auth(user)).status_code, 403)
        self.assertEqual(self._post(base, {'note': 'x'}, user).status_code, 403)

    # ── 附件上传 / 下载 / 缩略图 / 删除 ───────────────────────────────────────
    def test_attachment_image_upload_thumb_download_delete(self):
        rid = self.record.id
        url = f'/api/pk/ar/records/{rid}/attachments'
        upload = SimpleUploadedFile('shot.png', self._png_bytes(), content_type='image/png')
        resp = self.client.post(url, {'file': upload, 'stage': 'dunning'}, **self._auth(self.admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        att = resp.json()['data']
        self.assertTrue(att['is_image'])
        self.assertTrue(att['has_thumb'])
        self.assertEqual(self._record_counts()[1], 1)   # attachment_count -> 1

        # physical file exists on disk
        obj = ARAttachment.objects.get(pk=att['id'])
        self.assertTrue(os.path.exists(os.path.join(_TMP_MEDIA, str(obj.file))))
        self.assertTrue(os.path.exists(os.path.join(_TMP_MEDIA, obj.thumb_path)))

        # download (FileResponse path)
        dl = self.client.get(f'{url}/{att["id"]}', **self._auth(self.admin))
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(b''.join(dl.streaming_content), self._png_bytes())

        # thumbnail
        th = self.client.get(f'{url}/{att["id"]}/thumb', **self._auth(self.admin))
        self.assertEqual(th.status_code, 200)
        self.assertEqual(th['Content-Type'], 'image/jpeg')

        # combined list shows it under attachments
        act_list = self.client.get(f'/api/pk/ar/records/{rid}/activity',
                                   **self._auth(self.admin)).json()['data']
        self.assertEqual(len(act_list['attachments']), 1)

        # delete removes file + thumb + decrements counter
        file_abs = os.path.join(_TMP_MEDIA, str(obj.file))
        thumb_abs = os.path.join(_TMP_MEDIA, obj.thumb_path)
        d = self.client.delete(f'{url}/{att["id"]}', **self._auth(self.admin))
        self.assertEqual(d.status_code, 200, d.content)
        self.assertEqual(self._record_counts()[1], 0)
        self.assertFalse(os.path.exists(file_abs))
        self.assertFalse(os.path.exists(thumb_abs))

    def test_attachment_non_image_upload(self):
        url = f'/api/pk/ar/records/{self.record.id}/attachments'
        pdf = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        resp = self.client.post(url, {'file': pdf}, **self._auth(self.admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        att = resp.json()['data']
        self.assertFalse(att['is_image'])
        self.assertFalse(att['has_thumb'])
        self.assertIsNone(att['thumb_url'])

    def test_attachment_rejects_bad_extension(self):
        url = f'/api/pk/ar/records/{self.record.id}/attachments'
        bad = SimpleUploadedFile('x.exe', b'MZ...', content_type='application/octet-stream')
        resp = self.client.post(url, {'file': bad}, **self._auth(self.admin))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._record_counts()[1], 0)

    def test_attachment_rejects_oversize(self):
        from ar.views import activity as activity_views
        url = f'/api/pk/ar/records/{self.record.id}/attachments'
        orig = activity_views._MAX_BYTES
        activity_views._MAX_BYTES = 10   # 10 bytes ceiling for this test
        try:
            big = SimpleUploadedFile('big.txt', b'x' * 50, content_type='text/plain')
            resp = self.client.post(url, {'file': big}, **self._auth(self.admin))
            self.assertEqual(resp.status_code, 400)
        finally:
            activity_views._MAX_BYTES = orig
        self.assertEqual(self._record_counts()[1], 0)

    def test_attachment_delete_requires_owner(self):
        url = f'/api/pk/ar/records/{self.record.id}/attachments'
        att = self.client.post(url, {'file': SimpleUploadedFile('d.pdf', b'%PDF')},
                               **self._auth(self.admin)).json()['data']
        other = self._make_user('13900000904', role='operator')
        d = self.client.delete(f'{url}/{att["id"]}', **self._auth(other))
        self.assertEqual(d.status_code, 403)
        self.assertEqual(self._record_counts()[1], 1)   # unchanged

    # ── 行内快速编辑 ─────────────────────────────────────────────────────────
    def test_quick_edit_persists_without_recompute(self):
        url = f'/api/pk/ar/records/{self.record.id}/quick-edit'
        resp = self._patch(url, {'collector': '李催收',
                                 'target_collection_date': '2026-07-01',
                                 'notes': '客户答应月底付'}, self.admin)
        self.assertEqual(resp.status_code, 200, resp.content)
        rec = ARRecord.objects.get(pk=self.record.id)
        self.assertEqual(rec.collector, '李催收')
        self.assertEqual(str(rec.target_collection_date), '2026-07-01')
        self.assertEqual(rec.notes, '客户答应月底付')

    def test_quick_edit_method_and_empty_guard(self):
        url = f'/api/pk/ar/records/{self.record.id}/quick-edit'
        # wrong method
        self.assertEqual(self._post(url, {'collector': 'x'}, self.admin).status_code, 405)
        # empty payload -> nothing to update
        self.assertEqual(self._patch(url, {}, self.admin).status_code, 400)

    # ── collection-log 兼容垫片 == 单一数据源 ────────────────────────────────
    def test_collection_log_shim_writes_to_activity(self):
        rid = self.record.id
        log_url = f'/api/pk/ar/records/{rid}/collection-logs'
        # POST via old endpoint
        resp = self._post(log_url, {'log_type': 'call', 'note': '老接口写入',
                                    'status': 'pending'}, self.admin)
        self.assertEqual(resp.status_code, 200, resp.content)
        log = resp.json()['data']
        self.assertEqual(log['log_type'], 'call')           # legacy shape preserved
        # it lands in ARActivity as a dunning-stage row
        a = ARActivity.objects.get(pk=log['id'])
        self.assertEqual(a.stage, 'dunning')
        self.assertEqual(a.note, '老接口写入')
        # counter maintained by the shim too
        self.assertEqual(self._record_counts()[0], 1)

        # the new /activity endpoint sees the same row (single source of truth)
        acts = self.client.get(f'/api/pk/ar/records/{rid}/activity',
                               **self._auth(self.admin)).json()['data']['activities']
        self.assertEqual([x['id'] for x in acts], [log['id']])

        # old GET also returns it in legacy shape
        items = self.client.get(log_url, **self._auth(self.admin)).json()['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['note'], '老接口写入')

        # DELETE via old endpoint decrements the counter
        d = self.client.delete(f'{log_url}/{log["id"]}', **self._auth(self.admin))
        self.assertEqual(d.status_code, 200, d.content)
        self.assertEqual(self._record_counts()[0], 0)

    def test_new_dunning_activity_visible_via_old_log_endpoint(self):
        """反向：新面板建的 dunning 动态，老 /collection-logs 也能读到。"""
        rid = self.record.id
        self._post(f'/api/pk/ar/records/{rid}/activity',
                   {'stage': 'dunning', 'act_type': 'note', 'note': '新面板备注'}, self.admin)
        items = self.client.get(f'/api/pk/ar/records/{rid}/collection-logs',
                                **self._auth(self.admin)).json()['data']['items']
        self.assertEqual(len(items), 1)
        # act_type 'note' 不在旧 log_type 取值里 → 归并为 other（仍合法）
        self.assertEqual(items[0]['log_type'], 'other')
        self.assertEqual(items[0]['note'], '新面板备注')

    # ── 计数器对账命令 ───────────────────────────────────────────────────────
    def test_recompute_counters_command_fixes_drift(self):
        rid = self.record.id
        base = f'/api/pk/ar/records/{rid}/activity'
        self._post(base, {'note': 'a'}, self.admin)
        self._post(base, {'note': 'b'}, self.admin)
        # tamper the stored counter to simulate drift
        ARRecord.objects.filter(pk=rid).update(activity_count=99, attachment_count=7)

        out = io.StringIO()
        call_command('recompute_ar_counters', stdout=out)
        rec = ARRecord.objects.get(pk=rid)
        self.assertEqual(rec.activity_count, 2)   # real count
        self.assertEqual(rec.attachment_count, 0)
        self.assertIn('已修复', out.getvalue())

    def test_recompute_counters_dry_run_does_not_write(self):
        rid = self.record.id
        ARRecord.objects.filter(pk=rid).update(activity_count=42)
        call_command('recompute_ar_counters', '--dry-run', stdout=io.StringIO())
        self.assertEqual(ARRecord.objects.get(pk=rid).activity_count, 42)  # untouched

    # ── 操作审计轨迹 ──────────────────────────────────────────────────────────
    def test_audit_trail_collects_record_writes(self):
        rid = self.record.id
        # 三类写操作：改记录字段、加跟进、登记回款（中间件自动写 AuditLog）
        self._put(f'/api/pk/ar/records/{rid}',
                  {'reconciliation_date': '2024-02-01'}, self.admin)
        self._post(f'/api/pk/ar/records/{rid}/activity',
                   {'note': '已电话联系', 'stage': 'dunning'}, self.admin)

        res = self.client.get(f'/api/pk/ar/records/{rid}/audit', **self._auth(self.admin))
        self.assertEqual(res.status_code, 200)
        events = res.json()['data']
        actions = [e['action'] for e in events]
        self.assertTrue(any('对账日期' in a for a in actions))   # 字段编辑被翻译
        self.assertIn('新增跟进', actions)
        # 每条事件都带操作人与时间
        self.assertTrue(all(e['user_name'] and e['created_at'] for e in events))

    def test_audit_trail_does_not_leak_other_record(self):
        """id 前缀不应误配：record 1 的轨迹不含 record 11 的写操作。"""
        other = self._make_record(self.project)   # 不同 id
        self._put(f'/api/pk/ar/records/{other.id}',
                  {'collector': '他人记录'}, self.admin)
        res = self.client.get(f'/api/pk/ar/records/{self.record.id}/audit',
                              **self._auth(self.admin))
        details = ' '.join(e.get('detail', '') for e in res.json()['data'])
        self.assertNotIn('他人记录', details)

    def test_audit_trail_dept_access_enforced(self):
        outsider = self._make_user('13900000940', role='operator',
                                   departments=[self.other_dept])
        res = self.client.get(f'/api/pk/ar/records/{self.record.id}/audit',
                              **self._auth(outsider))
        self.assertEqual(res.status_code, 403)
