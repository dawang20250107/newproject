from rest_framework.views import APIView
from rest_framework.response import Response
from projects.models import Project
from receivables.models import Receivable
from payables.models import Payable
from django.db.models import Sum, Count
from django.db import connection
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class MonthlyReceivedPaidView(APIView):
    """
    月度已收 vs 已付对比
    - 已收: SUM(receivable_data.received_amount) GROUP BY month
    - 已付: SUM(payment_registrations.paid_amount) WHERE is_paid=1 GROUP BY month
    - 支持 month 参数筛选单月
    """

    def get(self, request):
        target_month = request.query_params.get('month', '').strip()

        # 已收: 从 receivable_data
        recv_qs = Receivable.objects.values('month').annotate(
            received=Sum('received_amount')
        ).order_by('month')

        # 已付: 从 payment_registrations (paid_amount)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT DATE_FORMAT(planned_date, '%%Y-%%m') as pay_month,
                       SUM(paid_amount) as paid
                FROM payment_registrations
                WHERE planned_date IS NOT NULL AND paid_amount > 0
                GROUP BY pay_month
                ORDER BY pay_month
            """)
            paid_rows = {r[0]: float(r[1]) for r in cur.fetchall()}

        # Merge
        months_map = {}
        for r in recv_qs:
            m = r['month']
            months_map.setdefault(m, {'month': m, 'received': 0.0, 'paid': 0.0})
            months_map[m]['received'] = float(r['received'] or 0)

        for m, p in paid_rows.items():
            months_map.setdefault(m, {'month': m, 'received': 0.0, 'paid': 0.0})
            months_map[m]['paid'] = p

        months = sorted(months_map.values(), key=lambda x: x['month'])

        if target_month:
            months = [m for m in months if m['month'] == target_month]

        total_received = sum(m['received'] for m in months)
        total_paid = sum(m['paid'] for m in months)

        return Response({
            'monthly_received': round(total_received, 2),
            'monthly_paid': round(total_paid, 2),
            'months': months,
        })
