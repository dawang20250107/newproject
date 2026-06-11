import io
import json
import logging
import datetime
import functools
import re
import threading
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, IntegrityError
from django.db.models import F, Q, Sum, Count, Case, When, ExpressionWrapper, Value, OuterRef, Subquery
from django.db.models import DecimalField as DjDecimalField
from django.db.models.functions import Coalesce
from django.conf import settings
from django.utils import timezone
import jwt

from paikuan.models import PaikuanUser, Payment, PaymentInstallment, JobPermission, ApprovalRecord, PaymentChangeLog

logger = logging.getLogger('paikuan')

DEPARTMENTS = [
    '集团总部', '劳务事业部', '运输事业部', '自营事业部',
    '阔展事业部', '多式联运事业部', '供应链事业部',
]
VALID_DEPARTMENTS = set(DEPARTMENTS)

# Job titles double as the permission "roles" configured by super_admin.
JOB_TITLES = {
    'finance_director': '财务总监',
    'finance_bp': '财务BP',
    'chief_cashier': '总出纳',
    'cashier': '出纳',
    'general_manager': '总经理',
    'gm_assistant': '总经理助理',
    'settlement_accountant': '结算会计',
    'sales_bp': '销售BP',
}

# ── permission model ────────────────────────────────────────────────────────────
# Payment fields that can be individually permission-controlled. Each logical
# field maps to one or more columns in the serialized payment dict.
PAYMENT_FIELD_DEFS = [
    {'key': 'department',      'label': '部门',         'cols': ['department']},
    {'key': 'applicant',       'label': '申请人',        'cols': ['applicant']},
    {'key': 'approval_number', 'label': '审批单号',      'cols': ['approval_number']},
    {'key': 'project_desc',    'label': '付款事项',      'cols': ['project_desc']},
    {'key': 'payee',           'label': '收款方',        'cols': ['payee']},
    {'key': 'total_amount',    'label': '计划总金额',    'cols': ['total_amount']},
    {'key': 'planned_date',    'label': '计划付款日期',  'cols': ['planned_date']},
    {'key': 'installments',    'label': '付款明细',     'cols': ['installments', 'total_paid', 'remaining', 'status']},
    {'key': 'notes',            'label': '备注',          'cols': ['notes']},
    {'key': 'plan_adjustment', 'label': '计划调整金额',   'cols': ['plan_adjustment']},
]
FIELD_KEYS = [f['key'] for f in PAYMENT_FIELD_DEFS]
PAGE_KEYS = [
    'dashboard', 'payments', 'approval_records', 'stats',
    'ar_projects', 'ar_records', 'ar_advance', 'ar_analytics', 'ar_cashflow', 'ar_budget',
    'caiwu_report', 'caiwu_data', 'caiwu_charts', 'caiwu_metrics', 'caiwu_cockpit',
]

# Caiwu report/chart element permission keys (mirrored from caiwu.views.PERM_FIELD_DEFS)
CAIWU_FIELD_DEFS = [
    {'key': 'report_l1',       'label': '一级科目报表'},
    {'key': 'report_l2',       'label': '二级项目部明细'},
    {'key': 'report_l3',       'label': '三级科目明细'},
    {'key': 'amount',          'label': '金额数据'},
    {'key': 'chart_trend',     'label': '走势折线图'},
    {'key': 'chart_waterfall', 'label': '因素瀑布图'},
    {'key': 'export',          'label': '导出 Excel'},
]
CAIWU_FIELD_KEYS = [f['key'] for f in CAIWU_FIELD_DEFS]

# 仅允许这些职务对审批单直接置为 approved/rejected；其余职务（操作员/出纳/结算会计等）
# 只能创建 pending、或取消自己的申请。super_admin 永远豁免此限制。
APPROVER_JOBS = {'finance_director', 'finance_bp', 'general_manager', 'gm_assistant'}


def is_approver(request):
    if getattr(request, 'pk_role', None) == 'super_admin':
        return True
    return getattr(request, 'pk_job', None) in APPROVER_JOBS

# ── AR field-level permission defs ───────────────────────────────────────────
# Per-field show/hide control for the AR module. Keys are namespaced (p_ for
# project台账 fields, r_ for 应收明细 fields) so project/record fields never
# collide. `cols` lists the serialized dict keys masked when the field is hidden.
# Defined here (not in ar/views.py) so the permission system has no dependency
# on the ar app, avoiding a circular import (ar imports paikuan, not vice versa).
AR_PROJECT_FIELD_DEFS = [
    {'key': 'p_contract_name',  'label': '客户名称',   'group': 'project', 'cols': ['customer_name']},
    {'key': 'p_short_name',     'label': '项目简称',   'group': 'project', 'cols': ['short_name']},
    {'key': 'p_delivery_dept',  'label': '交付部门',   'group': 'project', 'cols': ['delivery_dept']},
    {'key': 'p_sub_dept',       'label': '二级部门',   'group': 'project', 'cols': ['sub_dept']},
    {'key': 'p_business_mode',  'label': '业务模式',   'group': 'project', 'cols': ['business_mode']},
    {'key': 'p_customer_level', 'label': '客户等级',   'group': 'project', 'cols': ['customer_level']},
    {'key': 'p_sales_contact',  'label': '销售对接人', 'group': 'project', 'cols': ['sales_contact']},
    {'key': 'p_project_manager','label': '项目负责人', 'group': 'project', 'cols': ['project_manager']},
    {'key': 'p_has_contract',   'label': '有无合同',   'group': 'project', 'cols': ['has_contract']},
    {'key': 'p_contract_date',  'label': '签订日期',   'group': 'project', 'cols': ['contract_date']},
    {'key': 'p_account_period', 'label': '账期配置',   'group': 'project',
        'cols': ['reconciliation_days', 'invoice_wait_days', 'post_invoice_days', 'total_days']},
    {'key': 'p_invoice_config', 'label': '开票配置(模式/类型/税率)', 'group': 'project',
        'cols': ['invoice_mode', 'invoice_type', 'tax_rate']},
    {'key': 'p_notes',          'label': '项目备注',   'group': 'project', 'cols': ['notes']},
]
AR_RECORD_FIELD_DEFS = [
    {'key': 'r_estimated_amount',      'label': '预估上账金额', 'group': 'record', 'cols': ['estimated_amount']},
    {'key': 'r_actual_invoice_amount', 'label': '实际开票金额', 'group': 'record', 'cols': ['actual_invoice_amount']},
    {'key': 'r_tax_amount',            'label': '税额',         'group': 'record', 'cols': ['tax_amount']},
    {'key': 'r_invoice_date',          'label': '开票日期',     'group': 'record', 'cols': ['invoice_date']},
    {'key': 'r_account_diff',          'label': '账实差额',     'group': 'record', 'cols': ['account_diff_adjustment']},
    {'key': 'r_outstanding',           'label': '未回款金额',   'group': 'record', 'cols': ['outstanding_amount']},
    {'key': 'r_due_date',              'label': '应收日期/逾期', 'group': 'record',
        'cols': ['due_date', 'is_overdue', 'overdue_days']},
    {'key': 'r_reconciliation',        'label': '对账信息',     'group': 'record',
        'cols': ['reconciliation_date', 'reconciliation_status']},
    {'key': 'r_invoice_status',        'label': '开票状态',     'group': 'record', 'cols': ['invoice_status']},
    {'key': 'r_payments',              'label': '回款记录',     'group': 'record', 'cols': ['payments']},
    {'key': 'r_notes',                 'label': '明细备注',     'group': 'record', 'cols': ['notes']},
]
# 预收预付字段级权限（adv_ 前缀）。cols 为隐藏时遮蔽的序列化 key。
AR_ADVANCE_FIELD_DEFS = [
    {'key': 'adv_counterparty',  'label': '往来单位',     'group': 'advance', 'cols': ['counterparty']},
    {'key': 'adv_amount',        'label': '预收/预付金额', 'group': 'advance', 'cols': ['advance_amount']},
    {'key': 'adv_writeoff',      'label': '核销信息',     'group': 'advance',
        'cols': ['written_off_amount', 'balance_amount', 'writeoff_status', 'writeoffs']},
    {'key': 'adv_expected_date', 'label': '预计核销/账龄', 'group': 'advance',
        'cols': ['expected_writeoff_date', 'pending_days', 'is_overdue', 'overdue_days']},
    {'key': 'adv_notes',         'label': '预收预付备注',  'group': 'advance', 'cols': ['notes']},
]
AR_FIELD_DEFS = AR_PROJECT_FIELD_DEFS + AR_RECORD_FIELD_DEFS + AR_ADVANCE_FIELD_DEFS
AR_FIELD_KEYS = [f['key'] for f in AR_FIELD_DEFS]

# Ordered columns for Excel template / import / export.
# (perm_field_key, excel_header, db_column)
EXCEL_COLUMN_MAP = [
    ('department',      '部门',               'department'),
    ('applicant',       '申请人',             'applicant'),
    ('approval_number', '审批单号',            'approval_number'),
    ('project_desc',    '项目编号',            'project_no'),
    ('project_desc',    '付款事项',            'project_desc'),
    ('payee',           '收款方',              'payee'),
    ('total_amount',    '计划总金额(元)',       'total_amount'),
    ('planned_date',    '计划付款日期',         'planned_date'),
    # installment columns are generated dynamically (see _visible_excel_cols)
    ('notes',           '备注',                'notes'),
    ('plan_adjustment', '计划调整金额(元)',     'plan_adjustment'),
]
_EXCEL_HEADER_TO_COL = {h: c for _, h, c in EXCEL_COLUMN_MAP}
_EXCEL_DATE_COLS = {'planned_date'}
# Default number of installment slots in the import template.
TEMPLATE_INSTALLMENT_SLOTS = 6

# Example row in the template carries this marker in 部门 so import skips it
# even when the user forgets to delete it.
EXAMPLE_ROW_MARKER = '示例-导入前请删除此行'


def _normalize_date(s):
    """Best-effort normalize a user-typed date string to ISO YYYY-MM-DD."""
    s = (str(s) or '').strip()
    if not s:
        return None
    s = s.replace('/', '-').replace('.', '-').replace('年', '-').replace('月', '-').replace('日', '')
    parts = [p for p in s.split('-') if p != '']
    try:
        if len(parts) >= 3:
            return f'{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}'
    except ValueError:
        pass
    return s  # leave as-is; downstream save will reject if truly invalid


def _all_fields(value):
    return {k: value for k in FIELD_KEYS}


def _all_ar_fields(value):
    return {k: value for k in AR_FIELD_KEYS}


def _all_caiwu_fields(value):
    return {k: value for k in CAIWU_FIELD_KEYS}


