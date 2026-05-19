import logging, json
from decimal import Decimal
from django.http import JsonResponse
from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, serializers
from wxcloudrun.models import ProjectBase, ReceivableSource, ExpenseRecord

logger = logging.getLogger('wxcloudrun')


def to_f(v):
    try:
        return float(v or 0)
    except:
        return 0.0


def ok(data):
    return JsonResponse({'code': 0, 'data': data})


def err(msg, code=-1):
    return JsonResponse({'code': code, 'error': msg}, status=400)


def ds(qs, field):
    return float(qs.aggregate(s=Coalesce(Sum(field, output_field=DecimalField()), Decimal('0')))['s'] or 0)


# ─── 主页 & 通用 ──────────────────────────────────────────

def index(request):
    return JsonResponse({'code': 0, 'msg': 'KXT API Running', 'version': '2.0.0'})


# ─── 认证 API ──────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class AuthViewSet(viewsets.ViewSet):
    def login(self, request):
        username = request.data.get('username', '')
        password = request.data.get('password', '')
        if username == 'admin' and password == 'admin123':
            return JsonResponse({'code': 0, 'data': {'username': username, 'token': 'admin-token-kxt'}})
        return err('\u7528\u6237\u540d\u6216\u5bc6\u7801\u9519\u8bef', code=401)

    def logout(self, request):
        return ok({'msg': 'ok'})

    def me(self, request):
        return ok({'username': 'admin', 'role': 'admin'})


# ─── DRF Serializers ─────────────────────────────────────

class ProjectBaseSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='CONTRACT_NAME')
    project_alias = serializers.CharField(source='PROJECT_ALIAS')
    business_mode = serializers.CharField(source='BUSINESS_MODE')
    department = serializers.CharField(source='DEPARTMENT')
    manager_name = serializers.CharField(source='PROJECT_MANAGER')
    sales_contact = serializers.CharField(source='SALES_CONTACT')
    share_type = serializers.CharField(source='SHARE_TYPE')
    settlement_cycle = serializers.CharField(source='SETTLEMENT_CYCLE')
    reconciliation_period = serializers.CharField(source='RECONCILIATION_PERIOD')
    invoice_wait_period = serializers.CharField(source='INVOICE_WAIT_PERIOD')
    payment_period = serializers.CharField(source='PAYMENT_PERIOD')
    total_period = serializers.CharField(source='TOTAL_PERIOD')
    invoice_mode = serializers.CharField(source='INVOICE_MODE')

    class Meta:
        model = ProjectBase
        fields = ['id', 'project_name', 'project_alias', 'business_mode', 'department',
                  'manager_name', 'sales_contact', 'share_type', 'settlement_cycle',
                  'reconciliation_period', 'invoice_wait_period', 'payment_period',
                  'total_period', 'invoice_mode', 'created_at']


class ReceivableSourceSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='PROJECT_NAME')
    contract_name = serializers.CharField(source='CONTRACT_NAME')
    manager_name = serializers.CharField(source='PROJECT_MANAGER')
    month = serializers.DateField(source='BUSINESS_MONTH', format='%Y-%m')
    receivable_amount = serializers.DecimalField(source='ESTIMATED_RECEIVABLE', max_digits=14, decimal_places=2)
    received_amount = serializers.DecimalField(source='RECEIVED_AMOUNT', max_digits=14, decimal_places=2)
    unpaid_amount = serializers.DecimalField(source='TOTAL_UNPAID', max_digits=14, decimal_places=2)
    status = serializers.CharField(source='OVERDUE_STATUS')

    class Meta:
        model = ReceivableSource
        fields = ['id', 'project_name', 'contract_name', 'manager_name', 'month',
                  'receivable_amount', 'received_amount', 'unpaid_amount', 'status']


