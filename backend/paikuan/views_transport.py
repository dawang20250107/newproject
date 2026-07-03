"""运输事业部对账单业务域（从 paikuan/views.py 拆出）：
原表(21列/金额为负) 专用导入 / 零误差导出 / 单号复制。
共享助手从 views 引入；views 底部 re-export 本模块公开名，urls/tests 引用路径不变。"""
import datetime
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction, IntegrityError
from django.utils import timezone
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt

from paikuan.models import ApprovalRecord, Payment
from paikuan.list_filters import build_filter_q
from paikuan.views import (
    pk_required, err, ok, get_request_perms, can_write_dept, dept_filter,
    _read_import_rows, _payments_page_denied, _payments_filtered_qs,
    _build_excel_response, PAYMENT_FILTER_REGISTRY, G7_COPY_CAP,
)

# ── 运输事业部对账单 专用导入 / 导出 ────────────────────────────────────────────
# 运输事业部从自有系统导出的对账单结构与排款表完全不同（14 固定列、金额为负）。
# 导入（审批管理）：逐行转为「已通过」审批记录（金额取绝对值、映射部门/收款方），原始整行
#       存 ext_raw，以「对账单号」为唯一键去重。之后由用户在审批管理手动排款进入付款管理。
# 导出（付款管理）：按勾选 / 筛选取回已排款的运输付款记录，从来源审批的 ext_raw 原样还原原表，
#       逐字零误差，仅把「状态」列改写为「已结算」（限系统内已付清行），供回传运输自有系统。
TRANSPORT_SOURCE = 'transport'
TRANSPORT_DEPT = '运输事业部'
# 运输对账单原表头（顺序即导出列顺序，必须与来源系统完全一致）
TRANSPORT_HEADERS = [
    '序号', '所属组织', '对账单号', '运单号', '项目名称', '收支方式', '对账对象', '联系电话',
    '实际对账金额', '对账时间', '状态', '创建人', '创建时间', '备注', '单据类别',
    '账单调整', '对账金额', '结算方式', '实对网货服务费合计', '实对网货费用合计', '开户人',
]
TRANSPORT_KEY_COL = '对账单号'      # 去重唯一键
TRANSPORT_AMOUNT_COL = '实际对账金额'  # 取绝对值作为申请金额（已含账单调整的最终额）
TRANSPORT_STATUS_COL = '状态'       # 导出时改写为「已结算」的列
TRANSPORT_SEQ_COL = '序号'          # 导出时按输出行重排为 1,2,3…（不沿用原表零散序号）
TRANSPORT_SETTLED_LABEL = '已结算'
# 汇总/合计行标记：运输原表末尾常有一行「合计」（序号=合计、对账单号=「681 条」、
# 金额=全表总额）。它不是真实对账单，若不识别会被当成一条巨额付款导入。
TRANSPORT_SUMMARY_MARKERS = ('合计', '总计', '小计', '合 计')
# 运输对账单正常应为「已通过」（对账通过、待我方付款）。下列源状态不可导入：
#   已结算/已完成类 → 源系统已结算，再导入排款会重复付款；
#   作废/取消/驳回类 → 单据已失效，不应付款。
# 精确匹配（规范化后），避免误伤「未结算/待结算」（含「结算」二字但应可导入）。
TRANSPORT_BLOCK_SETTLED = {'已结算', '已完成', '已支付', '已付款', '结算完成', '付款完成'}
TRANSPORT_BLOCK_VOID = {'已作废', '作废', '已取消', '取消', '已关闭', '已驳回', '驳回', '已拒绝', '拒绝', '无效'}


def _transport_json_safe(v):
    """把 openpyxl 读出的单元格值转成 JSON 可序列化值（存入 ext_raw JSONField）。
    运输原表「对账时间/创建时间」是真正的 datetime → 直接入 JSON 会报
    "Object of type datetime is not JSON serializable"。统一转贴近原表的字符串。"""
    if isinstance(v, datetime.datetime):
        # 纯日期格（零点）只留日期，避免凭空多出 00:00:00；否则保留到秒
        if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0):
            return v.strftime('%Y-%m-%d')
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, datetime.date):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, datetime.time):
        return v.strftime('%H:%M:%S')
    if isinstance(v, Decimal):
        return float(v)
    return v


