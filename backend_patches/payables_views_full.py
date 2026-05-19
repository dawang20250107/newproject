from rest_framework import viewsets
from .models import Payable
from .serializers import PayableSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import connection


class PayableViewSet(viewsets.ModelViewSet):
    """应付账款（未回款记录）CRUD - 对接 unpaid_records 表"""
    queryset = Payable.objects.all()
    serializer_class = PayableSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '')
        project_name = self.request.query_params.get('project_name', '')
        project_id = self.request.query_params.get('project_id')
        status_filter = self.request.query_params.get('status', '')
        manager_name = self.request.query_params.get('manager_name', '')

        if keyword:
            qs = qs.filter(project_name__icontains=keyword) | qs.filter(manager_name__icontains=keyword)
        if project_name:
            qs = qs.filter(project_name=project_name)
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if manager_name:
            qs = qs.filter(manager_name=manager_name)
        return qs


class PaymentRegistrationListView(APIView):
    """付款登记表 - 列表查询（直接SQL，无ORM依赖）"""

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        is_paid = request.query_params.get('is_paid', '').strip()
        source = request.query_params.get('source', '').strip()
        ordering = request.query_params.get('ordering', '-planned_date').strip()
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))

        where = ['1=1']
        params = []
        if search:
            where.append("(project_name LIKE %s OR applicant_name LIKE %s OR description LIKE %s)")
            p = f"%{search}%"
            params.extend([p, p, p])
        if is_paid in ('true', '1'):
            where.append("is_paid = 1")
        elif is_paid in ('false', '0'):
            where.append("is_paid = 0")
        if source:
            where.append("source_sheet = %s")
            params.append(source)

        ORDER_MAP = {
            '-planned_date': 'planned_date DESC',
            'planned_date': 'planned_date ASC',
            '-pending_amount': 'pending_amount DESC',
            'pending_amount': 'pending_amount ASC',
            '-apply_amount': 'apply_amount DESC',
            'apply_amount': 'apply_amount ASC',
            '-applicant_name': 'applicant_name',
            'applicant_name': 'applicant_name ASC',
        }
        order_str = ORDER_MAP.get(ordering, 'planned_date DESC')

        with connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM payment_registrations WHERE {' AND '.join(where)}", params)
            total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        data_sql = (
            f"SELECT id, applicant_name, invoice_no, description, project_name, "
            f"planned_date, apply_amount, paid_amount, pending_amount, pay_date, "
            f"is_paid, payment_manager, has_invoice, source_sheet, expense_summary, created_at "
            f"FROM payment_registrations "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY {order_str} "
            f"LIMIT %s OFFSET %s"
        )
        with connection.cursor() as cur:
            cur.execute(data_sql, params + [page_size, offset])
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                'id': r[0],
                'applicant_name': r[1],
                'invoice_no': r[2],
                'description': r[3],
                'project_name': r[4],
                'planned_date': r[5].isoformat() if r[5] else None,
                'apply_amount': float(r[6]) if r[6] else 0,
                'paid_amount': float(r[7]) if r[7] else 0,
                'pending_amount': float(r[8]) if r[8] else 0,
                'pay_date': r[9].isoformat() if r[9] else None,
                'is_paid': bool(r[10]),
                'payment_manager': r[11],
                'has_invoice': bool(r[12]),
                'source_sheet': r[13],
                'expense_summary': float(r[14]) if r[14] else 0,
                'created_at': r[15].isoformat() if r[15] else None,
            })

        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'results': results
        })


class PaymentRegistrationSummaryView(APIView):
    """付款登记表 - 汇总统计"""

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT source_sheet,
                       COUNT(*) as cnt,
                       COALESCE(SUM(pending_amount), 0) as total_pending,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       SUM(CASE WHEN is_paid=1 THEN 1 ELSE 0 END) as paid_count
                FROM payment_registrations
                GROUP BY source_sheet
            """)
            by_source = []
            for row in cur.fetchall():
                by_source.append({
                    'source': row[0], 'count': row[1],
                    'total_pending': float(row[2]),
                    'total_paid': float(row[3]),
                    'total_apply': float(row[4]),
                    'paid_count': row[5]
                })

            cur.execute("""
                SELECT
                    COUNT(*) as total_count,
                    SUM(CASE WHEN is_paid=0 THEN 1 ELSE 0 END) as unpaid_count,
                    COALESCE(SUM(pending_amount), 0) as total_pending,
                    COALESCE(SUM(paid_amount), 0) as total_paid,
                    COALESCE(SUM(apply_amount), 0) as total_apply
                FROM payment_registrations
            """)
            row = cur.fetchone()
            summary = {
                'total_count': row[0],
                'unpaid_count': row[1],
                'total_pending': float(row[2]),
                'total_paid': float(row[3]),
                'total_apply': float(row[4]),
            }

        return Response({'summary': summary, 'by_source': by_source})