class ExpenseRecordSerializer(serializers.ModelSerializer):
    applicant = serializers.CharField(source='APPLICANT')
    dingtalk_id = serializers.CharField(source='DINGTALK_ID')
    summary = serializers.CharField(source='SUMMARY')
    project = serializers.CharField(source='PROJECT')
    planned_date = serializers.DateField(source='PLANNED_PAYMENT_DATE', format='%Y-%m-%d', required=False, allow_null=True)
    apply_amount = serializers.DecimalField(source='APPLICATION_AMOUNT', max_digits=14, decimal_places=2)
    paid_amount = serializers.DecimalField(source='PAYMENT_AMOUNT', max_digits=14, decimal_places=2)
    pay_date = serializers.DateField(source='PAYMENT_DATE', format='%Y-%m-%d', required=False, allow_null=True)
    payment_entity = serializers.CharField(source='PAYMENT_ENTITY')
    is_planned = serializers.BooleanField(source='IS_PLANNED')
    has_invoice = serializers.BooleanField(source='HAS_INVOICE')

    class Meta:
        model = ExpenseRecord
        fields = ['id', 'applicant', 'dingtalk_id', 'summary', 'project', 'planned_date',
                  'apply_amount', 'paid_amount', 'pay_date', 'payment_entity', 'is_planned', 'has_invoice']


# ─── DRF ViewSets ───────────────────────────────────────

class ProjectBaseViewSet(viewsets.ModelViewSet):
    permission_classes = []
    authentication_classes = []
    queryset = ProjectBase.objects.all()
    serializer_class = ProjectBaseSerializer

    def list(self, request):
        return project_list(request)

    def retrieve(self, request, pk=None):
        try:
            obj = self.get_queryset().get(pk=pk)
        except ProjectBase.DoesNotExist:
            return err('\u9879\u76ee\u4e0d\u5b58\u5728', code=404)
        serializer = self.get_serializer(obj)
        return ok(serializer.data)


class ReceivableSourceViewSet(viewsets.ModelViewSet):
    permission_classes = []
    authentication_classes = []
    queryset = ReceivableSource.objects.all()
    serializer_class = ReceivableSourceSerializer

    def list(self, request):
        return receivables_list(request)

    def retrieve(self, request, pk=None):
        try:
            obj = self.get_queryset().get(pk=pk)
        except ReceivableSource.DoesNotExist:
            return err('\u8bb0\u5f55\u4e0d\u5b58\u5728', code=404)
        serializer = self.get_serializer(obj)
        return ok(serializer.data)


class ExpenseRecordViewSet(viewsets.ModelViewSet):
    permission_classes = []
    authentication_classes = []
    queryset = ExpenseRecord.objects.all()
    serializer_class = ExpenseRecordSerializer

    def list(self, request):
        return payables_registrations_list(request)

    def retrieve(self, request, pk=None):
        try:
            obj = self.get_queryset().get(pk=pk)
        except ExpenseRecord.DoesNotExist:
            return err('\u8bb0\u5f55\u4e0d\u5b58\u5728', code=404)
        serializer = self.get_serializer(obj)
        return ok(serializer.data)


# ─── 仪表板 API ──────────────────────────────────────────

def dashboard_kpi(request):
    """
    GET /api/dashboard/kpi/
    三行KPI：新表字段映射
    """
    try:
        all_rs = ReceivableSource.objects.all()
        normal_rs = all_rs.filter(TOTAL_UNPAID=0)
        overdue_rs = all_rs.filter(OVERDUE_STATUS='\u903e\u671f')

        def calc(qs):
            total = ds(qs, 'ESTIMATED_RECEIVABLE')
            received = ds(qs, 'RECEIVED_AMOUNT')
            unpaid = ds(qs, 'TOTAL_UNPAID')
            rate = round(received / total * 100, 2) if total > 0 else 0
            return {
                'receivable': round(total, 2),
                'receivable_display': f'{round(total / 10000, 2)}',
                'received': round(received, 2),
                'received_display': f'{round(received / 10000, 2)}',
                'unpaid': round(unpaid, 2),
                'unpaid_display': f'{round(unpaid / 10000, 2)}',
                'completion_rate': rate,
            }

        row1 = calc(all_rs)
        row2 = calc(normal_rs)
        row3 = calc(overdue_rs)

        overdue_projects = all_rs.filter(OVERDUE_STATUS='\u903e\u671f').values('PROJECT_NAME').distinct().count()
        latest = all_rs.exclude(BUSINESS_MONTH=None).order_by('-BUSINESS_MONTH').first()
        update_time = str(latest.BUSINESS_MONTH)[:10] if latest and latest.BUSINESS_MONTH else ''

        return ok({
            'row1': row1,
            'row2': row2,
            'row3': row3,
            'total_projects': ProjectBase.objects.count(),
            'overdue_projects': overdue_projects,
            'update_time': update_time,
        })
    except Exception as e:
        logger.error(f'[KPI] {e}')
        return err(str(e))


