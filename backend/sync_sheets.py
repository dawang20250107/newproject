"""
腾讯文档智能表格 → MySQL 数据同步脚本
运行方式：在3号服务器上通过Django shell执行
python3 /home/ubuntu/kxt_backend/manage.py shell < /home/ubuntu/kxt_backend/sync_sheets.py
或 python3 /home/ubuntu/kxt_backend/manage.py shell -c "exec(open('/home/ubuntu/kxt_backend/sync_sheets.py').read())"
"""
import os, sys, django, json, requests
from datetime import datetime, date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wxcloudrun.settings')
django.setup()

from wxcloudrun.models import (
    Customer, Project, Receivable, Expense,
    InvoiceOut, InvoiceIn, PaymentRecord,
    ProjectInvoiceOut, ProjectExpense, ProjectInvoiceIn,
    ProjectCustomer, ReceivablePayment, ReceivableInvoiceOut, ExpenseInvoiceIn,
)

# ─── 腾讯文档API配置 ───────────────────────────────────
TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjbHQiOiIzM2U1MWE0MGYwZTg0YWM1YTAwYmE4MzAzYmIwM2ZjNCIsInR5cCI6MSwiZXhwIjoxNzc5Njg2NzkyLjY4MjgxLCJpYXQiOjE3NzcwOTQ3OTIuNjgyODEsInN1YiI6IjRmOTVjNmRjYTVhZDQzNDViN2JlYTgzODRiZWI1M2E0In0.GlKVOoHtXg2qRnbZ6uH0-iYaponxXjaMCEEAbicyLXw'
CID = '33e51a40f0e84ac5a00ba8303bb03fc4'
OID = '4f95c6dca5ad4345b7bea8384beb53a4'
FILE_ID = '300000000$DwyffGxEQtOk'
BASE = 'https://docs.qq.com/openapi/smartbook/v2/files'

headers = {
    'Access-Token': TOKEN,
    'Client-Id': CID,
    'Open-Id': OID,
    'Content-Type': 'application/json',
}


# ─── 通用工具函数 ─────────────────────────────────────

def fetch_records(sheet_id, limit=500):
    """获取指定子表的全部记录"""
    all_records = []
    offset = 0
    while True:
        url = f'{BASE}/{FILE_ID}/sheets/{sheet_id}'
        body = {"getRecords": {"offset": offset, "limit": min(limit, 1000)}}
        r = requests.post(url, headers=headers, json=body)
        data = r.json()
        records = data.get('data', {}).get('getRecords', {}).get('records', [])
        all_records.extend(records)
        has_more = data.get('data', {}).get('getRecords', {}).get('hasMore', False)
        if not has_more or not records:
            break
        offset += len(records)
    return all_records


def val_text(values, key, default=''):
    """提取文本值：支持 text/array/autoNumber/number 格式"""
    v = values.get(key)
    if v is None:
        return default
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return v.get('text', default)
    if isinstance(v, list) and len(v) > 0:
        item = v[0]
        if isinstance(item, dict):
            return item.get('text', default)
        if isinstance(item, str):
            return item
    return default


def val_number(values, key, default=None):
    """提取数字值：腾讯文档API数字字段直接返回数字，不是数组"""
    v = values.get(key)
    if v is None:
        return default
    # 数字字段：直接是 int/float
    if isinstance(v, (int, float)):
        return float(v)
    # 文本格式的数字：先用val_text提取
    s = val_text(values, key, '')
    if s == '' or s is None:
        return default
    try:
        return float(str(s).replace(',', ''))
    except (ValueError, TypeError):
        return default