def default_job_config(job):
    """Sensible starting permissions for each job title; super_admin can override."""
    # Non-caiwu pages True for most roles; caiwu pages default to off
    _non_cw_pages = {k: True for k in PAGE_KEYS if not k.startswith('caiwu_')}
    pages_all = {**_non_cw_pages, 'caiwu_report': False, 'caiwu_data': False, 'caiwu_charts': False,
                 'caiwu_metrics': False, 'caiwu_cockpit': False}
    ar_pages_all = {k: True for k in ('ar_projects', 'ar_records', 'ar_advance', 'ar_analytics', 'ar_cashflow', 'ar_budget')}
    ar_pages_cashier = {k: (k in ('ar_records', 'ar_advance', 'ar_cashflow', 'ar_budget')) for k in ar_pages_all}
    # Reusable caiwu capability blocks
    _cw_full = {
        'caiwu_view': _all_caiwu_fields(True),
        'caiwu_upload': True, 'caiwu_publish': True, 'caiwu_delete': True,
    }
    _cw_upload_no_del = {
        'caiwu_view': _all_caiwu_fields(True),
        'caiwu_upload': True, 'caiwu_publish': True, 'caiwu_delete': False,
    }
    _cw_readonly = {
        'caiwu_view': _all_caiwu_fields(True),
        'caiwu_upload': False, 'caiwu_publish': False, 'caiwu_delete': False,
    }
    if job == 'finance_director':
        pages = {**pages_all, 'caiwu_report': True, 'caiwu_data': True, 'caiwu_charts': True,
                 'caiwu_metrics': True, 'caiwu_cockpit': True}
        return {'pages': pages, 'view': _all_fields(True),
                'edit': _all_fields(True), 'ar_view': _all_ar_fields(True),
                'can_create': True, 'can_delete': True, 'ar_shared_only': False,
                **_cw_full}
    if job == 'finance_bp':
        pages = {**pages_all, 'caiwu_report': True, 'caiwu_data': True, 'caiwu_charts': True,
                 'caiwu_metrics': True, 'caiwu_cockpit': True}
        return {'pages': pages, 'view': _all_fields(True),
                'edit': _all_fields(True), 'ar_view': _all_ar_fields(True),
                'can_create': True, 'can_delete': False, 'ar_shared_only': False,
                **_cw_upload_no_del}
    if job == 'chief_cashier':
        edit = {k: (k in ('installments',)) for k in FIELD_KEYS}
        # 总出纳默认看不到税额
        ar_view = {**_all_ar_fields(True), 'r_tax_amount': False}
        return {'pages': {**pages_all, **ar_pages_all}, 'view': _all_fields(True),
                'edit': edit, 'ar_view': ar_view,
                'can_create': True, 'can_delete': False, 'ar_shared_only': False,
                **_cw_readonly}
    if job == 'cashier':
        edit = {k: (k in ('installments',)) for k in FIELD_KEYS}
        base_pages = {'dashboard': True, 'payments': True, 'approval_records': True, 'stats': False}
        # 出纳默认看不到税额与账实差额
        ar_view = {**_all_ar_fields(True), 'r_tax_amount': False, 'r_account_diff': False}
        return {'pages': {**base_pages, **ar_pages_cashier},
                'view': _all_fields(True), 'edit': edit, 'ar_view': ar_view,
                'can_create': False, 'can_delete': False, 'ar_shared_only': False,
                **_cw_readonly}
    if job == 'general_manager':
        # 总经理：全量查看，无编辑/创建；财务分析只读
        pages = {**pages_all, 'caiwu_report': True, 'caiwu_data': False, 'caiwu_charts': True,
                 'caiwu_metrics': True, 'caiwu_cockpit': True}
        return {'pages': pages, 'view': _all_fields(True),
                'edit': _all_fields(False), 'ar_view': _all_ar_fields(True),
                'can_create': False, 'can_delete': False, 'ar_shared_only': False,
                **_cw_readonly}
    if job == 'gm_assistant':
        # 总经理助理：全量查看 + 可新增（协助登记），不可删除
        return {'pages': pages_all, 'view': _all_fields(True),
                'edit': _all_fields(True), 'ar_view': _all_ar_fields(True),
                'can_create': True, 'can_delete': False, 'ar_shared_only': False,
                **_cw_readonly}
    if job == 'settlement_accountant':
        # 结算会计：聚焦应收/对账/开票，可编辑应收主数据；付款条数据只读
        edit = {k: False for k in FIELD_KEYS}
        return {'pages': pages_all, 'view': _all_fields(True),
                'edit': edit, 'ar_view': _all_ar_fields(True),
                'can_create': False, 'can_delete': False, 'ar_can_create': True,
                'ar_shared_only': False,
                **_cw_readonly}
    if job == 'sales_bp':
        # 销售BP：仅可见共享业务，AR 只读，无付款操作
        ar_pages = {k: (k in ('ar_projects', 'ar_records')) for k in _non_cw_pages}
        pages = {**{k: False for k in _non_cw_pages}, **ar_pages,
                 'dashboard': True, 'caiwu_report': False, 'caiwu_data': False, 'caiwu_charts': False}
        return {'pages': pages, 'view': _all_fields(False),
                'edit': _all_fields(False), 'ar_view': _all_ar_fields(True),
                'can_create': False, 'can_delete': False, 'ar_shared_only': True,
                **_cw_readonly}
    # Unknown / no job title → read-only minimum, no caiwu access.
    return {'pages': pages_all, 'view': _all_fields(True),
            'edit': _all_fields(False), 'ar_view': _all_ar_fields(True),
            'can_create': False, 'can_delete': False, 'ar_shared_only': False,
            **_cw_readonly}


_perm_cache: dict = {}
_perm_cache_lock = threading.Lock()
# 进程内缓存带短 TTL：权限修改在多 worker 部署下，未命中保存请求的 worker 也能在
# 数秒内自愈（_invalidate_perm_cache 只清当前进程，跨进程靠 TTL 兜底），避免"刚授权
# 仍提示无权限"。读多写少，TTL 期内仍走缓存不增加 DB 压力。
_PERM_CACHE_TTL = 5.0  # seconds


def _invalidate_perm_cache(job=None):
    with _perm_cache_lock:
        if job:
            _perm_cache.pop(job, None)
        else:
            _perm_cache.clear()


def get_job_perms(job):
    """Effective config for a job title = defaults merged with stored overrides.
    Results are cached per-process to avoid repeated DB lookups."""
    now = time.monotonic()
    with _perm_cache_lock:
        ent = _perm_cache.get(job)
        if ent and ent[0] > now:
            return ent[1]
    base = default_job_config(job)
    try:
        rp = JobPermission.objects.filter(job_title=job).first()
    except Exception:
        # paikuan_job_permissions table may not exist yet (migration pending).
        logger.warning('get_job_perms: DB unavailable for %s, using defaults', job)
        return base
    if not (rp and rp.config):
        result = dict(base)
        # 能力位规范化：保证返回值始终带 ar_can_create（多数职务基线无此键 → False），
        # 让权限配置页统一可读可改，避免 undefined 造成误判。
        result.setdefault('ar_can_create', base.get('ar_can_create', False))
    else:
        cfg = rp.config
        view = dict(base['view']);  view.update(cfg.get('view', {}))
        edit = dict(base['edit']);  edit.update(cfg.get('edit', {}))
        pages = dict(base['pages']); pages.update(cfg.get('pages', {}))
        ar_view = dict(base.get('ar_view', _all_ar_fields(True)))
        ar_view.update(cfg.get('ar_view', {}))
        caiwu_view = dict(base.get('caiwu_view', _all_caiwu_fields(True)))
        caiwu_view.update(cfg.get('caiwu_view', {}))
        result = {
            'pages': pages, 'view': view, 'edit': edit, 'ar_view': ar_view,
            'can_create': bool(cfg.get('can_create', base['can_create'])),
            'can_delete': bool(cfg.get('can_delete', base['can_delete'])),
            # 应收专属写权限（结算会计等）：必须在合并时保留，否则一旦超管在权限
            # 配置页对该职务做任何自定义覆盖，ar_can_create 会丢失 → 写入再次被拒。
            'ar_can_create': bool(cfg.get('ar_can_create', base.get('ar_can_create', False))),
            'ar_shared_only': bool(cfg.get('ar_shared_only', base.get('ar_shared_only', False))),
            'caiwu_view': caiwu_view,
            'caiwu_upload':  bool(cfg.get('caiwu_upload',  base.get('caiwu_upload', False))),
            'caiwu_publish': bool(cfg.get('caiwu_publish', base.get('caiwu_publish', False))),
            'caiwu_delete':  bool(cfg.get('caiwu_delete',  base.get('caiwu_delete', False))),
        }
    with _perm_cache_lock:
        _perm_cache[job] = (time.monotonic() + _PERM_CACHE_TTL, result)
    return result


def full_perms():
    return {'pages': {k: True for k in PAGE_KEYS}, 'view': _all_fields(True),
            'edit': _all_fields(True), 'ar_view': _all_ar_fields(True),
            'can_create': True, 'can_delete': True, 'ar_can_create': True,
            'ar_shared_only': False,
            'caiwu_view': _all_caiwu_fields(True),
            'caiwu_upload': True, 'caiwu_publish': True, 'caiwu_delete': True}


def effective_perms(user):
    """Perms object sent to the client (super_admin gets full access)."""
    cfg = full_perms() if user.role == 'super_admin' else get_job_perms(user.job_title)
    return {**cfg, 'is_admin': user.role == 'super_admin',
            'fields': PAYMENT_FIELD_DEFS, 'ar_fields': AR_FIELD_DEFS}


_AR_DEFS_BY_GROUP = {
    'project': AR_PROJECT_FIELD_DEFS,
    'record': AR_RECORD_FIELD_DEFS,
    'advance': AR_ADVANCE_FIELD_DEFS,
}


def apply_ar_view_mask(d, perms, group):
    """Null out AR dict fields the role cannot view. `group` is 'project',
    'record' or 'advance'. perms None (super_admin) → unchanged."""
    if perms is None:
        return d
    ar_view = perms.get('ar_view') or {}
    defs = _AR_DEFS_BY_GROUP.get(group, AR_RECORD_FIELD_DEFS)
    for f in defs:
        if not ar_view.get(f['key'], True):
            for c in f['cols']:
                if c in d:
                    d[c] = None
    return d


def get_request_perms(request):
    """Effective perms for the authed request. None means full access (super_admin)."""
    if request.pk_role == 'super_admin':
        return None
    jt = getattr(request, 'pk_job', '') or ''
    if not jt:
        u = PaikuanUser.objects.filter(id=request.pk_uid).only('job_title').first()
        jt = u.job_title if u else ''
    return get_job_perms(jt)


def apply_view_mask(d, perms):
    """Null out payment-dict fields the role cannot view."""
    if perms is None:
        return d
    view = perms['view']
    hide_cols = set()
    for f in PAYMENT_FIELD_DEFS:
        if not view.get(f['key'], True):
            hide_cols.update(f['cols'])
    for c in hide_cols:
        if c in d:
            d[c] = None
    inst_hidden = not view.get('installments', True)
    if inst_hidden:
        d['total_paid'] = None
    if inst_hidden or not view.get('total_amount', True):
        d['remaining'] = None
    return d


# ── helpers ───────────────────────────────────────────────────────────────────

def _no_store(resp):
    # API data is per-user and mutates frequently (e.g. user deletion); never let
    # a browser or proxy serve a stale copy that would resurrect deleted records.
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp['Pragma'] = 'no-cache'
    return resp


def ok(data=None):
    return _no_store(JsonResponse({'code': 0, 'data': data}))


def err(msg, status=400, code=-1):
    return _no_store(JsonResponse({'code': code, 'error': msg}, status=status))


def parse_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