def _transport_analyze(rows, existing_bills):
    """运输对账单逐行分类（只读，不落库）。导入与导入预检共用同一口径，杜绝漂移。
    返回各类别清单 + 列漂移信息。existing_bills：系统内已存在的 ext_bill_no 集合。"""
    header = [str(h).strip() if h is not None else '' for h in rows[0]]
    pos = {h: i for i, h in enumerate(header)}
    report = {
        'header': header,
        'missing_required': [c for c in (TRANSPORT_KEY_COL, TRANSPORT_AMOUNT_COL) if c not in pos],
        # 列漂移：原表新增的非标准列 / 缺失的标准列
        'extra_columns': [h for h in header if h and h not in TRANSPORT_HEADERS],
        'missing_standard': [h for h in TRANSPORT_HEADERS if h not in pos],
        'total': 0,
        'ok': [], 'settled': [], 'voided': [],
        'dup_in_file': [], 'dup_in_system': [], 'bad': [], 'summary_rows': [],
    }
    if report['missing_required']:
        return report

    def cell(row, col):
        i = pos.get(col)
        return row[i] if (i is not None and i < len(row)) else None

    seen = set()
    for rn, row in enumerate(rows[1:], start=2):
        if row is None or all(v is None or str(v).strip() == '' for v in row):
            continue
        # 合计/汇总行识别：序号或对账单号含「合计/总计/小计」，或对账单号形如「681 条」
        # （条数统计而非真实单号）。这类行跳过——不计入总数、不导入，避免全表总额被当成
        # 一条巨额付款。真实对账单号形如 ZD202605310006，绝不含「条」或「合计」。
        seq_probe = str(cell(row, TRANSPORT_SEQ_COL) or '').strip()
        bill_probe = str(cell(row, TRANSPORT_KEY_COL) or '').strip()
        if (any(m in seq_probe for m in TRANSPORT_SUMMARY_MARKERS)
                or any(m in bill_probe for m in TRANSPORT_SUMMARY_MARKERS)
                or re.match(r'^\d[\d,]*\s*条$', bill_probe)):
            report.setdefault('summary_rows', []).append({'row': rn, 'bill_no': bill_probe})
            continue
        report['total'] += 1
        bill_no = str(cell(row, TRANSPORT_KEY_COL) or '').strip()
        if not bill_no:
            report['bad'].append({'row': rn, 'bill_no': '', 'reason': '缺少对账单号'})
            continue
        if bill_no in seen:
            report['dup_in_file'].append({'row': rn, 'bill_no': bill_no})
            continue
        if bill_no in existing_bills:
            report['dup_in_system'].append({'row': rn, 'bill_no': bill_no})
            continue
        src_status = str(cell(row, TRANSPORT_STATUS_COL) or '').strip()
        if src_status in TRANSPORT_BLOCK_SETTLED:
            report['settled'].append({'row': rn, 'bill_no': bill_no, 'src_status': src_status})
            continue
        if src_status in TRANSPORT_BLOCK_VOID:
            report['voided'].append({'row': rn, 'bill_no': bill_no, 'src_status': src_status})
            continue
        amt_raw = cell(row, TRANSPORT_AMOUNT_COL)
        try:
            amount = abs(Decimal(str(amt_raw).strip()))
        except (InvalidOperation, AttributeError, TypeError):
            report['bad'].append({'row': rn, 'bill_no': bill_no, 'reason': f'金额「{amt_raw}」无法解析'})
            continue
        if amount <= 0:
            report['bad'].append({'row': rn, 'bill_no': bill_no, 'reason': '金额为 0'})
            continue
        raw = {h: (_transport_json_safe(row[i]) if i < len(row) else None) for h, i in pos.items()}
        report['ok'].append({
            'row': rn, 'bill_no': bill_no, 'src_status': src_status,
            # 字段映射（运输原表列 → 我方记录字段），各列按目标字段 max_length 截断：
            #   对账单号 → 审批编号(approval_number，唯一键/复制/批量筛选主键)
            #   运单号   → G7编号(g7_number，可多张以「/」拼接)
            #   项目名称 → 项目简称(project_short_name)
            #   备注     → 备注(notes)
            #   收支方式 → 收款主体(payee)、对账对象 → 摘要(summary)
            'approval_number': bill_no[:21],
            'g7': str(cell(row, '运单号') or '').strip()[:255],
            'project_short_name': str(cell(row, '项目名称') or '').strip()[:100],
            'notes': str(cell(row, '备注') or '').strip()[:500],
            'payee': (str(cell(row, '收支方式') or '').strip() or bill_no)[:200],
            'summary': (str(cell(row, '对账对象') or '').strip() or f'运输对账 {bill_no}')[:500],
            'org': str(cell(row, '所属组织') or '').strip(),
            'amount': amount, 'raw': raw,
        })
        seen.add(bill_no)
    return report