def dashboard_abnormal_ranking(request):
    """
    GET /api/dashboard/abnormal-ranking/
    前端期望: [{manager_name, alert_count, total_abnormal}]
    """
    try:
        overdue_rs = ReceivableSource.objects.filter(OVERDUE_STATUS='\u903e\u671f')
        managers = {}
        for r in overdue_rs:
            key = r.PROJECT_MANAGER or '\u672a\u77e5'
            if key not in managers:
                managers[key] = {'count': 0, 'unpaid': 0.0}
            managers[key]['count'] += 1
            managers[key]['unpaid'] += to_f(r.TOTAL_UNPAID)

        data = sorted([
            {
                'manager_name': k,
                'alert_count': v['count'],
                'total_abnormal': round(v['unpaid'], 2),
            }
            for k, v in managers.items()
        ], key=lambda x: -x['total_abnormal'])[:20]

        return ok(data)
    except Exception as e:
        logger.error(f'[AbnormalRanking] {e}')
        return err(str(e))


def dashboard_unpaid_distribution(request):
    """
    GET /api/dashboard/unpaid-distribution/
    前端期望: [{name, value}] - 按项目维度的未收款
    """
    try:
        unpaid_rs = ReceivableSource.objects.filter(TOTAL_UNPAID__gt=0)
        proj_unpaid = {}
        for r in unpaid_rs:
            key = r.PROJECT_NAME or '\u672a\u77e5\u9879\u76ee'
            proj_unpaid[key] = proj_unpaid.get(key, 0) + to_f(r.TOTAL_UNPAID)

        data = sorted([
            {'name': k, 'value': round(v, 2)}
            for k, v in proj_unpaid.items()
        ], key=lambda x: -x['value'])[:20]

        return ok(data)
    except Exception as e:
        logger.error(f'[UnpaidDist] {e}')
        return err(str(e))


def dashboard_manager_comparison(request):
    """
    GET /api/dashboard/manager-comparison/
    前端期望: [{manager_name, receivable, received, unpaid, project_count, completion_rate}]
    """
    try:
        all_rs = ReceivableSource.objects.all()
        managers = {}
        for r in all_rs:
            key = r.PROJECT_MANAGER or '\u672a\u77e5'
            if key not in managers:
                managers[key] = {'receivable': 0.0, 'received': 0.0, 'unpaid': 0.0, 'projects': set()}
            managers[key]['receivable'] += to_f(r.ESTIMATED_RECEIVABLE)
            managers[key]['received'] += to_f(r.RECEIVED_AMOUNT)
            managers[key]['unpaid'] += to_f(r.TOTAL_UNPAID)
            managers[key]['projects'].add(r.PROJECT_NAME)

        data = sorted([
            {
                'manager_name': k,
                'receivable': round(v['receivable'], 2),
                'received': round(v['received'], 2),
                'unpaid': round(v['unpaid'], 2),
                'project_count': len(v['projects']),
                'completion_rate': round(v['received'] / v['receivable'] * 100, 2) if v['receivable'] > 0 else 0,
            }
            for k, v in managers.items()
        ], key=lambda x: -x['receivable'])

        return ok(data)
    except Exception as e:
        logger.error(f'[ManagerComparison] {e}')
        return err(str(e))