def make_token(user):
    payload = {
        'uid': user.id,
        'role': user.role,
        'job': user.job_title,
        'departments': user.departments,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')


def pk_required(roles=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
            if not token:
                return err('未认证', 401, 401)
            try:
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
                uid = payload['uid']
            except jwt.ExpiredSignatureError:
                return err('Token已过期', 401, 401)
            except (jwt.InvalidTokenError, KeyError):
                return err('Token无效', 401, 401)
            user = PaikuanUser.objects.filter(id=uid).first()
            if not user:
                return err('用户不存在或登录已失效', 401, 401)
            if not user.is_active:
                return err('账号已停用，请重新登录', 401, 401)
            if not user.is_approved:
                return err('账号待审批，请联系管理员', 403, -2)
            # 改密码即踢旧会话：token 签发时间早于最近一次改密 → 失效
            if user.pwd_changed_at:
                iat = payload.get('iat')
                if iat and int(iat) < int(user.pwd_changed_at.timestamp()):
                    return err('密码已修改，请重新登录', 401, 401)
            request.pk_user = user
            request.pk_uid = user.id
            request.pk_role = user.role
            request.pk_job = user.job_title
            request.pk_depts = user.departments or []
            if roles and request.pk_role not in roles:
                return err('权限不足', 403, 403)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def _payments_page_denied(request, perms=None):
    perms = get_request_perms(request) if perms is None else perms
    if perms is not None and not perms['pages'].get('payments', True):
        return err('无访问权限', 403, 403)
    return None


def dept_filter(qs, request):
    """Row visibility: super_admin sees all; everyone else sees assigned departments.
    Optional ?depts=A,B,C further narrows the set (intersected with pk_depts)."""
    raw = request.GET.get('depts', '').strip()
    requested = [d for d in raw.split(',') if d.strip()] if raw else []

    if request.pk_role == 'super_admin':
        if requested:
            return qs.filter(department__in=requested)
        return qs

    allowed = set(request.pk_depts or [])
    if requested:
        active = [d for d in requested if d in allowed]
        if active:
            return qs.filter(department__in=active)
    return qs.filter(department__in=request.pk_depts)


def can_write_dept(request, dept):
    if request.pk_role == 'super_admin':
        return True
    return dept in request.pk_depts


_DEC = DjDecimalField(max_digits=15, decimal_places=2)


def _paid_subq():
    """Correlated subquery: sum of installment amounts for each Payment row."""
    return Coalesce(
        Subquery(
            PaymentInstallment.objects
                .filter(payment_id=OuterRef('pk'))
                .values('payment_id')
                .annotate(s=Sum('pay_amount'))
                .values('s'),
            output_field=_DEC,
        ),
        Value(Decimal('0')),
        output_field=_DEC,
    )


def _paid_expr():
    """Annotation expression for total paid amount (from installments subtable)."""
    return _paid_subq()


def _remaining_expr():
    """SQL expression for remaining = total_amount - paid (requires 'paid' annotation)."""
    return ExpressionWrapper(F('total_amount') - F('paid'), output_field=_DEC)


# 求和字段位宽放宽，避免跨多月结转累加时溢出 _DEC 的 15 位上限。
_DEC18 = DjDecimalField(max_digits=18, decimal_places=2)


def _not_settled_q(paid_field='_paid'):
    """未结清：已付 + 预付冲抵 仍小于有效计划（调整额优先）。
    预付冲抵的现金在预付时已流出，剩余应付须扣除——与资金池「刚性待付」口径一致。"""
    return (
        Q(plan_adjustment__isnull=True,
          **{f'{paid_field}__lt': F('total_amount') - F('prepaid_offset_amount')}) |
        Q(plan_adjustment__isnull=False,
          **{f'{paid_field}__lt': F('plan_adjustment') - F('prepaid_offset_amount')})
    )


def _effective_remaining_expr(paid_field='_paid'):
    """剩余应付：有效计划（调整额优先）− 已付 − 预付冲抵（与资金池口径一致）。"""
    return Case(
        When(plan_adjustment__isnull=False,
             then=ExpressionWrapper(
                 F('plan_adjustment') - F(paid_field) - F('prepaid_offset_amount'),
                 output_field=_DEC18)),
        default=ExpressionWrapper(
            F('total_amount') - F(paid_field) - F('prepaid_offset_amount'),
            output_field=_DEC18),
        output_field=_DEC18,
    )


# ── version / deploy check ──────────────────────────────────────────────────────
# Bump BUILD_VERSION whenever backend behaviour changes so a deploy can be verified
# by opening /api/pk/version in a browser (no auth required).
BUILD_VERSION = '2026-06-11.1'


@csrf_exempt
def version(request):
    return ok({
        'version': BUILD_VERSION,
        'features': {
            'hard_delete_user': True,      # DELETE /users/<id> permanently removes the row
            'stats_dept_filter': True,     # GET /stats?depts=A,B filters by department
            'no_store_headers': True,      # API responses are never cached
        },
    })


# ── auth ──────────────────────────────────────────────────────────────────────

@csrf_exempt
def register(request):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    phone = (data.get('phone') or '').strip()
    password = (data.get('password') or '').strip()
    name = (data.get('name') or '').strip()
    job_title = (data.get('job_title') or '').strip()
    depts = data.get('departments') or []

    if not phone or not password or not name:
        return err('手机号、密码和姓名均必填')
    if not phone.isdigit() or len(phone) < 8:
        return err('手机号格式有误')
    if len(password) < 8:
        return err('密码至少8位（建议包含字母和数字）')
    if not job_title or job_title not in JOB_TITLES:
        return err('请选择有效职务')
    if not isinstance(depts, list) or len(depts) == 0:
        return err('请至少选择一个部门')

    # Phone uniqueness
    existing = PaikuanUser.objects.filter(phone=phone).first()
    if existing:
        if existing.name != name:
            return err(f'该手机号已被"{existing.name}"注册，姓名不符')
        return err('该手机号已注册')
    # Name uniqueness — each person should have exactly one account
    if PaikuanUser.objects.filter(name=name).exists():
        return err('该姓名已被注册，如有疑问请联系管理员')

    is_first = not PaikuanUser.objects.exists()
    role = 'super_admin' if is_first else 'viewer'

    user = PaikuanUser(
        phone=phone, name=name, role=role,
        job_title=job_title,
        departments=depts if role != 'super_admin' else [],
        is_approved=is_first,
    )
    user.set_password(password)
    user.save()

    if is_first:
        return ok({'token': make_token(user), 'user': user.to_dict(),
                   'permissions': effective_perms(user), 'pending': False})
    return ok({'pending': True, 'message': '注册成功！请等待管理员审批后登录'})


@csrf_exempt
def login(request):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    phone = (data.get('phone') or '').strip()
    password = (data.get('password') or '').strip()
    if not phone or not password:
        return err('手机号和密码均必填')
    # 防暴力破解：同账号15分钟内失败≥5次 → 临时锁定（基于审计日志，多进程安全）
    try:
        from paikuan.models import AuditLog
        _cutoff = timezone.now() - datetime.timedelta(minutes=15)
        _failed = AuditLog.objects.filter(
            path__endswith='/login', status_code__gte=400,
            created_at__gte=_cutoff, user__phone=phone).count()
        if _failed >= 5:
            return err('失败次数过多，账号已临时锁定，请15分钟后再试', 429, 429)
    except Exception:
        pass
    try:
        user = PaikuanUser.objects.get(phone=phone)
    except PaikuanUser.DoesNotExist:
        return err('手机号或密码错误', 401, 401)
    if not user.is_active:
        return err('账号已停用，请联系管理员', 401, 401)
    if not user.check_password(password):
        return err('手机号或密码错误', 401, 401)
    if not user.is_approved:
        return err('账号待审批，请联系管理员', 403, -2)
    return ok({'token': make_token(user), 'user': user.to_dict(),
               'permissions': effective_perms(user)})


@csrf_exempt
def registration_status(request):
    """Public polling endpoint so a pending registrant can detect approval."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    phone = (request.GET.get('phone') or '').strip()
    if not phone:
        return err('缺少手机号')
    user = PaikuanUser.objects.filter(phone=phone).first()
    if not user:
        return ok({'status': 'none'})
    if not user.is_active:
        return ok({'status': 'rejected'})
    if user.is_approved:
        return ok({'status': 'approved'})
    return ok({'status': 'pending'})


@pk_required()
def me(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=request.pk_uid)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    return ok({'user': user.to_dict(), 'permissions': effective_perms(user)})


# ── payments ──────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def payments(request):
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    if request.method == 'GET':
        return _list_payments(request)
    if request.method == 'POST':
        return _create_payment(request)
    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def prepaid_balance(request):
    """排款页联动：按项目编号查该项目的「预付」未核销余额，提示是否先核销再付款。

    只读；按用户可见部门作用域过滤。未匹配到项目台账则返回空。
    """
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    project_no = (request.GET.get('project_no') or '').strip()
    empty = {'project_no': project_no, 'matched': False, 'count': 0,
             'total_balance': '0.00', 'items': []}
    if not project_no:
        return ok(empty)
    from ar.models import AdvanceRecord, ARProject
    proj = ARProject.objects.filter(project_no=project_no).first()
    if not proj:
        return ok(empty)
    qs = AdvanceRecord.objects.filter(direction='预付', balance_amount__gt=0, project=proj)
    if request.pk_role != 'super_admin':
        qs = qs.filter(delivery_dept__in=request.pk_depts)
    agg = qs.aggregate(total=Sum('balance_amount'), cnt=Count('id'))
    total = (agg['total'] or Decimal('0')).quantize(Decimal('0.01'))
    items = [{
        'id': r.id,
        'counterparty': r.counterparty,
        'occur_date': str(r.occur_date) if r.occur_date else None,
        'advance_amount': str(r.advance_amount),
        'balance_amount': str(r.balance_amount),
    } for r in qs.order_by('-balance_amount')[:20]]
    return ok({
        'project_no': project_no,
        'matched': True,
        'short_name': proj.short_name,
        'count': agg['cnt'] or 0,
        'total_balance': str(total),
        'items': items,
    })


def _list_payments(request):
    qs = Payment.objects.select_related('created_by').prefetch_related('installments').all()
    qs = dept_filter(qs, request)

    dept = request.GET.get('dept', '').strip()
    status_q = request.GET.get('status', '').strip()
    start = request.GET.get('start_date', '').strip()
    end = request.GET.get('end_date', '').strip()
    q = request.GET.get('q', '').strip()

    if dept:
        qs = qs.filter(department=dept)
    if start:
        qs = qs.filter(planned_date__gte=start)
    if end:
        qs = qs.filter(planned_date__lte=end)
    if q:
        qs = qs.filter(
            Q(project_desc__icontains=q) | Q(payee__icontains=q) |
            Q(approval_number__icontains=q) | Q(department__icontains=q) |
            Q(applicant__icontains=q)
        )

    try:
        page = max(1, int(request.GET.get('page', 1)))
        size = min(200, max(1, int(request.GET.get('size', 50))))
    except ValueError:
        page, size = 1, 50

    # Status filter via SQL annotation — avoids fetching all rows into Python.
    # 口径与 _not_settled_q 一致：已付 + 预付冲抵 对比有效计划（调整额优先）。
    if status_q:
        qs = qs.annotate(paid=_paid_expr())
        if status_q == 'pending':
            qs = qs.filter(paid=Decimal('0'), plan_adjustment__isnull=True,
                           prepaid_offset_amount=Decimal('0'))
        elif status_q == 'settled':
            qs = qs.filter(
                Q(paid__gte=F('total_amount') - F('prepaid_offset_amount')) |
                Q(plan_adjustment__isnull=False,
                  paid__gte=F('plan_adjustment') - F('prepaid_offset_amount'))
            )
        elif status_q == 'partial':
            qs = qs.filter(paid__gt=Decimal('0'),
                           paid__lt=F('total_amount') - F('prepaid_offset_amount'),
                           plan_adjustment__isnull=True)
        elif status_q == 'overdue':
            today_val = datetime.date.today()
            qs = qs.filter(planned_date__lt=today_val).filter(_not_settled_q('paid'))
        elif status_q == 'adjusted':
            qs = qs.filter(plan_adjustment__isnull=False,
                           paid__lt=F('plan_adjustment') - F('prepaid_offset_amount'))

    total = qs.count()

    # 未结清合计：与 stats/资金池共用同一口径 helper（扣预付冲抵）
    paid_expr = _paid_expr()
    not_settled = _not_settled_q('_paid')
    effective_remaining = _effective_remaining_expr('_paid')
    summary = qs.annotate(_paid=paid_expr).aggregate(
        outstanding=Sum(effective_remaining, filter=not_settled),
        outstanding_count=Count('id', filter=not_settled),
        planned_total=Sum('total_amount'),
        paid_total=Sum('_paid'),
    )
    outstanding_total = summary['outstanding'] or Decimal('0')
    outstanding_count = summary['outstanding_count'] or 0

    perms = get_request_perms(request)
    items = [apply_view_mask(p.to_dict(), perms) for p in qs[(page - 1) * size: page * size]]
    return ok({
        'items': items, 'total': total, 'page': page, 'size': size,
        'outstanding_total': str(outstanding_total),
        'outstanding_count': outstanding_count,
        'planned_total': str(summary['planned_total'] or Decimal('0')),
        'paid_total': str(summary['paid_total'] or Decimal('0')),
    })


def _parse_payment_fields(data, payment=None):
    fields = {}

    def get(key, default=None):
        return data.get(key, getattr(payment, key, default) if payment else default)

    fields['department'] = (get('department') or '').strip()
    fields['applicant'] = (get('applicant') or '').strip()[:100]
    fields['approval_number'] = (get('approval_number') or '').strip()
    fields['project_no'] = (get('project_no') or '').strip()[:20]
    fields['project_desc'] = (get('project_desc') or '').strip()
    fields['payee'] = (get('payee') or '').strip()
    fields['notes'] = (get('notes') or '').strip()

    # plan_adjustment: nullable decimal — None means "no adjustment"
    pa_raw = get('plan_adjustment')
    if pa_raw not in (None, '', 0):
        pa_str = str(pa_raw).replace(',', '').replace('，', '').replace('¥', '').replace('￥', '').strip()
        try:
            pa_val = Decimal(pa_str or '0')
            if pa_val < Decimal('0'):
                return None, '计划调整金额不能为负数'
            fields['plan_adjustment'] = pa_val
        except (InvalidOperation, TypeError):
            return None, f'计划调整金额"{pa_raw}"格式有误，请填写纯数字金额（如 20000）'
    else:
        fields['plan_adjustment'] = None

    def _num(raw):
        s = str(raw if raw not in (None, '') else 0)
        s = s.replace(',', '').replace('，', '').replace('¥', '').replace('￥', '').strip()
        return Decimal(s or '0')

    try:
        fields['total_amount'] = _num(get('total_amount', 0))
    except (InvalidOperation, TypeError) as e:
        return None, f'计划总金额格式有误: {e}'
    if fields['total_amount'] < Decimal('0'):
        return None, '计划总金额不能为负数'
    if fields['total_amount'] <= Decimal('0'):
        return None, '计划总金额必须大于0'

    # Parse planned_date
    pd_val = data.get('planned_date') if 'planned_date' in data else getattr(payment, 'planned_date', None)
    fields['planned_date'] = pd_val or None
    if fields['planned_date']:
        try:
            datetime.date.fromisoformat(str(fields['planned_date']))
        except ValueError:
            return None, f'计划付款日期无效（{fields["planned_date"]}），请使用 YYYY-MM-DD 格式'

    # Parse installments list
    raw_insts = data.get('installments')
    if raw_insts is None and payment:
        # Keep existing installments when not provided on edit (handled separately)
        raw_insts = None
        fields['installments'] = None  # sentinel: do not update
    else:
        raw_insts = raw_insts or []
        parsed_insts = []
        total_paid = Decimal('0')
        for idx, item in enumerate(raw_insts, 1):
            try:
                amt = _num(item.get('pay_amount', 0))
            except (InvalidOperation, TypeError):
                return None, f'第{idx}次付款金额格式有误'
            if amt < Decimal('0'):
                return None, f'第{idx}次付款金额不能为负数'
            if amt <= Decimal('0'):
                return None, f'第{idx}次付款金额必须大于0'
            pay_date = (item.get('pay_date') or '').strip() or None
            if not pay_date:
                return None, f'第{idx}次付款日期必填'
            try:
                pay_date_d = datetime.date.fromisoformat(str(pay_date))
            except ValueError:
                return None, f'第{idx}次付款日期无效（{pay_date}），请使用 YYYY-MM-DD 格式'
            # 付款明细是已发生的现金事件：未来日期会让这笔钱既不算已付现金流、
            # 又被从刚性待付中扣掉，资金池两头都看不见
            if pay_date_d > datetime.date.today():
                return None, f'第{idx}次付款日期（{pay_date}）不能晚于今天——实际付款以发生日入账；计划性付款请用「计划付款日期」'
            total_paid += amt
            parsed_insts.append({
                'seq': idx,
                'pay_date': pay_date,
                'pay_amount': amt,
                'notes': (item.get('notes') or '').strip()[:200],
                'id': item.get('id'),  # for update — may be None for new rows
            })
        fields['installments'] = parsed_insts

    # ── 有效计划（调整额优先）与实付/冲抵的关系校验 ──────────────────────────
    # 覆盖：实付超出有效计划；把计划/调整额改到低于已付（会让剩余被截到0、状态假结清）
    effective_plan = (fields['plan_adjustment'] if fields['plan_adjustment'] is not None
                      else fields['total_amount'])
    if fields['installments'] is not None:
        paid_check = sum((i['pay_amount'] for i in fields['installments']), Decimal('0'))
    elif payment is not None:
        paid_check = payment.total_paid
    else:
        paid_check = Decimal('0')
    if paid_check > effective_plan:
        label = '计划调整金额' if fields['plan_adjustment'] is not None else '计划总金额'
        return None, (
            f'实付总额（{paid_check}元）超出{label}（{effective_plan}元），'
            '请核实金额后再提交'
        )

    if not fields['department']:
        return None, '部门必填'
    if fields['department'] not in VALID_DEPARTMENTS:
        return None, f'部门"{fields["department"]}"无效，请使用系统预设部门'
    if not fields['project_desc']:
        return None, '付款事项描述必填'
    if not fields['payee']:
        return None, '收款方必填'
    # Payee must be text (letters/Chinese/digits/common punctuation only — no HTML/control chars)
    if fields['payee'] and re.search(r'[<>{}\[\]|\\^~`@#$%&*=+]', fields['payee']):
        return None, '收款方仅允许输入文字内容，不能含特殊符号'
    if not fields['planned_date']:
        return None, '计划付款日期必填'
    # Approval number: must be exactly 21 digits when provided
    if fields['approval_number'] and not re.fullmatch(r'\d{21}', fields['approval_number']):
        return None, '审批单号须为21位数字（如不填写可留空）'

    return fields, None


# Field-name → Chinese-label map for change-log records.
_PAYMENT_FIELD_LABELS = {
    'department': '部门', 'applicant': '申请人', 'approval_number': '审批单号',
    'project_desc': '付款事项', 'payee': '收款方',
    'total_amount': '计划总金额', 'planned_date': '计划付款日期',
    'notes': '备注',
    'plan_adjustment': '计划调整金额',
}


def _find_duplicate_payment(fields, exclude_id=None):
    """Detect duplicate planned payments on same business key.

    Business key: department + approval_number + payee + planned_date + total_amount.
    Skip the rule when approval_number is blank (low confidence).
    """
    if not fields.get('approval_number'):
        return None
    qs = Payment.objects.filter(
        department=fields['department'],
        approval_number=fields['approval_number'],
        payee=fields['payee'],
        planned_date=fields['planned_date'],
        total_amount=fields['total_amount'],
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.first()


def _record_payment_changes(payment, before_dict, after_dict, request, action='update'):
    """Persist field-level diffs into PaymentChangeLog."""
    user = PaikuanUser.objects.filter(id=request.pk_uid).only('id', 'name').first() \
        if getattr(request, 'pk_uid', None) else None
    operator_name = user.name if user else ''
    if action == 'create':
        PaymentChangeLog.objects.create(
            payment=payment, payment_id_snapshot=payment.id,
            action='create', operator=user, operator_name=operator_name,
            field_name='', field_label='整条记录',
            old_value='', new_value=f'新建排款 #{payment.id}',
        )
        return
    if action == 'delete':
        PaymentChangeLog.objects.create(
            payment=None, payment_id_snapshot=payment.id,
            action='delete', operator=user, operator_name=operator_name,
            field_name='', field_label='整条记录',
            old_value=f'排款 #{payment.id}', new_value='',
        )
        return
    # update: diff each tracked field
    logs = []
    for fname, label in _PAYMENT_FIELD_LABELS.items():
        old_v = before_dict.get(fname)
        new_v = after_dict.get(fname)
        if str(old_v if old_v is not None else '') != str(new_v if new_v is not None else ''):
            logs.append(PaymentChangeLog(
                payment=payment, payment_id_snapshot=payment.id,
                action='update', operator=user, operator_name=operator_name,
                field_name=fname, field_label=label,
                old_value=str(old_v if old_v is not None else ''),
                new_value=str(new_v if new_v is not None else ''),
            ))
    # diff installments as a whole
    old_insts = before_dict.get('installments_summary', '')
    new_insts = after_dict.get('installments_summary', '')
    if old_insts != new_insts:
        logs.append(PaymentChangeLog(
            payment=payment, payment_id_snapshot=payment.id,
            action='update', operator=user, operator_name=operator_name,
            field_name='installments', field_label='付款明细',
            old_value=old_insts, new_value=new_insts,
        ))
    if logs:
        PaymentChangeLog.objects.bulk_create(logs)


def _save_installments(payment, parsed_insts):
    """Replace all installments for a payment with the provided list."""
    payment.installments.all().delete()
    if parsed_insts:
        PaymentInstallment.objects.bulk_create([
            PaymentInstallment(
                payment=payment,
                seq=inst['seq'],
                pay_date=inst['pay_date'],
                pay_amount=inst['pay_amount'],
                notes=inst['notes'],
            )
            for inst in parsed_insts
        ])


def _installments_summary(insts_qs):
    """Human-readable summary of installments for change-log."""
    rows = list(insts_qs.order_by('seq', 'pay_date'))
    if not rows:
        return '无'
    return '；'.join(f'{i.pay_date} ¥{i.pay_amount}' for i in rows)


def _create_payment(request):
    perms = get_request_perms(request)
    if perms is not None and not perms['can_create']:
        return err('无新增权限', 403, 403)
    data = parse_body(request)
    fields, error = _parse_payment_fields(data)
    if error:
        return err(error)
    if not can_write_dept(request, fields['department']):
        return err('无权操作该部门', 403, 403)
    parsed_insts = fields.pop('installments') or []
    # Idempotency: block duplicate submissions on the same business key.
    dup = _find_duplicate_payment(fields)
    if dup:
        return err(
            f'重复排款：已有相同审批单号({fields["approval_number"]})/收款方/计划日期/计划金额的排款记录 #{dup.id}',
            409, 409,
        )
    try:
        with transaction.atomic():
            p = Payment(created_by_id=request.pk_uid, updated_by_id=request.pk_uid, **fields)
            p.save()
            _save_installments(p, parsed_insts)
            _record_payment_changes(p, {}, {}, request, action='create')
    except IntegrityError:
        dup = _find_duplicate_payment(fields)
        ref = f' #{dup.id}' if dup else ''
        return err(
            f'重复排款：已有相同审批单号/收款方/计划日期/金额的排款记录{ref}',
            409, 409,
        )
    p_fresh = Payment.objects.prefetch_related('installments').select_related('created_by').get(id=p.id)
    return ok(p_fresh.to_dict())


def _editable_payment_payload(data, perms):
    """Drop non-editable payment fields before merge+validation on update."""
    if perms is None:
        return data
    editable_cols = set()
    for f in PAYMENT_FIELD_DEFS:
        if perms['edit'].get(f['key'], False):
            editable_cols.update(f['cols'])
    # 'installments' is a virtual key — always include it when its permission is granted
    if 'installments' in editable_cols and 'installments' in data:
        editable_cols.add('installments')
    return {k: v for k, v in data.items() if k in editable_cols or k == 'installments'}


@csrf_exempt
@pk_required()
def payment_detail(request, pk):
    try:
        p = Payment.objects.select_related('created_by').prefetch_related('installments').get(id=pk)
    except Payment.DoesNotExist:
        return err('记录不存在', 404)

    if not dept_filter(Payment.objects.filter(id=pk), request).exists():
        return err('无权访问', 403, 403)

    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied

    if request.method == 'GET':
        return ok(apply_view_mask(p.to_dict(), perms))

    if request.method == 'PUT':
        # Record-level access: super_admin or write access to this department.
        if not can_write_dept(request, p.department):
            return err('无权编辑此记录', 403, 403)
        data = _editable_payment_payload(parse_body(request), perms)
        fields, error = _parse_payment_fields(data, payment=p)
        if error:
            return err(error)
        new_dept = fields['department']
        if new_dept != p.department and not can_write_dept(request, new_dept):
            return err('无权操作目标部门', 403, 403)
        parsed_insts = fields.pop('installments')  # None means "keep existing"
        before_snapshot = {f: getattr(p, f) for f in _PAYMENT_FIELD_LABELS}
        before_snapshot['installments_summary'] = _installments_summary(p.installments)
        with transaction.atomic():
            for k, v in fields.items():
                setattr(p, k, v)
            p.updated_by_id = request.pk_uid
            p.save()
            if parsed_insts is not None:
                _save_installments(p, parsed_insts)
            after_snapshot = {f: getattr(p, f) for f in _PAYMENT_FIELD_LABELS}
            after_snapshot['installments_summary'] = _installments_summary(p.installments)
            _record_payment_changes(p, before_snapshot, after_snapshot, request, action='update')
        p_fresh = Payment.objects.prefetch_related('installments').select_related('created_by').get(id=p.id)
        return ok(apply_view_mask(p_fresh.to_dict(), perms))

    if request.method == 'DELETE':
        if perms is not None:
            if not perms['can_delete']:
                return err('无删除权限', 403, 403)
            if not can_write_dept(request, p.department):
                return err('无权删除此记录', 403, 403)
        # 已关联预付核销的排款不可直接删：FK 置空后核销悬空、
        # 预付台账与资金池的冲抵口径会失去对应关系
        if p.prepaid_offsets.exists():
            return err('该排款已关联预付核销，不能直接删除；'
                       '请先到「预收预付」删除对应核销记录后再删本排款', 409, 409)
        with transaction.atomic():
            _record_payment_changes(p, {}, {}, request, action='delete')
            p.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def payment_change_logs(request, pk):
    """Return the change-log timeline for a single payment."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    # Permission: viewer must have access to this row (same dept or super_admin).
    try:
        p = Payment.objects.get(id=pk)
    except Payment.DoesNotExist:
        # If the payment was deleted, still allow viewing logs (via snapshot id)
        # but only for super_admin to avoid leaking history.
        if request.pk_role != 'super_admin':
            return err('记录不存在', 404)
        logs = PaymentChangeLog.objects.filter(payment_id_snapshot=pk).order_by('-at')[:200]
        return ok({'items': [l.to_dict() for l in logs], 'payment_id': pk, 'deleted': True})
    if not dept_filter(Payment.objects.filter(id=pk), request).exists():
        return err('无权访问', 403, 403)
    logs = PaymentChangeLog.objects.filter(payment_id_snapshot=pk).order_by('-at')[:200]
    return ok({'items': [l.to_dict() for l in logs], 'payment_id': pk, 'deleted': False})


@csrf_exempt
@pk_required()
def approval_records(request):
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('approval_records', True):
        return err('无访问权限', 403, 403)
    if request.method == 'GET':
        qs = dept_filter(ApprovalRecord.objects.filter(archived=False), request)
        dept = request.GET.get('dept', '').strip()
        applicant = request.GET.get('applicant', '').strip()
        approval_no = request.GET.get('approval_number', '').strip()
        if dept:
            qs = qs.filter(department=dept)
        if applicant:
            qs = qs.filter(applicant__icontains=applicant)
        if approval_no:
            qs = qs.filter(approval_number__icontains=approval_no)
        total_amount = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
        total = qs.count()
        items = [o.to_dict() for o in qs[(page - 1) * size: page * size]]
        return ok({'items': items, 'total': total, 'page': page, 'size': size, 'total_amount': str(total_amount)})
    if request.method == 'POST':
        if perms is not None and not perms.get('can_create'):
            return err('无新增权限', 403, 403)
        data = parse_body(request)
        applicant = (data.get('applicant') or '').strip()
        department = (data.get('department') or '').strip()
        approval_number = (data.get('approval_number') or '').strip()
        summary = (data.get('summary') or '').strip()
        payee = (data.get('payee') or '').strip()
        status = (data.get('status') or 'pending').strip()
        amount = Decimal(str(data.get('amount') or '0'))
        if not applicant:
            return err('申请人不能为空')
        if amount <= 0:
            return err('申请金额必须大于0')
        # 空审批编号自动填 21 位 0（占位，便于后续补录）
        if not approval_number:
            approval_number = '0' * 21
        elif not re.fullmatch(r'\d{21}', approval_number):
            return err('审批编号必须为21位数字')
        if department not in VALID_DEPARTMENTS:
            return err('所属事业部无效')
        if status not in {'pending', 'approved', 'rejected', 'canceled'}:
            return err('审批状态无效')
        if not can_write_dept(request, department):
            return err('无权操作该部门', 403, 403)
        # 仅有审批权限职务可直接登记 approved/rejected；其它人新建只能为 pending
        if status != 'pending' and not is_approver(request):
            return err('当前职务无权直接登记非待审批状态，请先创建为"待审批"', 403, 403)
        rec = ApprovalRecord.objects.create(
            applicant=applicant, department=department, approval_number=approval_number,
            summary=summary, amount=amount, payee=payee, status=status, created_by_id=request.pk_uid
        )
        return ok(rec.to_dict())
    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def approval_record_detail(request, pk):
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('approval_records', True):
        return err('无访问权限', 403, 403)
    try:
        rec = ApprovalRecord.objects.get(pk=pk)
    except ApprovalRecord.DoesNotExist:
        return err('记录不存在', 404)
    if not can_write_dept(request, rec.department):
        return err('无权操作该部门', 403, 403)
    if request.method == 'PUT':
        # 归档即终态（已排款 / 已拒绝 / 已撤销）：不可再改——
        # 已排款的审批改金额会让排款与审批对不上；已拒绝/撤销复活会产生
        # 列表与资金池在途都看不见的幽灵记录（archived 永远为 True）
        if rec.archived:
            return err('该审批记录已归档（已排款或已拒绝/已撤销），不可修改；如需变更请新建记录', 409, 409)
        # 写入能力闸口：与新建一致（防止只读岗位改写审批台账）
        if perms is not None and not (perms.get('can_create') or is_approver(request)):
            return err('无编辑权限', 403, 403)
        data = parse_body(request)
        for k in ('applicant', 'summary', 'payee'):
            if k in data:
                setattr(rec, k, (data.get(k) or '').strip())
        if 'department' in data and data['department'] in VALID_DEPARTMENTS:
            if not can_write_dept(request, data['department']):
                return err('无权操作目标事业部', 403, 403)
            rec.department = data['department']
        if 'approval_number' in data and re.fullmatch(r'\d{21}', str(data['approval_number'])):
            rec.approval_number = str(data['approval_number'])
        if 'amount' in data:
            try:
                new_amount = Decimal(str(data['amount'] or '0'))
            except (InvalidOperation, ValueError, TypeError):
                return err('申请金额格式错误')
            if new_amount <= 0:
                return err('申请金额必须大于0')
            # 金额是审批的标的：已审批通过的记录改金额会让资金池「在途支出」
            # 被悄悄改写，须先退回待审批再改
            if new_amount != rec.amount and rec.status != 'pending':
                return err('仅「待审批」状态可修改金额；已审批的记录请先退回待审批再修改')
            rec.amount = new_amount
        if 'status' in data and data['status'] in {'pending', 'approved', 'rejected', 'canceled'}:
            new_status = data['status']
            # 仅审批权限职务可设置 approved/rejected；任何登记人均可取消自己的申请
            if new_status in {'approved', 'rejected'} and not is_approver(request):
                return err('当前职务无权审批/拒绝该记录', 403, 403)
            if new_status == 'canceled' and not is_approver(request) and rec.created_by_id != request.pk_uid:
                return err('仅原申请人或审批人可撤销', 403, 403)
            rec.status = new_status
            if rec.status in {'rejected', 'canceled'}:
                rec.archived = True
        rec.save()
        return ok(rec.to_dict())
    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def approval_record_schedule(request, pk):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    # 须同时具备审批页与排款页权限 + 新增权限
    perms = get_request_perms(request)
    if perms is not None:
        if not perms['pages'].get('approval_records', True):
            return err('无审批记录访问权限', 403, 403)
        if not perms['pages'].get('payments', True):
            return err('无排款台账访问权限', 403, 403)
        if not perms.get('can_create'):
            return err('无新增排款权限', 403, 403)
    try:
        rec = ApprovalRecord.objects.get(pk=pk, archived=False)
    except ApprovalRecord.DoesNotExist:
        return err('记录不存在', 404)
    if not can_write_dept(request, rec.department):
        return err('无权操作该部门', 403, 403)
    if rec.status != 'approved':
        return err('仅审批通过记录可排款')
    data = parse_body(request)
    planned_date = data.get('planned_date')
    total_amount = Decimal(str(data.get('total_amount') or '0'))
    if not planned_date or total_amount <= 0:
        return err('计划日期和计划金额必填')
    fields = {
        'department': rec.department,
        'approval_number': rec.approval_number,
        'payee': rec.payee,
        'planned_date': planned_date,
        'total_amount': total_amount,
    }
    dup = _find_duplicate_payment(fields)
    if dup:
        return err(
            f'重复排款：已有相同审批单号/收款方/计划日期/金额的排款记录 #{dup.id}',
            409, 409,
        )
    try:
        with transaction.atomic():
            # 二次检查 + 原子创建+归档（避免并发下两个请求同时通过 dup 检查）
            rec_locked = ApprovalRecord.objects.select_for_update().get(pk=pk)
            if rec_locked.archived:
                return err('记录已归档', 409, 409)
            dup2 = _find_duplicate_payment(fields)
            if dup2:
                return err(
                    f'重复排款：已有相同审批单号/收款方/计划日期/金额的排款记录 #{dup2.id}',
                    409, 409,
                )
            p = Payment.objects.create(
                created_by_id=request.pk_uid,
                updated_by_id=request.pk_uid,
                department=rec.department,
                applicant=rec.applicant,
                approval_number=rec.approval_number,
                project_desc=rec.summary,
                payee=rec.payee,
                total_amount=total_amount,
                planned_date=planned_date,
            )
            _record_payment_changes(p, {}, {}, request, action='create')
            rec_locked.archived = True
            rec_locked.save(update_fields=['archived', 'updated_at'])
    except IntegrityError:
        dup = _find_duplicate_payment(fields)
        ref = f' #{dup.id}' if dup else ''
        return err(
            f'重复排款：已有相同审批单号/收款方/计划日期/金额的排款记录{ref}',
            409, 409,
        )
    return ok({'payment': p.to_dict(), 'archived': rec.id})


@pk_required()
def approval_template(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)
    wb = Workbook()
    ws = wb.active
    ws.title = '审批记录导入模板'
    headers = ['申请人*', '所属事业部*', '审批编号*', '摘要', '申请金额*', '收款主体', '审批状态*']
    header_fill = PatternFill(fill_type='solid', fgColor='C96342')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h); c.fill = header_fill; c.font = header_font; c.alignment = center
    ws.append(['示例张三', '运输事业部', '123456789012345678901', '示例摘要', 10000, '某供应商', '待审批'])
    return _build_excel_response(wb, '审批记录导入模板.xlsx')


@csrf_exempt
@pk_required()
def approval_import(request):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    if perms is not None:
        if not perms['pages'].get('approval_records', True):
            return err('无访问权限', 403, 403)
        if not perms.get('can_create'):
            return err('无新增权限', 403, 403)
    f = request.FILES.get('file')
    if not f:
        return err('请上传文件')
    from openpyxl import load_workbook
    wb = load_workbook(f, data_only=True)
    ws = wb.active
    headers = [str(ws.cell(1, c).value or '').strip() for c in range(1, ws.max_column + 1)]

    # 表头健壮匹配：去掉 *、＊、空格后建索引，并支持别名——这样模板(带*)、导出文件
    # (不带*)、以及用户轻微改动表头都能正确识别，避免"按要求填了却整表跳过"。
    def _norm(h):
        return str(h or '').strip().replace('*', '').replace('＊', '').replace(' ', '').replace('　', '')
    norm_col = {}
    for i, h in enumerate(headers, 1):
        key = _norm(h)
        if key and key not in norm_col:
            norm_col[key] = i

    def cv(r, *names):
        for n in names:
            ci = norm_col.get(_norm(n))
            if ci:
                return str(ws.cell(r, ci).value or '').strip()
        return ''

    # 必要列缺失（多为表头被删/改名/选错文件）→ 明确报错，而不是静默全跳过
    if not (norm_col.get('申请人') and (norm_col.get('申请金额') or norm_col.get('金额'))):
        return err('未识别到必要表头（申请人 / 申请金额）。请使用最新模板，或确认首行表头与列内容未被删改、且未选错文件。')

    created = skipped = 0
    errors = []
    for r in range(2, ws.max_row + 1):
        applicant = cv(r, '申请人')
        dept = cv(r, '所属事业部', '事业部', '部门')
        no = cv(r, '审批编号', '审批单号')
        status_cn = cv(r, '审批状态', '状态') or '待审批'
        amount_raw = cv(r, '申请金额', '金额')
        # 整行空白：直接略过，不计入跳过/报错（容忍模板尾部空行）
        if not any([applicant, dept, no, amount_raw, cv(r, '摘要'), cv(r, '收款主体')]):
            continue
        # 模板自带的示例行：静默跳过，避免误导入为真实数据
        if applicant.startswith('示例') or cv(r, '摘要').startswith('示例'):
            continue
        if not applicant or not amount_raw:
            skipped += 1; errors.append(f'第{r}行: 申请人和金额不能为空'); continue
        if not no:
            no = '0' * 21
        elif not re.fullmatch(r'\d{21}', no):
            skipped += 1; errors.append(f'第{r}行: 审批编号必须为21位数字（当前“{no}”），不填可留空'); continue
        if status_cn not in {'待审批', 'pending'}:
            skipped += 1; errors.append(f'第{r}行: 仅允许导入“待审批”状态（当前“{status_cn}”）'); continue
        if dept not in VALID_DEPARTMENTS:
            skipped += 1; errors.append(f'第{r}行: 所属事业部无效（当前“{dept or "空"}”）'); continue
        if not can_write_dept(request, dept):
            skipped += 1; errors.append(f'第{r}行: 无权操作事业部 {dept}'); continue
        try:
            amount = Decimal(str(amount_raw).replace(',', '').replace('，', '').replace('¥', '').strip())
            if amount <= 0:
                raise ValueError()
        except Exception:
            skipped += 1; errors.append(f'第{r}行: 申请金额无效（当前“{amount_raw}”）'); continue
        ApprovalRecord.objects.create(
            applicant=applicant, department=dept, approval_number=no,
            summary=cv(r, '摘要'), amount=amount, payee=cv(r, '收款主体'),
            status='pending', created_by_id=request.pk_uid
        )
        created += 1
    return ok({'created': created, 'skipped': skipped, 'errors': errors})


@pk_required()
def approval_export(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('approval_records', True):
        return err('无访问权限', 403, 403)
    qs = dept_filter(ApprovalRecord.objects.filter(archived=False), request)
    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')

    # Excel 公式注入防护：以 =+-@ 等开头的文本前置单引号转义
    _formula_chars = ('=', '+', '-', '@', '\t', '\r')

    def _safe(v):
        if isinstance(v, str) and v and v[0] in _formula_chars:
            return "'" + v
        return v
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = '审批记录'
    headers = ['申请人', '所属事业部', '审批编号', '摘要', '申请金额', '收款主体', '审批状态']
    header_fill = PatternFill(fill_type='solid', fgColor='C96342')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h); c.fill = header_fill; c.font = header_font; c.alignment = center
    cn = {'pending': '待审批', 'approved': '审批通过', 'rejected': '已拒绝', 'canceled': '已撤销'}
    for o in qs:
        ws.append([_safe(o.applicant), o.department, _safe(o.approval_number),
                   _safe(o.summary), float(o.amount), _safe(o.payee),
                   cn.get(o.status, o.status)])
    return _build_excel_response(wb, '审批记录.xlsx')


# ── dashboard ─────────────────────────────────────────────────────────────────

@pk_required()
def dashboard(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('dashboard', True):
        return err('无访问权限', 403, 403)
    today = timezone.localdate()
    show_amount = perms is None or perms['view'].get('total_amount', True)

    base = dept_filter(Payment.objects.all(), request).annotate(paid=_paid_expr())

    def money(v):
        return str(v if v is not None else Decimal('0')) if show_amount else None

    today_qs = base.filter(planned_date=today)
    pending_qs = base.filter(paid=Decimal('0'))
    overdue_qs = base.filter(paid__lt=F('total_amount'), planned_date__lt=today)

    # Each rollup is a single count+sum aggregate (indexed, no full table load).
    today_agg = today_qs.aggregate(c=Count('id'), s=Sum('total_amount'))
    # For pending records paid=0 → remaining == total_amount.
    pending_agg = pending_qs.aggregate(c=Count('id'), s=Sum('total_amount'))
    overdue_agg = overdue_qs.aggregate(c=Count('id'), s=Sum(_remaining_expr()))
    partial_agg = base.filter(paid__gt=Decimal('0'), paid__lt=F('total_amount')).aggregate(
        c=Count('id'), s=Sum(_remaining_expr()))

    today_payments = [
        apply_view_mask(p.to_dict(), perms)
        for p in today_qs.select_related('created_by').prefetch_related('installments')[:50]
    ]

    return ok({
        'today_count': today_agg['c'],
        'today_amount': money(today_agg['s']),
        'pending_count': pending_agg['c'],
        'pending_amount': money(pending_agg['s']),
        'partial_count': partial_agg['c'],
        'partial_amount': money(partial_agg['s']),
        'overdue_count': overdue_agg['c'],
        'overdue_amount': money(overdue_agg['s']),
        'today_payments': today_payments,
    })


# ── stats ─────────────────────────────────────────────────────────────────────

@pk_required()
def stats(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('stats', True):
        return err('无访问权限', 403, 403)
    if perms is not None and not perms['view'].get('total_amount', True):
        return err('无金额查看权限，无法查看统计', 403, 403)
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12):
            month = today.month
        if not (2000 <= year <= 2100):
            year = today.year
    except ValueError:
        year, month = today.year, today.month

    # 部门作用域 + 可选部门筛选先建基集，本期与前期结转共用同一过滤口径。
    base = dept_filter(Payment.objects.all(), request)
    depts_param = request.GET.get('depts', '').strip()
    if depts_param:
        selected = [d.strip() for d in depts_param.split(',') if d.strip()]
        if selected:
            base = base.filter(department__in=selected)

    qs = base.filter(
        planned_date__year=year, planned_date__month=month
    ).annotate(paid=_paid_expr())

    # 前期结转：计划日期早于本月、且仍未付清的排款，其剩余应付额结转到本期展示。
    month_start = datetime.date(year, month, 1)
    not_settled = _not_settled_q()
    eff_remaining = _effective_remaining_expr()
    carry_qs = base.filter(planned_date__lt=month_start).annotate(_paid=_paid_expr())

    D = Decimal

    # Overall totals + status breakdown in a single aggregate query.
    # 待付口径 = 计划 − 已付 − 预付冲抵（与付款台账列表/资金池一致）
    agg = qs.aggregate(
        total=Sum('total_amount'),
        paid_sum=Sum('paid'),
        offset_sum=Sum('prepaid_offset_amount'),
        cnt=Count('id'),
        settled=Count(Case(When(
            paid__gte=F('total_amount') - F('prepaid_offset_amount'), then=1))),
        partial=Count(Case(When(
            paid__gt=Decimal('0'),
            paid__lt=F('total_amount') - F('prepaid_offset_amount'), then=1))),
        pending=Count(Case(When(paid=Decimal('0'),
                                prepaid_offset_amount=Decimal('0'), then=1))),
    )
    total_amount = agg['total'] or D(0)
    total_paid = agg['paid_sum'] or D(0)
    total_remaining = total_amount - total_paid - (agg['offset_sum'] or D(0))
    completion_rate = round(float(total_paid / total_amount * 100), 1) if total_amount else 0.0

    # 前期结转合计（仅未付清部分的剩余应付额）。
    carry_agg = carry_qs.aggregate(
        carry=Sum(eff_remaining, filter=not_settled),
        carry_count=Count('id', filter=not_settled),
    )
    carryover_remaining = carry_agg['carry'] or D(0)
    carryover_count = carry_agg['carry_count'] or 0
    # 累计应付未付 = 本期未付 + 前期结转未付。
    total_outstanding = total_remaining + carryover_remaining

    # Per-department rollup grouped in SQL（本期 + 前期结转分别分组后合并）。
    dept_map = {}
    for r in qs.values('department').annotate(
            total=Sum('total_amount'), paid_sum=Sum('paid'),
            offset_sum=Sum('prepaid_offset_amount'), count=Count('id')):
        dept_map[r['department']] = {
            'total': r['total'] or D(0), 'paid': r['paid_sum'] or D(0),
            'offset': r['offset_sum'] or D(0),
            'count': r['count'], 'carry': D(0), 'carry_count': 0,
        }
    for r in carry_qs.values('department').annotate(
            carry=Sum(eff_remaining, filter=not_settled),
            carry_count=Count('id', filter=not_settled)):
        row = dept_map.setdefault(r['department'], {
            'total': D(0), 'paid': D(0), 'offset': D(0),
            'count': 0, 'carry': D(0), 'carry_count': 0})
        row['carry'] = r['carry'] or D(0)
        row['carry_count'] = r['carry_count'] or 0

    by_dept = []
    for dept, v in dept_map.items():
        t, pd, carry = v['total'], v['paid'], v['carry']
        by_dept.append({
            'dept': dept,
            'total': str(t),
            'paid': str(pd),
            'remaining': str(t - pd - v.get('offset', D(0))),
            'count': v['count'],
            'carry': str(carry),               # 前期结转未付
            'carry_count': v['carry_count'],
            'outstanding': str((t - pd) + carry),  # 本期未付 + 前期结转
            'completion_rate': round(float(pd / t * 100), 1) if t else 0.0,
        })
    # 按「应付合计（本期计划 + 前期结转）」降序，结转大的部门优先呈现。
    by_dept.sort(key=lambda x: Decimal(x['total']) + Decimal(x['carry']), reverse=True)

    return ok({
        'year': year, 'month': month,
        'total_amount': str(total_amount),
        'total_paid': str(total_paid),
        'total_remaining': str(total_remaining),
        'carryover_remaining': str(carryover_remaining),
        'carryover_count': carryover_count,
        'total_outstanding': str(total_outstanding),
        'completion_rate': completion_rate,
        'total_records': agg['cnt'],
        'by_dept': by_dept,
        'by_status': {
            'settled': agg['settled'],
            'partial': agg['partial'],
            'pending': agg['pending'],
        },
    })


# ── users ─────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required(roles=['super_admin'])
def users(request):
    if request.method == 'GET':
        try:
            all_users = PaikuanUser.objects.order_by('is_approved', 'id')
            return ok([u.to_dict() for u in all_users])
        except Exception as e:
            logger.error('users list failed: %s', e)
            return err('用户列表加载失败，请确认已执行 python manage.py migrate', 500)
    # Super admin cannot create users directly — users register themselves
    return err('请通过注册流程创建用户', 405)


@csrf_exempt
@pk_required(roles=['super_admin'])
def user_detail(request, pk):
    try:
        user = PaikuanUser.objects.get(id=pk)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)

    if request.method == 'PUT':
        data = parse_body(request)
        if 'name' in data:
            user.name = (data['name'] or '').strip()
        if 'role' in data:
            if data['role'] not in ('super_admin', 'manager', 'operator', 'viewer'):
                return err('角色无效')
            # Prevent creating a second super_admin
            if data['role'] == 'super_admin' and user.role != 'super_admin':
                return err('超级管理员只能有一位')
            # Prevent downgrading the only super_admin
            if user.role == 'super_admin' and data['role'] != 'super_admin':
                return err('不能修改超级管理员的角色')
            user.role = data['role']
        if 'departments' in data:
            depts = data['departments'] or []
            # Approved non-admin users must retain at least one department;
            # otherwise they'd become invisible to the system (no rows to see or edit).
            if user.is_approved and user.role != 'super_admin' and len(depts) == 0:
                return err('已审批用户至少需要分配一个部门')
            user.departments = depts
        if 'job_title' in data:
            user.job_title = data['job_title'] or ''
        if 'is_active' in data:
            user.is_active = bool(data['is_active'])
        if data.get('password'):
            if len(data['password']) < 8:
                return err('新密码至少8位（建议包含字母和数字）')
            user.set_password(data['password'])
            user.pwd_changed_at = timezone.now()
        user.save()
        return ok(user.to_dict())

    if request.method == 'DELETE':
        if user.id == request.pk_uid:
            return err('不能删除自己的账号')
        if user.role == 'super_admin':
            return err('不能删除超级管理员账号')
        user.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required(roles=['super_admin'])
def approve_user(request, pk):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=pk)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    except Exception as e:
        logger.error('approve_user get failed: %s', e)
        return err('操作失败，请先执行 python manage.py migrate', 500)
    if user.role == 'super_admin':
        return err('超级管理员无需审批')
    body = parse_body(request)
    # Super admin may adjust job title / departments at approval time.
    if body.get('job_title') in JOB_TITLES:
        user.job_title = body['job_title']
    if isinstance(body.get('departments'), list):
        user.departments = body['departments']
    user.is_approved = True
    user.is_active = True
    user.role = 'operator'   # regular member; field perms come from job_title
    try:
        user.approved_by_id = request.pk_uid
        user.approved_at = timezone.now()
        user.save()
    except Exception as e:
        logger.error('approve_user save failed: %s', e)
        return err('审批保存失败，请检查数据库迁移是否完整', 500)
    return ok(user.to_dict())