def _transport_read_for_analyze(request):
    """运输导入/预检共用的鉴权 + 取文件 + 读行 + 取已存在单号。
    成功返回 (rows, existing_bills, None)；失败返回 (None, None, err_response)。"""
    perms = get_request_perms(request)
    if perms is not None:
        if not perms['pages'].get('approval_records', True):
            return None, None, err('无审批记录访问权限', 403, 403)
        if not perms.get('can_create'):
            return None, None, err('无新增权限', 403, 403)
    if not can_write_dept(request, TRANSPORT_DEPT):
        return None, None, err(f'无权操作部门"{TRANSPORT_DEPT}"', 403, 403)
    upload = request.FILES.get('file')
    if not upload:
        return None, None, err('请上传文件（.xlsx / .csv）')
    if upload.size > 5 * 1024 * 1024:
        return None, None, err('文件过大，请确认文件不超过5MB')
    rows, ferr = _read_import_rows(upload)
    if ferr:
        return None, None, err(ferr)
    if not rows or len(rows) < 2:
        return None, None, err('文件为空或缺少数据行')
    existing = set(ApprovalRecord.objects.filter(ext_source=TRANSPORT_SOURCE)
                   .values_list('ext_bill_no', flat=True))
    return rows, existing, None


@csrf_exempt
@pk_required()
def transport_import_precheck(request):
    """POST（审批管理）— 运输对账单导入预检：只读分析，返回逐类详单供前端确认。
    覆盖：将导入 / 源已结算（防重复付款）/ 源已作废 / 文件内重复 / 系统内重复 /
    数据异常 / 列漂移（新增列、缺标准列）。不落库。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    rows, existing, resp = _transport_read_for_analyze(request)
    if resp:
        return resp
    report = _transport_analyze(rows, existing)
    if report['missing_required']:
        return err(f'运输对账单缺少必要列：{"、".join(report["missing_required"])}。请直接上传运输系统导出的原始表')

    def slim(i):
        return {'row': i['row'], 'bill_no': i['bill_no'],
                'payee': i['payee'], 'amount': str(i['amount']), 'src_status': i['src_status']}
    return ok({
        'total': report['total'],
        'will_import': len(report['ok']),
        'ok_sample': [slim(i) for i in report['ok'][:100]],
        'settled': report['settled'],
        'voided': report['voided'],
        'dup_in_file': report['dup_in_file'],
        'dup_in_system': report['dup_in_system'],
        'bad': report['bad'],
        'summary_rows': report['summary_rows'],
        'extra_columns': report['extra_columns'],
        'missing_standard': report['missing_standard'],
    })


@csrf_exempt
@pk_required()
def transport_import(request):
    """POST（审批管理）— 运输对账单导入：原表 → 「已通过」审批记录（金额取绝对值），
    按对账单号去重。源已结算/已作废单据跳过（防重复付款）。导入后手动排款流转付款管理。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    rows, existing, resp = _transport_read_for_analyze(request)
    if resp:
        return resp
    report = _transport_analyze(rows, existing)
    if report['missing_required']:
        return err(f'运输对账单缺少必要列：{"、".join(report["missing_required"])}。请直接上传运输系统导出的原始表')

    results = {'created': 0, 'skipped': 0, 'duplicates': 0,
               'already_settled': 0, 'voided': 0, 'errors': [], 'created_ids': []}
    importer = getattr(getattr(request, 'pk_user', None), 'name', '') or '运输导入'
    for item in report['ok']:
        bill_no = item['bill_no']
        try:
            with transaction.atomic():
                _rec_new = ApprovalRecord.objects.create(
                    created_by_id=request.pk_uid, applicant=importer,
                    department=TRANSPORT_DEPT, secondary_dept=item['org'],
                    approval_number=item['approval_number'],  # 审批编号 ← 对账单号
                    g7_number=item['g7'],                     # G7编号 ← 运单号
                    project_short_name=item['project_short_name'],  # 项目简称 ← 项目名称
                    summary=item['summary'][:500], notes=item['notes'],
                    amount=item['amount'], payee=item['payee'], status='approved',
                    ext_source=TRANSPORT_SOURCE, ext_bill_no=bill_no, ext_raw=item['raw'],
                )
            results['created'] += 1
            results['created_ids'].append(_rec_new.id)   # 供前端「一键排款」直达
        except IntegrityError:
            # DB 兜底唯一约束命中（并发）→ 计为重复
            results['duplicates'] += 1
            results['skipped'] += 1
        except Exception as e:
            results['errors'].append(f'第{item["row"]}行: 对账单 {bill_no} 保存失败 ({e})')
            results['skipped'] += 1

    # 汇总各跳过类别（与预检同口径）
    results['duplicates'] += len(report['dup_in_file']) + len(report['dup_in_system'])
    results['already_settled'] = len(report['settled'])
    results['voided'] = len(report['voided'])
    results['skipped'] += (len(report['dup_in_file']) + len(report['dup_in_system'])
                           + len(report['settled']) + len(report['voided']) + len(report['bad']))
    for s in report['settled']:
        results['errors'].append(
            f'第{s["row"]}行: 对账单 {s["bill_no"]} 源状态「{s["src_status"]}」已结算，跳过以防重复付款')
    for v in report['voided']:
        results['errors'].append(
            f'第{v["row"]}行: 对账单 {v["bill_no"]} 源状态「{v["src_status"]}」已作废/取消，跳过')
    for b in report['bad']:
        results['errors'].append(f'第{b["row"]}行: 对账单 {b["bill_no"] or "(空)"} {b["reason"]}，已跳过')
    for s in report['summary_rows']:
        results['errors'].append(f'第{s["row"]}行: 合计/汇总行（对账单号「{s["bill_no"]}」），已跳过')
    results['summary_rows'] = len(report['summary_rows'])

    parts = [f'成功导入 {results["created"]} 条（已建为「审批通过」记录，请在审批管理排款）']
    if results['duplicates']:
        parts.append(f'跳过重复 {results["duplicates"]} 条')
    if results['already_settled']:
        parts.append(f'跳过源已结算 {results["already_settled"]} 条（防重复付款）')
    if results['voided']:
        parts.append(f'跳过源已作废/取消 {results["voided"]} 条')
    if report['summary_rows']:
        parts.append(f'跳过合计行 {len(report["summary_rows"])} 条')
    if report['bad']:
        parts.append(f'跳过异常 {len(report["bad"])} 条')
    results['message'] = '；'.join(parts)
    return ok(results)