def dashboard_manager_detail(request):
    """
    GET /api/dashboard/manager-detail/?manager=<name>
    前端期望: {items: [{project_name, abnormal_amount, received_amount, unpaid_amount, days_overdue, status, record_date, sub_records}]}
    """
    try:
        import urllib.parse
        manager = urllib.parse.unquote(request.GET.get('manager', ''))
        if not manager:
            return err('\u7f3a\u5c11 manager \u53c2\u6570')

        records = ReceivableSource.objects.filter(PROJECT_MANAGER=manager)
        items = []
        seen = set()

        for r in records.order_by('PROJECT_NAME', '-BUSINESS_MONTH'):
            pname = r.PROJECT_NAME or ''
            if pname in seen:
                continue
            seen.add(pname)
            proj_recs = list(records.filter(PROJECT_NAME=pname).order_by('-BUSINESS_MONTH'))
            items.append({
                'project_name': pname,
                'abnormal_amount': round(sum(to_f(rr.ESTIMATED_RECEIVABLE) for rr in proj_recs), 2),
                'received_amount': round(sum(to_f(rr.RECEIVED_AMOUNT) for rr in proj_recs), 2),
                'unpaid_amount': round(sum(to_f(rr.TOTAL_UNPAID) for rr in proj_recs), 2),
                'days_overdue': 0,
                'status': proj_recs[0].OVERDUE_STATUS or 'normal',
                'record_date': str(proj_recs[0].BUSINESS_MONTH)[:10] if proj_recs[0].BUSINESS_MONTH else '',
                'sub_records': [
                    {
                        'month': str(rr.BUSINESS_MONTH)[:7] if rr.BUSINESS_MONTH else '',
                        'abnormal_amount': to_f(rr.ESTIMATED_RECEIVABLE),
                        'received_amount': to_f(rr.RECEIVED_AMOUNT),
                        'unpaid_amount': to_f(rr.TOTAL_UNPAID),
                        'status': rr.OVERDUE_STATUS or 'normal',
                    }
                    for rr in proj_recs
                ],
            })

        return ok({'items': items})
    except Exception as e:
        logger.error(f'[ManagerDetail] {e}')
        return err(str(e))


def dashboard_monthly_received_paid(request):
    """
    GET /api/dashboard/monthly-received-paid/
    月度已收 vs 已付对比
    """
    try:
        target_month = request.GET.get('month', '').strip()
        all_rs = ReceivableSource.objects.exclude(BUSINESS_MONTH=None)

        # 月度已收
        monthly = {}
        for r in all_rs:
            m = str(r.BUSINESS_MONTH)[:7]
            if m not in monthly:
                monthly[m] = {'received': 0.0, 'paid': 0.0}
            monthly[m]['received'] += to_f(r.RECEIVED_AMOUNT)

        # 已付：从 ExpenseRecord
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("""
                SELECT DATE_FORMAT(PLANNED_PAYMENT_DATE, '%%Y-%%m') as pay_month,
                       SUM(PAYMENT_AMOUNT) as paid
                FROM mp_expense_record
                WHERE PLANNED_PAYMENT_DATE IS NOT NULL AND PAYMENT_AMOUNT > 0
                GROUP BY pay_month
                ORDER BY pay_month
            """)
            paid_rows = {str(r[0])[:7]: float(r[1]) for r in cur.fetchall() if r[0]}

        for m, v in monthly.items():
            if m in paid_rows:
                monthly[m]['paid'] = paid_rows[m]
            else:
                monthly[m]['paid'] = 0.0
        for m in paid_rows:
            if m not in monthly:
                monthly[m] = {'received': 0.0, 'paid': paid_rows[m]}

        months = sorted(monthly.keys())
        if target_month:
            months = [m for m in months if m == target_month]

        result = [
            {'month': m, 'received': round(monthly[m]['received'], 2), 'paid': round(monthly[m]['paid'], 2)}
            for m in months
        ]

        total_received = sum(m['received'] for m in result)
        total_paid = sum(m['paid'] for m in result)

        return ok({
            'monthly_received': round(total_received, 2),
            'monthly_paid': round(total_paid, 2),
            'months': result,
        })
    except Exception as e:
        logger.error(f'[MonthlyReceivedPaid] {e}')
        return err(str(e))