@csrf_exempt
@pk_required(roles=['super_admin'])
def reject_user(request, pk):
    """Reject a pending registration by deleting the account."""
    if request.method not in ('POST', 'DELETE'):
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=pk)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    except Exception as e:
        logger.error('reject_user get failed: %s', e)
        return err('操作失败，请先执行 python manage.py migrate', 500)
    if user.role == 'super_admin':
        return err('不能拒绝超级管理员')
    if user.is_approved:
        return err('该用户已审批，不能拒绝；如需禁用请使用停用')
    try:
        user.delete()
    except Exception as e:
        logger.error('reject_user delete failed: %s', e)
        return err('删除失败', 500)
    return ok({'rejected': pk})


# ── permissions ───────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required(roles=['super_admin'])
def permissions(request):
    """GET: full permission matrix for all job titles + field metadata."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    jobs = [
        {'job_title': key, 'label': label, 'config': get_job_perms(key)}
        for key, label in JOB_TITLES.items()
    ]
    return ok({
        'fields': PAYMENT_FIELD_DEFS,
        'ar_fields': AR_FIELD_DEFS,
        'caiwu_fields': CAIWU_FIELD_DEFS,
        'pages': [
            {'key': 'dashboard',         'label': '今日工作台'},
            {'key': 'payments',          'label': '付款台账'},
            {'key': 'approval_records',  'label': '审批记录'},
            {'key': 'stats',             'label': '月度统计'},
            {'key': 'ar_projects',       'label': '项目台账'},
            {'key': 'ar_records',        'label': '应收明细'},
            {'key': 'ar_advance',        'label': '预收预付'},
            {'key': 'ar_analytics',      'label': '应收分析'},
            {'key': 'ar_cashflow',       'label': '现金流分析'},
            {'key': 'ar_budget',         'label': '预算管理'},
            {'key': 'caiwu_report',      'label': '财务分析·报表'},
            {'key': 'caiwu_data',        'label': '财务分析·数据加工'},
            {'key': 'caiwu_charts',      'label': '财务分析·图表'},
            {'key': 'caiwu_metrics',     'label': '财务分析·指标管理'},
            {'key': 'caiwu_cockpit',     'label': '财务分析·驾驶舱'},
        ],
        'jobs': jobs,
    })


@csrf_exempt
@pk_required(roles=['super_admin'])
def permission_detail(request, job):
    """PUT: update one job title's permission config."""
    if request.method != 'PUT':
        return err('Method not allowed', 405)
    if job not in JOB_TITLES:
        return err('职务无效', 404)
    body = parse_body(request)
    cfg = body.get('config') or {}
    _base = default_job_config(job)   # 用于补齐前端未显式传入的能力位默认值

    # Sanitize against known keys to avoid storing junk.
    clean = {
        'pages': {k: bool(cfg.get('pages', {}).get(k, True)) for k in PAGE_KEYS},
        'view': {k: bool(cfg.get('view', {}).get(k, True)) for k in FIELD_KEYS},
        'edit': {k: bool(cfg.get('edit', {}).get(k, False)) for k in FIELD_KEYS},
        'ar_view': {k: bool(cfg.get('ar_view', {}).get(k, True)) for k in AR_FIELD_KEYS},
        'can_create': bool(cfg.get('can_create', False)),
        'can_delete': bool(cfg.get('can_delete', False)),
        # 应收专属写权限：前端未传时回退到该职务的基线默认（结算会计=True），
        # 避免老前端保存时把该能力清掉；前端传了则以传入为准（可自由搭配）。
        'ar_can_create': bool(cfg.get('ar_can_create', _base.get('ar_can_create', False))),
        'ar_shared_only': bool(cfg.get('ar_shared_only', False)),
        'caiwu_view': {k: bool(cfg.get('caiwu_view', {}).get(k, True)) for k in CAIWU_FIELD_KEYS},
        'caiwu_upload':  bool(cfg.get('caiwu_upload', False)),
        'caiwu_publish': bool(cfg.get('caiwu_publish', False)),
        'caiwu_delete':  bool(cfg.get('caiwu_delete', False)),
    }
    obj, _ = JobPermission.objects.get_or_create(job_title=job)
    obj.config = clean
    obj.save()
    _invalidate_perm_cache(job)
    # caiwu reads its 财务分析 perms straight from this JobPermission via paikuan's
    # cached get_job_perms (it keeps no cache of its own), so clearing this cache
    # is enough for the change to take effect everywhere immediately.
    return ok({'job_title': job, 'config': get_job_perms(job)})