@csrf_exempt
@pk_required()
def transport_export(request):
    """GET（付款管理）— 运输对账单导出：按 ids（勾选付款记录）/ 筛选取回已排款的运输付款，
    从来源审批的 ext_raw 原样还原原表，仅把状态列改为「已结算」（限已付清行）。零误差回传。"""
    return _transport_export_core(request)


def _transport_export_core(request, export_cap=5000):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import Workbook
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    # 运输付款 = 来源审批为运输导入的付款记录（经手动排款流转而来）；排除回收站
    qs = Payment.objects.filter(approval__ext_source=TRANSPORT_SOURCE, deleted_at__isnull=True)
    qs = dept_filter(qs, request)
    qs = qs.select_related('approval').prefetch_related('installments')

    # 勾选导出优先：ids=逗号分隔的付款记录主键
    ids_raw = (request.GET.get('ids') or '').strip()
    if ids_raw:
        try:
            ids = [int(x) for x in ids_raw.split(',') if x.strip()]
        except ValueError:
            return err('ids 参数格式有误')
        qs = qs.filter(id__in=ids)
    else:
        # 否则走列表同款筛选（日期 / 关键词 / 列头筛选）
        start = request.GET.get('start_date', '').strip()
        end = request.GET.get('end_date', '').strip()
        q_str = request.GET.get('q', '').strip()
        if start:
            qs = qs.filter(planned_date__gte=start)
        if end:
            qs = qs.filter(planned_date__lte=end)
        if q_str:
            qs = qs.filter(
                Q(payee__icontains=q_str) | Q(approval__ext_bill_no__icontains=q_str) |
                Q(secondary_dept__icontains=q_str) | Q(notes__icontains=q_str)
            )
        fq, fq_distinct = build_filter_q(request.GET.get('filters', ''), PAYMENT_FILTER_REGISTRY)
        if fq:
            qs = qs.filter(fq)
            if fq_distinct:
                qs = qs.distinct()

    payments = list(qs)
    if not payments:
        return err('没有可导出的运输对账记录（请先在审批管理排款，再勾选付款记录或调整筛选）')
    if len(payments) > export_cap:
        return err(f'当前结果共 {len(payments)} 条，超出导出上限（{export_cap} 条），请缩小范围')

    # 一条审批（一张对账单）↔ 一条付款汇总记录；按对账单号去重，保证一单一行
    by_bill = {}
    for p in payments:
        rec = p.approval
        if rec is None or not isinstance(rec.ext_raw, dict) or not rec.ext_raw:
            continue
        key = rec.ext_bill_no or rec.id
        # 同单多条付款（理论上不会）取已结算优先
        if key not in by_bill or (p.status == 'settled' and by_bill[key].status != 'settled'):
            by_bill[key] = p
    rows_out = list(by_bill.values())
    if not rows_out:
        return err('选中的付款记录没有可还原的运输对账原始数据')

    # ── 导出统一为「标准表」：无论导入表列多列少，导出一律补齐为标准结构 ──
    #   · 标准列：始终按 TRANSPORT_HEADERS 全列、固定列序输出。
    #       - 列少的导入（缺标准列）→ 缺失列补空白单元，仍是完整标准表；
    #       - 列序乱（生产库 jsonb 不保证键序）→ 强制按标准列序，不漂移。
    #   · 非标准额外列：标准列之后，按「所有行」首次出现顺序并集追加，避免丢数据
    #       （列多的导入不丢列，但标准块永远在前、结构稳定、可被运输系统原样回导）。
    all_raws = [(r.approval.ext_raw or {}) for r in rows_out]
    canonical = list(TRANSPORT_HEADERS)        # 始终输出全部标准列（缺失留空）
    seen_cols = set(canonical)
    extras = []
    for raw in all_raws:
        for k in raw.keys():
            if k not in seen_cols:
                seen_cols.add(k)
                extras.append(k)
    headers = canonical + extras
    if TRANSPORT_STATUS_COL not in headers:
        headers.append(TRANSPORT_STATUS_COL)

    wb = Workbook()
    ws = wb.active
    ws.title = '运输对账单'
    # 零误差还原：表头为原表纯文本，不施加任何品牌底色/字体样式（与来源系统原表一致，
    # 仅状态列的「值」可改写）。导出 = 原表逐字 + 已结算行状态列改为「已结算」。
    for ci, h in enumerate(headers, 1):
        ws.cell(row=1, column=ci, value=h)

    _FORMULA_CHARS = ('=', '+', '@')

    def _safe(v):
        # Excel 注入防护：仅对会被当成公式的纯文本前缀加引号，不动数字 → 不改变数值精度
        if isinstance(v, str) and v and v[0] in _FORMULA_CHARS:
            return "'" + v
        return v

    for ri, p in enumerate(rows_out, start=2):
        raw = p.approval.ext_raw
        settled = p.status == 'settled'
        for ci, h in enumerate(headers, 1):
            if h == TRANSPORT_SEQ_COL:
                # 序号按导出行顺序重排 1,2,3…：导出常是勾选/筛选/去重后的子集，
                # 沿用原表零散序号会断号，统一从 1 连续编号更规范。
                val = ri - 1
            elif h == TRANSPORT_STATUS_COL:
                # 状态列以「我方结算」为准（这是导出存在的意义）：
                #   已结算 → 写「已结算」；
                #   未结算 → 保留源原值（零误差）；但若源原值本身就是「已结算类」
                #   （历史遗留：在导入状态校验之前导入的脏数据），不沿用以免谎报已结算，
                #   改写为明确的「未结算」，杜绝「我方未付却显示已结算」的错配。
                if settled:
                    val = TRANSPORT_SETTLED_LABEL
                else:
                    orig = raw.get(h)
                    val = '未结算' if str(orig or '').strip() in TRANSPORT_BLOCK_SETTLED else orig
            else:
                val = raw.get(h)
            # 空单元格统一还原为空字符串，与来源系统原表表示一致（避免 None/'' 表象差异）
            if val is None:
                val = ''
            ws.cell(row=ri, column=ci, value=_safe(val))

    for col in ws.columns:
        max_len = max((len(str(c.value or '')) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 36)

    today = timezone.localdate().strftime('%Y%m%d')
    # 运输导出零误差还原：保留其自带的更窄逐格防护（仅 = + @），不施加 chokepoint 全表扫描，
    # 以免给以「-」开头的原始文本前置单引号、破坏与运输系统的原样回导契约。
    return _build_excel_response(wb, f'运输对账单_已结算_{today}.xlsx', formula_guard=False)


# ── 异步导出（大数据量后台任务）──────────────────────────────────────────────
# 同步导出上限 5000 行，超出改后台异步生成：前端建任务→轮询状态→完成后下载。
# 文件字节存 ExportJob.file_data（DB），跨 gunicorn worker 共享，无需 Redis/Celery。


@pk_required()
def transport_g7_numbers(request):
    """运输专用：返回所选(ids)/当前筛选口径下付款记录的 审批编号（=对账单号）去重列表，
    供前端以「+」或空格连接复制到剪贴板。跨页全量，不受分页限制。上限 G7_COPY_CAP。
    注：运输映射调整后「单号」对应审批编号（对账单号），不再取 G7编号（现为运单号）。"""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    ids_raw = (request.GET.get('ids') or '').strip()
    if ids_raw:
        try:
            ids = [int(x) for x in ids_raw.split(',') if x.strip()]
        except ValueError:
            return err('ids 参数格式有误')
        qs = dept_filter(Payment.objects.filter(pk__in=ids, deleted_at__isnull=True), request)
    else:
        qs, _ = _payments_filtered_qs(request)
    # 保序去重（清空排序以规避 DISTINCT/ORDER BY 跨库差异；顺序对拼接用途不敏感）
    seen, nums = set(), []
    for no in qs.order_by().values_list('approval_number', flat=True).iterator():
        no = (no or '').strip()
        # 跳过空/占位（全 0）审批编号
        if not no or set(no) == {'0'} or no in seen:
            continue
        seen.add(no)
        nums.append(no)
        if len(nums) >= G7_COPY_CAP:
            break
    return ok({'numbers': nums, 'count': len(nums), 'capped': len(nums) >= G7_COPY_CAP})