# ─── 项目 API ──────────────────────────────────────────

def project_list(request):
    """
    GET /api/projects/
    按项目名聚合 ReceivableSource，返回去重项目列表
    page/page_size/keyword 参数
    """
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()

        all_rs = ReceivableSource.objects.all()
        if keyword:
            all_rs = all_rs.filter(
                Q(PROJECT_NAME__icontains=keyword) |
                Q(PROJECT_MANAGER__icontains=keyword) |
                Q(CONTRACT_NAME__icontains=keyword)
            )

        # 按 PROJECT_NAME 去重聚合
        seen = {}
        for r in all_rs.order_by('PROJECT_NAME', '-BUSINESS_MONTH'):
            pname = r.PROJECT_NAME or ''
            if pname not in seen:
                seen[pname] = {
                    'manager': r.PROJECT_MANAGER or '',
                    'status': r.OVERDUE_STATUS or 'normal',
                    'record_date': r.BUSINESS_MONTH,
                    'total_estimated': 0.0,
                    'total_received': 0.0,
                    'total_unpaid': 0.0,
                    'all_recs': [],
                }
            seen[pname]['total_estimated'] += to_f(r.ESTIMATED_RECEIVABLE)
            seen[pname]['total_received'] += to_f(r.RECEIVED_AMOUNT)
            seen[pname]['total_unpaid'] += to_f(r.TOTAL_UNPAID)
            seen[pname]['all_recs'].append(r)

        items_data = sorted(seen.items(), key=lambda x: -x[1]['total_unpaid'])
        total = len(items_data)
        offset = (page - 1) * page_size
        page_items = items_data[offset:offset + page_size]

        items = []
        for pname, info in page_items:
            all_recs = info['all_recs']
            sub_items = [
                {
                    'id': r.id,
                    'record_date': str(r.BUSINESS_MONTH)[:10] if r.BUSINESS_MONTH else '',
                    'manager_name': r.PROJECT_MANAGER or '',
                    'abnormal_amount': to_f(r.ESTIMATED_RECEIVABLE),
                    'received_amount': to_f(r.RECEIVED_AMOUNT),
                    'unpaid_amount': to_f(r.TOTAL_UNPAID),
                    'days_overdue': 0,
                    'status': r.OVERDUE_STATUS or 'normal',
                }
                for r in all_recs
            ]
            latest = all_recs[0]
            items.append({
                'project_name': pname,
                'manager_name': info['manager'],
                'status': info['status'],
                'record_date': str(info['record_date'])[:10] if info['record_date'] else '',
                'abnormal_amount': round(info['total_estimated'], 2),
                'received_amount': round(info['total_received'], 2),
                'unpaid_amount': round(info['total_unpaid'], 2),
                'days_overdue': 0,
                'has_detail': len(sub_items) > 1,
                'sub_items': sub_items,
            })

        return ok({
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': items,
        })
    except Exception as e:
        logger.error(f'[ProjectList] {e}')
        return err(str(e))


def project_detail(request, project_id):
    """
    GET /api/projects/<id>/
    """
    try:
        try:
            record = ReceivableSource.objects.get(id=project_id)
        except ReceivableSource.DoesNotExist:
            return err('\u9879\u76ee\u4e0d\u5b58\u5728', code=404)

        proj_recs = list(ReceivableSource.objects.filter(
            PROJECT_NAME=record.PROJECT_NAME
        ).order_by('-BUSINESS_MONTH'))

        receivable_history = [
            {
                'month': str(r.BUSINESS_MONTH)[:7] if r.BUSINESS_MONTH else '',
                'receivable_amount': to_f(r.ESTIMATED_RECEIVABLE),
                'received_amount': to_f(r.RECEIVED_AMOUNT),
                'status': r.OVERDUE_STATUS or 'normal',
            }
            for r in proj_recs
        ]

        return ok({
            'id': record.id,
            'project_name': record.PROJECT_NAME or '',
            'manager_name': record.PROJECT_MANAGER or '',
            'abnormal_amount': to_f(record.ESTIMATED_RECEIVABLE),
            'received_amount': to_f(record.RECEIVED_AMOUNT),
            'unpaid_amount': to_f(record.TOTAL_UNPAID),
            'days_overdue': 0,
            'status': record.OVERDUE_STATUS or 'normal',
            'record_date': str(record.BUSINESS_MONTH)[:10] if record.BUSINESS_MONTH else '',
            'receivable_history': receivable_history,
        })
    except Exception as e:
        logger.error(f'[ProjectDetail] {e}')
        return err(str(e))