# ── Excel template / import / export ─────────────────────────────────────────

def _visible_excel_cols(perms, n_installments=TEMPLATE_INSTALLMENT_SLOTS):
    """Return [(excel_header, db_col)] for columns the user can view.
    Installment columns are generated dynamically for n_installments slots.
    db_col for installment date/amount uses the slot index as 'inst_date_{n}' / 'inst_amount_{n}'.
    """
    can_view_insts = perms is None or perms['view'].get('installments', True)
    cols = []
    for (fk, h, c) in EXCEL_COLUMN_MAP:
        if perms is None or perms['view'].get(fk, True):
            cols.append((h, c))
        # Insert installment columns right after planned_date
        if fk == 'planned_date' and can_view_insts:
            for i in range(1, n_installments + 1):
                cols.append((f'第{i}次付款日期', f'inst_date_{i}'))
                cols.append((f'第{i}次付款金额(元)', f'inst_amount_{i}'))
    return cols


def _build_excel_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    # RFC 5987 encoding so Chinese filenames render correctly in all browsers.
    ascii_fallback = filename.encode('ascii', 'ignore').decode() or 'export.xlsx'
    encoded = quote(filename.encode('utf-8'), safe='')
    response['Content-Disposition'] = (
        f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
    )
    return response


@csrf_exempt
@pk_required()
def payment_template(request):
    """GET — download blank Excel import template (columns filtered by view perms)."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    cols = _visible_excel_cols(perms)

    wb = Workbook()
    ws = wb.active
    ws.title = '排款导入模板'

    header_fill = PatternFill(fill_type='solid', fgColor='C96342')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    example_font = Font(italic=True, color='888888', size=10)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Row 1: headers
    for col_idx, (header, _) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    # Row 2: example data (grayed out). The 部门 cell carries EXAMPLE_ROW_MARKER
    # so import skips this row even if the user forgets to delete it.
    example = {
        '部门': EXAMPLE_ROW_MARKER,
        '申请人': '如：张三',
        '审批单号': '123456789012345678901',
        '付款事项': '如：工程款结算',
        '收款方': '如：某某公司',
        '计划总金额(元)': 100000,
        '计划付款日期': '2026-06-01',
        '第1次付款日期': '',
        '第1次付款金额(元)': 0,
        '备注': '本行为格式示例，导入前可删除',
        '计划调整金额(元)': '',
    }
    for col_idx, (header, _) in enumerate(cols, 1):
        cell = ws.cell(row=2, column=col_idx, value=example.get(header, ''))
        cell.font = example_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    # Column widths
    for col_idx, (header, _) in enumerate(cols, 1):
        if '日期' in header:
            w = 14
        elif '金额' in header:
            w = 16
        elif header in ('部门',):
            w = 14
        elif header in ('审批单号',):
            w = 16
        elif header in ('付款事项',):
            w = 28
        elif header in ('收款方',):
            w = 22
        elif header in ('备注',):
            w = 24
        elif header in ('申请人',):
            w = 12
        else:
            w = 14
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = w

    ws.row_dimensions[1].height = 22

    return _build_excel_response(wb, 'paikuan_import_template.xlsx')


@csrf_exempt
@pk_required()
def payment_import(request):
    """POST multipart/form-data with field 'file' — bulk import payments from Excel."""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import load_workbook
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    if perms is not None and not perms['can_create']:
        return err('无新增权限', 403, 403)

    upload = request.FILES.get('file')
    if not upload:
        return err('请上传Excel文件(.xlsx)')

    MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
    if upload.size > MAX_UPLOAD_BYTES:
        return err('文件过大，请确认文件不超过5MB')

    try:
        wb = load_workbook(upload, read_only=True, data_only=True)
    except Exception:
        return err('文件格式有误，请使用下载的模板（.xlsx格式）')

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return err('文件为空')

    # Map header position → db column name (base fields)
    header_row = [str(v).strip() if v is not None else '' for v in rows[0]]
    col_pos = {}
    for i, h in enumerate(header_row):
        if h in _EXCEL_HEADER_TO_COL:
            col_pos[_EXCEL_HEADER_TO_COL[h]] = i

    # Detect dynamic installment columns: 第N次付款日期 / 第N次付款金额(元)
    import re as _re
    inst_date_cols = {}  # seq_no → column index
    inst_amt_cols = {}
    for i, h in enumerate(header_row):
        m = _re.fullmatch(r'第(\d+)次付款日期', h)
        if m:
            inst_date_cols[int(m.group(1))] = i
        m2 = _re.fullmatch(r'第(\d+)次付款金额\(元\)', h)
        if m2:
            inst_amt_cols[int(m2.group(1))] = i

    # Match the fields _parse_payment_fields actually validates as required.
    required_headers = {'department', 'project_desc', 'payee', 'planned_date'}
    missing = required_headers - set(col_pos.keys())
    if missing:
        missing_labels = [h for _, h, c in EXCEL_COLUMN_MAP if c in missing]
        return err(f'模板缺少必要列：{", ".join(missing_labels)}，请重新下载模板')

    results = {'created': 0, 'skipped': 0, 'errors': []}

    def cell_val(row, col_name):
        idx = col_pos.get(col_name)
        if idx is None or idx >= len(row):
            return None
        v = row[idx]
        if hasattr(v, 'strftime'):
            return v.strftime('%Y-%m-%d')
        if col_name in _EXCEL_DATE_COLS and isinstance(v, str) and v.strip():
            return _normalize_date(v)
        return v

    def cell_at(row, idx):
        if idx is None or idx >= len(row):
            return None
        v = row[idx]
        if hasattr(v, 'strftime'):
            return v.strftime('%Y-%m-%d')
        return v

    for row_num, row in enumerate(rows[1:], start=2):
        if all(v is None or v == '' for v in row):
            continue

        dept_raw = cell_val(row, 'department')
        if dept_raw and str(dept_raw).strip().startswith('示例'):
            continue

        data = {col: cell_val(row, col) for col in col_pos}

        # Build installments list from dynamic columns
        inst_seqs = sorted(set(inst_date_cols) | set(inst_amt_cols))
        installments_raw = []
        for n in inst_seqs:
            raw_date = cell_at(row, inst_date_cols.get(n))
            raw_amt = cell_at(row, inst_amt_cols.get(n))
            if raw_date:
                raw_date = _normalize_date(str(raw_date)) if isinstance(raw_date, str) else raw_date
            amt_str = str(raw_amt or '0').replace(',', '').replace('，', '').replace('¥', '').strip()
            try:
                amt = Decimal(amt_str or '0')
            except InvalidOperation:
                amt = Decimal('0')
            if raw_date and amt > Decimal('0'):
                installments_raw.append({'seq': n, 'pay_date': str(raw_date), 'pay_amount': str(amt), 'notes': ''})

        data['installments'] = installments_raw

        fields, error = _parse_payment_fields(data)
        if error:
            results['errors'].append(f'第{row_num}行: {error}')
            results['skipped'] += 1
            continue

        if not can_write_dept(request, fields['department']):
            results['errors'].append(f'第{row_num}行: 无权操作部门"{fields["department"]}"')
            results['skipped'] += 1
            continue

        parsed_insts = fields.pop('installments') or []
        dup = _find_duplicate_payment(fields)
        if dup:
            results['errors'].append(
                f'第{row_num}行: 跳过重复（已存在排款 #{dup.id}，相同审批单号+收款方+计划日期+金额）')
            results['skipped'] += 1
            continue
        try:
            with transaction.atomic():
                p = Payment.objects.create(
                    created_by_id=request.pk_uid, updated_by_id=request.pk_uid, **fields)
                _save_installments(p, parsed_insts)
                _record_payment_changes(p, {}, {}, request, action='create')
            results['created'] += 1
        except Exception as e:
            results['errors'].append(f'第{row_num}行: 保存失败 ({e})')
            results['skipped'] += 1

    if results['created'] > 0 and results['skipped'] == 0:
        results['message'] = f'全部 {results["created"]} 条数据成功导入'
    elif results['created'] > 0:
        results['message'] = f'成功导入 {results["created"]} 条，跳过 {results["skipped"]} 条（含错误）'
    else:
        results['message'] = f'没有可导入的数据（跳过 {results["skipped"]} 条）'
    return ok(results)


@csrf_exempt
@pk_required()
def payment_export(request):
    """GET — export filtered payment list to Excel (same filters as list view)."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    qs = Payment.objects.select_related('created_by').all()
    qs = dept_filter(qs, request)
    qs = qs.prefetch_related('installments')

    dept = request.GET.get('dept', '').strip()
    status_q = request.GET.get('status', '').strip()
    start = request.GET.get('start_date', '').strip()
    end = request.GET.get('end_date', '').strip()
    q_str = request.GET.get('q', '').strip()

    if dept:
        qs = qs.filter(department=dept)
    if start:
        qs = qs.filter(planned_date__gte=start)
    if end:
        qs = qs.filter(planned_date__lte=end)
    if q_str:
        qs = qs.filter(
            Q(project_desc__icontains=q_str) | Q(payee__icontains=q_str) |
            Q(approval_number__icontains=q_str) | Q(department__icontains=q_str) |
            Q(applicant__icontains=q_str)
        )
    if status_q:
        qs = qs.annotate(paid=_paid_expr())
        if status_q == 'pending':
            qs = qs.filter(paid=Decimal('0'), plan_adjustment__isnull=True)
        elif status_q == 'settled':
            qs = qs.filter(
                Q(paid__gte=F('total_amount')) |
                Q(plan_adjustment__isnull=False, paid__gte=F('plan_adjustment'))
            )
        elif status_q == 'partial':
            qs = qs.filter(paid__gt=Decimal('0'), paid__lt=F('total_amount'),
                           plan_adjustment__isnull=True)
        elif status_q == 'adjusted':
            qs = qs.filter(plan_adjustment__isnull=False, paid__lt=F('plan_adjustment'))
        elif status_q == 'overdue':
            today_val = datetime.date.today()
            qs = qs.filter(planned_date__lt=today_val).filter(
                Q(plan_adjustment__isnull=True, paid__lt=F('total_amount')) |
                Q(plan_adjustment__isnull=False, paid__lt=F('plan_adjustment'))
            )

    # Reject rather than silently truncate: a truncated export is worse than no export.
    EXPORT_CAP = 5000
    total_count = qs.count()
    if total_count > EXPORT_CAP:
        return err(
            f'当前筛选结果共 {total_count} 条，超出导出上限（{EXPORT_CAP} 条）。'
            '请缩小日期范围或添加其他筛选条件后重试。'
        )

    # Determine max installment count across the filtered set for dynamic columns.
    can_view_insts = perms is None or perms['view'].get('installments', True)
    all_payments = list(qs.prefetch_related('installments').select_related('created_by'))
    if can_view_insts and all_payments:
        max_slots = max((p.installments.count() for p in all_payments), default=0)
    else:
        max_slots = 0
    cols = _visible_excel_cols(perms, n_installments=max_slots)

    wb = Workbook()
    ws = wb.active
    ws.title = '排款记录'

    header_fill = PatternFill(fill_type='solid', fgColor='C96342')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    center = Alignment(horizontal='center', vertical='center')

    for col_idx, (header, _) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    status_label = {'pending': '⏳待付款', 'partial': '⚡部分付款', 'settled': '✅已付清', 'adjusted': '📋计划调整'}

    _FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')

    def _safe_text(v):
        if isinstance(v, str) and v and v[0] in _FORMULA_CHARS:
            return "'" + v
        return v

    for row_idx, p in enumerate(all_payments, start=2):
        d = apply_view_mask(p.to_dict(), perms)
        # Build installment slot map: seq → {date, amount}
        insts = d.get('installments') or []
        inst_by_seq = {inst['seq']: inst for inst in insts}
        for col_idx, (_, db_col) in enumerate(cols, 1):
            if db_col.startswith('inst_date_'):
                n = int(db_col.split('_')[-1])
                val = inst_by_seq[n]['pay_date'] if n in inst_by_seq else ''
            elif db_col.startswith('inst_amount_'):
                n = int(db_col.split('_')[-1])
                val = float(inst_by_seq[n]['pay_amount']) if n in inst_by_seq else 0.0
            else:
                val = d.get(db_col)
                if val is None:
                    val = ''
                if db_col in ('total_amount', 'total_paid', 'remaining', 'plan_adjustment'):
                    try:
                        val = float(val) if val != '' else 0.0
                    except (ValueError, TypeError):
                        pass
                else:
                    val = _safe_text(val)
            ws.cell(row=row_idx, column=col_idx, value=val)

        # Append status column after visible cols
        ws.cell(row=row_idx, column=len(cols) + 1,
                value=status_label.get(d.get('status', ''), ''))

    # Status header
    status_header_cell = ws.cell(row=1, column=len(cols) + 1, value='状态')
    status_header_cell.font = header_font
    status_header_cell.fill = header_fill
    status_header_cell.alignment = center

    # Auto-width approximation
    for col in ws.columns:
        max_len = max((len(str(c.value or '')) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 32)

    today = timezone.localdate().strftime('%Y%m%d')
    return _build_excel_response(wb, f'排款记录_{today}.xlsx')


# ── departments ───────────────────────────────────────────────────────────────

@pk_required()
def departments(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    denied = _payments_page_denied(request)
    if denied:
        return denied
    # Only return canonical departments. Historical records with non-canonical names
    # (from before strict validation) should not pollute the department picker.
    merged = list(DEPARTMENTS)
    # Non-admins may only see/filter departments they are assigned to,
    # matching the row-level visibility enforced by dept_filter().
    if request.pk_role != 'super_admin':
        allowed = set(request.pk_depts or [])
        merged = [d for d in merged if d in allowed]
    return ok(merged)


# ── 操作审计日志（仅超管）───────────────────────────────────────────────────────

@csrf_exempt
@pk_required(roles=['super_admin'])
def audit_logs(request):
    """全系统操作审计查询：按操作人/模块/方法/结果/路径关键词/日期过滤，分页。"""
    from paikuan.models import AuditLog
    if request.method != 'GET':
        return err('Method not allowed', 405)
    qs = AuditLog.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(path__icontains=q) | Q(user_name__icontains=q))
    module = request.GET.get('module', '').strip()
    if module:
        qs = qs.filter(module=module)
    method = request.GET.get('method', '').strip().upper()
    if method:
        qs = qs.filter(method=method)
    result = request.GET.get('result', '').strip()   # ok | fail
    if result == 'ok':
        qs = qs.filter(status_code__lt=400)
    elif result == 'fail':
        qs = qs.filter(status_code__gte=400)
    date_start = request.GET.get('date_start', '').strip()
    if date_start:
        qs = qs.filter(created_at__date__gte=date_start)
    date_end = request.GET.get('date_end', '').strip()
    if date_end:
        qs = qs.filter(created_at__date__lte=date_end)

    total = qs.count()
    page = max(1, int(request.GET.get('page', 1) or 1))
    size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
    items = [l.to_dict() for l in qs[(page - 1) * size: page * size]]
    return ok({'items': items, 'total': total, 'page': page, 'size': size})


@csrf_exempt
@pk_required(roles=['super_admin'])
def audit_logs_prune(request):
    """清理 N 天前的审计日志（默认保留180天），防止无限增长。"""
    from paikuan.models import AuditLog
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    try:
        keep_days = max(30, min(3650, int(data.get('keep_days', 180))))
    except (ValueError, TypeError):
        keep_days = 180
    cutoff = timezone.now() - datetime.timedelta(days=keep_days)
    deleted, _ = AuditLog.objects.filter(created_at__lt=cutoff).delete()
    return ok({'deleted': deleted, 'keep_days': keep_days})