def val_date(values, key, default=None):
    """提取日期值：腾讯文档API日期字段返回毫秒时间戳字符串"""
    v = values.get(key)
    if v is None:
        return default
    # 毫秒时间戳格式：如 "1774886400000"
    if isinstance(v, str) and v.isdigit() and len(v) >= 13:
        try:
            ts = int(v) / 1000
            return datetime.fromtimestamp(ts).date()
        except (ValueError, OSError):
            pass
    # 文本格式日期
    s = val_text(values, key, '')
    if not s:
        return default
    s = s.strip().replace('/', '-')
    for fmt in ('%Y-%m-%d', '%Y-%m', '%Y'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return default


def val_int(values, key, default=None):
    """提取整数值"""
    n = val_number(values, key)
    if n is None:
        return default
    try:
        return int(n)
    except (ValueError, TypeError):
        return default


def val_links(values, key):
    """提取twoWayLink关联的recordID列表"""
    v = values.get(key)
    if isinstance(v, list):
        return [str(item) for item in v if item]
    return []


def val_bool(values, key, default=None):
    """提取布尔值：腾讯文档公式字段返回数字(1/0)或文本"""
    v = values.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = val_text(values, key, '').strip()
    if not s:
        return default
    return s in ('是', 'True', 'true', '1', '逾期')


# ─── 同步映射表 ─────────────────────────────────────

SHEET_MAP = {
    'dQtpjn': 'customer',
    '9h0jSn': 'project',
    'NsE1dw': 'receivable',
    'xb3BWo': 'expense',
    'PGcWic': 'invoice_out',
    'tqVV8K': 'invoice_in',
    'PAlZhk': 'payment_record',
}

# 人员信息表（辅助查找，不同步到独立表）
PERSON_SHEET_ID = 'tWSJz4'

# 记录ID → 数据库ID 的映射（用于关联表）
rid_to_dbid = {}  # {sheet_name: {record_id: db_id}}


# ─── 各表同步函数 ─────────────────────────────────────

def sync_customer():
    """同步客户信息库"""
    print('[1/7] 同步客户信息库...')
    records = fetch_records('dQtpjn')
    count = 0
    rid_to_dbid['customer'] = {}

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')
        defaults = {
            'sheet_record_id': rid,
            'customer_code': val_text(v, '客户编号'),
            'customer_name': val_text(v, '客户名称') or f'未命名客户',
            'billing_name': val_text(v, '开票名称'),
            'tax_number': val_text(v, '税号'),
            'bank_name': val_text(v, '开户行'),
            'bank_account': val_text(v, '银行账号'),
            'contact_person': val_text(v, '联系人'),
            'contact_phone': val_text(v, '联系电话'),
            'contact_address': val_text(v, '联系地址'),
            'address_phone': val_text(v, '地址电话'),
            'industry': val_text(v, '所属行业'),
            'customer_type': val_text(v, '客户类型'),
            'remark': val_text(v, '备注'),
        }
        obj, created = Customer.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['customer'][rid] = obj.id
        count += 1

    print(f'  客户信息库: {count} 条记录同步完成')
    return count


def sync_project():
    """同步项目/合同台账"""
    print('[2/7] 同步项目/合同台账...')
    records = fetch_records('9h0jSn')
    count = 0
    rid_to_dbid['project'] = {}
    link_data = []  # 存储多对多关联，后续处理

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')

        # 关联客户（twoWayLink → 可能多条，取第一条作为主客户）
        customer_rids = val_links(v, '关联客户')
        customer_id = None
        customer_name = val_text(v, '客户名称')

        defaults = {
            'sheet_record_id': rid,
            'project_code': val_text(v, '项目编号'),
            'project_short_name': val_text(v, '项目简称') or f'未命名项目',
            'customer_id': customer_id,  # 后面更新
            'customer_name': customer_name,
            'project_manager': val_text(v, '项目负责人'),
            'sales_contact': val_text(v, '销售对接人'),
            'department': val_text(v, '所属事业部') or val_text(v, '项目部门'),
            'status': val_text(v, '状态'),
            'project_feature': val_text(v, '项目特征'),
            'business_model': val_text(v, '业务模式'),
            'billing_model': val_text(v, '账单模式'),
            'charge_mode': val_text(v, '收费模式'),
            'charge_standard': val_text(v, '收费标准'),
            'invoice_mode': str(val_number(v, '开票模式') or val_text(v, '开票模式', '')),
            'contract_amount': val_number(v, '合同金额(元)'),
            'contract_start_date': val_date(v, '合同开始日期'),
            'contract_end_date': val_date(v, '合同结束日期'),
            'reconciliation_period': val_text(v, '对账期(天)'),
            'invoice_wait_period': val_text(v, '开票等待期(天)'),
            'payment_period': val_text(v, '付款期(天)'),
            'shared_or_dedicated': val_text(v, '共享/独有'),
            'total_period_days': val_int(v, '总账期(天)'),
            'remark': val_text(v, '备注'),
        }
        obj, created = Project.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['project'][rid] = obj.id

        # 收集多对多关联
        link_data.append({
            'obj': obj,
            'customer_rids': customer_rids,
            'invoice_out_rids': val_links(v, '关联销项'),
            'expense_rids': val_links(v, '关联 报销'),
            'invoice_in_rids': val_links(v, '关联 进项'),
        })
        count += 1

    # 更新客户外键
    for ld in link_data:
        if ld['customer_rids'] and ld['customer_rids'][0] in rid_to_dbid.get('customer', {}):
            ld['obj'].customer_id = rid_to_dbid['customer'][ld['customer_rids'][0]]
            ld['obj'].save(update_fields=['customer_id'])

    print(f'  项目/合同台账: {count} 条记录同步完成')
    return count, link_data


def sync_receivable():
    """同步应收账款台账"""
    print('[3/7] 同步应收账款台账...')
    records = fetch_records('NsE1dw')
    count = 0
    rid_to_dbid['receivable'] = {}
    link_data = []

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')

        # 关联项目
        project_rids = val_links(v, '关联项目')
        project_id = None
        if project_rids and project_rids[0] in rid_to_dbid.get('project', {}):
            project_id = rid_to_dbid['project'][project_rids[0]]

        defaults = {
            'sheet_record_id': rid,
            'project_id': project_id,
            'project_short_name': val_text(v, '项目简称'),
            'customer_name': val_text(v, '客户名称'),
            'project_manager': val_text(v, '项目负责人'),
            'department': val_text(v, '所属事业部'),
            'account_period_type': val_text(v, '账期类型'),
            'operation_month': val_text(v, '运作月份（提取）') or val_text(v, '运作月份'),
            'receivable_amount': val_number(v, '应收金额(元)'),
            'invoiced_amount': val_number(v, '开票金额(元)'),
            'tax_amount': val_number(v, '税额'),
            'adjustment_amount': val_number(v, '调整额'),
            'received_amount': val_number(v, '已回款金额(元)'),
            'unreceived_amount': val_number(v, '未回款金额(元)'),
            'receivable_date': val_date(v, '应收日期'),
            'invoice_date': val_date(v, '开票日期'),
            'reconciliation_date': val_date(v, '对账时间'),
            'latest_payment_date': val_date(v, '最近回款日期'),
            'reconciliation_status': val_text(v, '对账状态'),
            'status': val_text(v, '状态'),
            'is_overdue': val_bool(v, '是否逾期'),
            'overdue_days': val_int(v, '逾期天数'),
            'creator': val_text(v, '创建人'),
        }
        # 冗余计算字段
        ra = defaults.get('receivable_amount') or 0
        recv = defaults.get('received_amount') or 0
        if ra and recv is not None:
            defaults['unreceived_amount'] = round(ra - recv, 2)

        # 逾期判断
        rd = defaults.get('receivable_date')
        if rd and recv is not None and recv < (ra or 0):
            from datetime import date as date_type
            today = date_type.today()
            if rd < today:
                defaults['is_overdue'] = True
                defaults['overdue_days'] = (today - rd).days

        obj, created = Receivable.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['receivable'][rid] = obj.id

        link_data.append({
            'obj': obj,
            'payment_rids': val_links(v, '关联'),
            'invoice_out_rids': val_links(v, '关联 1'),
        })
        count += 1

    print(f'  应收账款台账: {count} 条记录同步完成')
    return count, link_data


# ─── 人员信息查找辅助 ─────────────────────────────
# 腾讯文档费用报销表的"申请人"字段是type=21关联字段，存储的是
# 人员信息表中的 recordID。本函数拉取人员表建立ID→姓名映射。
# 注意事项：
#   人员信息表 (tWSJz4) 默认在 sync 脚本里不可见
#   费用报销表有 type=20 lookup 字段"人员姓名"但被隐藏（fieldVisibility=false）
#   详见 MEMORY.md 2026-04-29 踩坑记录

def fetch_person_name_map():
    """拉取人员信息表，建立 recordID → 姓名 映射"""
    print('  [辅助] 拉取人员信息表（申请人ID→姓名翻译）...')
    records = fetch_records(PERSON_SHEET_ID)
    name_map = {}
    for rec in records:
        rid = rec.get('recordID', '')
        v = rec.get('values', {})
        # 字段可能以中文名或 fieldID 返回，都尝试
        name = val_text(v, '人员姓名') or val_text(v, 'fD4OIT')
        if name:
            name_map[rid] = name
    print(f'   找到 {len(name_map)} 个人员映射')
    return name_map


def sync_expense():
    """同步付款/报销登记"""
    print('[4/7] 同步付款/报销登记...')
    records = fetch_records('xb3BWo')
    name_map = fetch_person_name_map()
    count = 0
    rid_to_dbid['expense'] = {}
    link_data = []

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')

        project_rids = val_links(v, '关联项目')
        project_id = None
        if project_rids and project_rids[0] in rid_to_dbid.get('project', {}):
            project_id = rid_to_dbid['project'][project_rids[0]]

        # 申请人ID→姓名翻译（腾讯文档关联字段返回的是recordID）
        raw_applicant = val_text(v, '申请人')
        applicant_name = name_map.get(raw_applicant, raw_applicant)

        defaults = {
            'sheet_record_id': rid,
            'project_id': project_id,
            'department': val_text(v, '所属事业部'),
            'dingtalk_id': val_text(v, '钉钉编号'),
            'applicant': applicant_name,
            'expense_type': val_text(v, '费用类型'),
            'summary': val_text(v, '摘要'),
            'apply_amount': val_number(v, '申请金额(元)'),
            'pay_amount': val_number(v, '付款金额(元)'),
            'pending_amount': val_number(v, '待付金额'),
            'has_vat_invoice': val_text(v, '有无专票'),
            'pay_entity': val_text(v, '付款主体'),
            'receive_entity': val_text(v, '收款主体'),
            'pay_account': val_text(v, '付款账户'),
            'approval_status': val_text(v, '审批状态'),
            'pay_status': val_text(v, '付款状态'),
            'is_planned': val_bool(v, '是否计划内'),
            'apply_date': val_date(v, '申请日期'),
            'plan_pay_date': val_date(v, '计划付款日期'),
            'pay_date': val_date(v, '付款日期'),
            'remark': val_text(v, '备注'),
        }
        # 冗余计算字段：待付金额
        aa = defaults.get('apply_amount') or 0
        pa = defaults.get('pay_amount') or 0
        if aa and pa is not None:
            defaults['pending_amount'] = round(aa - pa, 2)

        obj, created = Expense.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['expense'][rid] = obj.id

        link_data.append({
            'obj': obj,
            'invoice_in_rids': val_links(v, '关联销项'),
        })
        count += 1

    print(f'  付款/报销登记: {count} 条记录同步完成')
    return count, link_data


def sync_invoice_out():
    """同步销项发票登记"""
    print('[5/7] 同步销项发票登记...')
    records = fetch_records('PGcWic')
    count = 0
    rid_to_dbid['invoice_out'] = {}
    link_data = []

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')

        project_rids = val_links(v, '关联项目')
        project_id = None
        if project_rids and project_rids[0] in rid_to_dbid.get('project', {}):
            project_id = rid_to_dbid['project'][project_rids[0]]

        defaults = {
            'sheet_record_id': rid,
            'project_id': project_id,
            'invoice_code': val_text(v, '发票编号'),
            'invoice_type': val_text(v, '发票类型'),
            'invoice_status': val_text(v, '发票状态'),
            'billing_company': val_text(v, '开票公司'),
            'tax_rate': str(val_number(v, '税率') or val_text(v, '税率', '')),
            'amount_with_tax': val_number(v, '含税金额(元)'),
            'amount_without_tax': val_number(v, '不含税金额(元)'),
            'tax_amount': val_number(v, '税额(元)'),
            'invoice_date': val_date(v, '开票日期'),
            'remark': val_text(v, '备注'),
        }
        obj, created = InvoiceOut.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['invoice_out'][rid] = obj.id

        link_data.append({
            'obj': obj,
            'receivable_rids': val_links(v, '关联应收'),
        })
        count += 1

    print(f'  销项发票登记: {count} 条记录同步完成')
    return count, link_data


def sync_invoice_in():
    """同步进项发票登记"""
    print('[6/7] 同步进项发票登记...')
    records = fetch_records('tqVV8K')
    count = 0
    rid_to_dbid['invoice_in'] = {}
    link_data = []

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')

        project_rids = val_links(v, '关联项目')
        project_id = None
        if project_rids and project_rids[0] in rid_to_dbid.get('project', {}):
            project_id = rid_to_dbid['project'][project_rids[0]]

        expense_rids = val_links(v, '关联付款')
        expense_id = None
        if expense_rids and expense_rids[0] in rid_to_dbid.get('expense', {}):
            expense_id = rid_to_dbid['expense'][expense_rids[0]]

        defaults = {
            'sheet_record_id': rid,
            'project_id': project_id,
            'expense_id': expense_id,
            'dingtalk_id': val_text(v, '钉钉编号'),
            'invoice_last6': val_text(v, '发票号码后六位'),
            'submitter': val_text(v, '提交者'),
            'tax_amount': val_text(v, '税额'),
            'issue_date': val_date(v, '开具日期'),
        }
        obj, created = InvoiceIn.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['invoice_in'][rid] = obj.id
        count += 1

    print(f'  进项发票登记: {count} 条记录同步完成')
    return count


def sync_payment_record():
    """同步回款记录"""
    print('[7/7] 同步回款记录...')
    records = fetch_records('PAlZhk')
    count = 0
    rid_to_dbid['payment_record'] = {}

    for rec in records:
        v = rec.get('values', {})
        rid = rec.get('recordID', '')

        receivable_rids = val_links(v, '关联应收')
        receivable_id = None
        if receivable_rids and receivable_rids[0] in rid_to_dbid.get('receivable', {}):
            receivable_id = rid_to_dbid['receivable'][receivable_rids[0]]

        defaults = {
            'sheet_record_id': rid,
            'receivable_id': receivable_id,
            'payment_amount': val_number(v, '回款金额(元)'),
            'payment_date': val_date(v, '回款日期'),
            'payment_method': val_text(v, '回款方式'),
            'payment_serial': val_text(v, '回款流水号'),
            'account_name': val_text(v, '收款账户名称'),
            'bank_name': val_text(v, '开户行'),
            'account_number': val_text(v, '收款账号'),
            'is_overdue': val_bool(v, '是否逾期'),
            'remark': val_text(v, '备注'),
        }
        obj, created = PaymentRecord.objects.update_or_create(
            sheet_record_id=rid,
            defaults=defaults,
        )
        rid_to_dbid['payment_record'][rid] = obj.id
        count += 1

    print(f'  回款记录: {count} 条记录同步完成')
    return count


def sync_m2m_links(project_links, receivable_links, expense_links, invoice_out_links):
    """同步多对多关联表"""
    print('[关联] 同步多对多关联表...')

    # 项目 ↔ 客户
    pc_count = 0
    for ld in project_links:
        for crid in ld['customer_rids']:
            cid = rid_to_dbid.get('customer', {}).get(crid)
            if cid:
                ProjectCustomer.objects.get_or_create(
                    project_id=ld['obj'].id, customer_id=cid
                )
                pc_count += 1

    # 项目 ↔ 销项发票
    pio_count = 0
    for ld in project_links:
        for iorid in ld['invoice_out_rids']:
            ioid = rid_to_dbid.get('invoice_out', {}).get(iorid)
            if ioid:
                ProjectInvoiceOut.objects.get_or_create(
                    project_id=ld['obj'].id, invoice_out_id=ioid
                )
                pio_count += 1

    # 项目 ↔ 报销
    pe_count = 0
    for ld in project_links:
        for erid in ld['expense_rids']:
            eid = rid_to_dbid.get('expense', {}).get(erid)
            if eid:
                ProjectExpense.objects.get_or_create(
                    project_id=ld['obj'].id, expense_id=eid
                )
                pe_count += 1

    # 项目 ↔ 进项发票
    pii_count = 0
    for ld in project_links:
        for iirid in ld['invoice_in_rids']:
            iid = rid_to_dbid.get('invoice_in', {}).get(iirid)
            if iid:
                ProjectInvoiceIn.objects.get_or_create(
                    project_id=ld['obj'].id, invoice_in_id=iid
                )
                pii_count += 1

    # 应收 ↔ 回款
    rp_count = 0
    for ld in receivable_links:
        for prid in ld['payment_rids']:
            pid = rid_to_dbid.get('payment_record', {}).get(prid)
            if pid:
                ReceivablePayment.objects.get_or_create(
                    receivable_id=ld['obj'].id, payment_record_id=pid
                )
                rp_count += 1

    # 应收 ↔ 销项发票
    rio_count = 0
    for ld in receivable_links:
        for iorid in ld['invoice_out_rids']:
            ioid = rid_to_dbid.get('invoice_out', {}).get(iorid)
            if ioid:
                ReceivableInvoiceOut.objects.get_or_create(
                    receivable_id=ld['obj'].id, invoice_out_id=ioid
                )
                rio_count += 1

    # 报销 ↔ 进项发票
    eii_count = 0
    for ld in expense_links:
        for iirid in ld['invoice_in_rids']:
            iid = rid_to_dbid.get('invoice_in', {}).get(iirid)
            if iid:
                ExpenseInvoiceIn.objects.get_or_create(
                    expense_id=ld['obj'].id, invoice_in_id=iid
                )
                eii_count += 1

    print(f'  项目↔客户:{pc_count} 项目↔销项:{pio_count} 项目↔报销:{pe_count} 项目↔进项:{pii_count}')
    print(f'  应收↔回款:{rp_count} 应收↔销项:{rio_count} 报销↔进项:{eii_count}')


# ─── 主流程 ─────────────────────────────────────

def main():
    start = datetime.now()
    print(f'=== 腾讯文档数据同步开始 {start.strftime("%Y-%m-%d %H:%M:%S")} ===\n')

    # 1. 客户（最先同步，无依赖）
    c = sync_customer()

    # 2. 项目（依赖客户）
    p, project_links = sync_project()

    # 3. 应收（依赖项目）
    r, receivable_links = sync_receivable()

    # 4. 报销（依赖项目）
    e, expense_links = sync_expense()

    # 5. 销项发票（依赖项目）
    io, invoice_out_links = sync_invoice_out()

    # 6. 进项发票（依赖项目+报销）
    ii = sync_invoice_in()

    # 7. 回款记录（依赖应收）
    pr = sync_payment_record()

    # 8. 多对多关联
    sync_m2m_links(project_links, receivable_links, expense_links, invoice_out_links)

    elapsed = (datetime.now() - start).total_seconds()
    total = c + p + r + e + io + ii + pr
    print(f'\n=== 同步完成！共 {total} 条记录，耗时 {elapsed:.1f}s ===')
    print(f'  客户:{c} 项目:{p} 应收:{r} 报销:{e} 销项:{io} 进项:{ii} 回款:{pr}')


if __name__ == '__main__':
    main()