# ─── ERP 项目 API ────────────────────────────────────────

def projects_erp_list(request):
    """GET /api/projects-erp/"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()
        qs = ProjectBase.objects.all()
        if keyword:
            qs = qs.filter(
                Q(CONTRACT_NAME__icontains=keyword) |
                Q(PROJECT_ALIAS__icontains=keyword) |
                Q(PROJECT_MANAGER__icontains=keyword)
            )
        total = qs.count()
        page_data = list(qs[(page-1)*page_size: page*page_size])
        items = [
            {
                'id': r.id,
                'project_name': r.CONTRACT_NAME or '',
                'project_alias': r.PROJECT_ALIAS or '',
                'business_mode': r.BUSINESS_MODE or '',
                'department': r.DEPARTMENT or '',
                'manager_name': r.PROJECT_MANAGER or '',
                'sales_contact': r.SALES_CONTACT or '',
                'share_type': r.SHARE_TYPE or '',
                'settlement_cycle': r.SETTLEMENT_CYCLE or '',
                'reconciliation_period': r.RECONCILIATION_PERIOD or '',
                'invoice_wait_period': r.INVOICE_WAIT_PERIOD or '',
                'payment_period': r.PAYMENT_PERIOD or '',
                'total_period': r.TOTAL_PERIOD or '',
                'invoice_mode': r.INVOICE_MODE or '',
                'created_at': str(r.created_at)[:10] if r.created_at else '',
            }
            for r in page_data
        ]
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[ProjectsERPList] {e}')
        return err(str(e))


def project_erp_detail(request, project_id):
    """GET /api/projects-erp/<id>/"""
    try:
        try:
            p = ProjectBase.objects.get(id=project_id)
        except ProjectBase.DoesNotExist:
            return err('\u9879\u76ee\u4e0d\u5b58\u5728', code=404)
        return ok({
            'id': p.id,
            'project_name': p.CONTRACT_NAME or '',
            'project_alias': p.PROJECT_ALIAS or '',
            'business_mode': p.BUSINESS_MODE or '',
            'department': p.DEPARTMENT or '',
            'manager_name': p.PROJECT_MANAGER or '',
            'sales_contact': p.SALES_CONTACT or '',
            'share_type': p.SHARE_TYPE or '',
            'settlement_cycle': p.SETTLEMENT_CYCLE or '',
            'reconciliation_period': p.RECONCILIATION_PERIOD or '',
            'invoice_wait_period': p.INVOICE_WAIT_PERIOD or '',
            'payment_period': p.PAYMENT_PERIOD or '',
            'total_period': p.TOTAL_PERIOD or '',
            'invoice_mode': p.INVOICE_MODE or '',
            'created_at': str(p.created_at)[:10] if p.created_at else '',
        })
    except Exception as e:
        logger.error(f'[ProjectERPDetail] {e}')
        return err(str(e))


def project_erp_summary(request):
    """GET /api/projects-erp/summary/"""
    try:
        total = ProjectBase.objects.count()
        managers = ProjectBase.objects.values('PROJECT_MANAGER').distinct().count()
        return ok({'total_projects': total, 'total_managers': managers, 'new_this_month': 0})
    except Exception as e:
        logger.error(f'[ProjectERPSummary] {e}')
        return err(str(e))


# ─── 应收账款 API ────────────────────────────────────────

def receivables_list(request):
    """GET /api/receivables/"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()
        qs = ReceivableSource.objects.all()
        if keyword:
            qs = qs.filter(
                Q(PROJECT_NAME__icontains=keyword) |
                Q(CONTRACT_NAME__icontains=keyword) |
                Q(PROJECT_MANAGER__icontains=keyword)
            )
        total = qs.count()
        page_data = list(qs[(page-1)*page_size: page*page_size])
        items = [
            {
                'id': r.id,
                'project_name': r.PROJECT_NAME or '',
                'contract_name': r.CONTRACT_NAME or '',
                'manager_name': r.PROJECT_MANAGER or '',
                'month': str(r.BUSINESS_MONTH)[:7] if r.BUSINESS_MONTH else '',
                'receivable_amount': to_f(r.ESTIMATED_RECEIVABLE),
                'received_amount': to_f(r.RECEIVED_AMOUNT),
                'unpaid_amount': to_f(r.TOTAL_UNPAID),
                'status': r.OVERDUE_STATUS or 'normal',
            }
            for r in page_data
        ]
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[ReceivablesList] {e}')
        return err(str(e))


# ─── 应付管理 API ────────────────────────────────────────

def payables_registrations_list(request):
    """GET /api/payables/registrations/"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()
        qs = ExpenseRecord.objects.all()
        if keyword:
            qs = qs.filter(
                Q(APPLICANT__icontains=keyword) |
                Q(PROJECT__icontains=keyword) |
                Q(SUMMARY__icontains=keyword)
            )
        total = qs.count()
        page_data = list(qs[(page-1)*page_size: page*page_size])
        items = [
            {
                'id': r.id,
                'applicant': r.APPLICANT or '',
                'dingtalk_id': r.DINGTALK_ID or '',
                'summary': r.SUMMARY or '',
                'project': r.PROJECT or '',
                'planned_date': str(r.PLANNED_PAYMENT_DATE)[:10] if r.PLANNED_PAYMENT_DATE else '',
                'apply_amount': to_f(r.APPLICATION_AMOUNT),
                'paid_amount': to_f(r.PAYMENT_AMOUNT),
                'pay_date': str(r.PAYMENT_DATE)[:10] if r.PAYMENT_DATE else '',
                'payment_entity': r.PAYMENT_ENTITY or '',
                'is_planned': bool(r.IS_PLANNED),
                'has_invoice': bool(r.HAS_INVOICE),
            }
            for r in page_data
        ]
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[PayablesList] {e}')
        return err(str(e))


def payables_registrations_summary(request):
    """GET /api/payables/registrations/summary/"""
    try:
        all_exp = list(ExpenseRecord.objects.all())
        total_apply = sum(to_f(r.APPLICATION_AMOUNT) for r in all_exp)
        total_paid = sum(to_f(r.PAYMENT_AMOUNT) for r in all_exp)
        paid_count = sum(1 for r in all_exp if r.IS_PLANNED)
        return ok({
            'total_apply': round(total_apply, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_apply - total_paid, 2),
            'total_count': len(all_exp),
            'paid_count': paid_count,
        })
    except Exception as e:
        logger.error(f'[PayablesSummary] {e}')
        return err(str(e))


# ─── 同步 API ────────────────────────────────────────

def sync_from_docs(request):
    """
    POST /api/sync/from-docs/
    从腾讯文档同步所有数据
    """
    if request.method != 'POST':
        return err('仅支持 POST 请求', code=405)
    try:
        from io import StringIO
        from django.core.management import call_command
        buf = StringIO()
        call_command('sync_from_docs', stdout=buf)
        output = buf.getvalue()
        logger.info(f'[SyncFromDocs] 同步完成: {output[:200]}')
        return ok({'message': '同步完成', 'output': output})
    except Exception as e:
        logger.error(f'[SyncFromDocs] {e}')
        return err(f'同步失败: {e}')
