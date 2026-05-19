from rest_framework import viewsets
from .models import Receivable
from .serializers import ReceivableSerializer


class ReceivableViewSet(viewsets.ModelViewSet):
    """应收账款 CRUD"""
    queryset = Receivable.objects.select_related('project').all()
    serializer_class = ReceivableSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project_id')
        month = self.request.query_params.get('month')
        keyword = self.request.query_params.get('search', '')
        s = self.request.query_params.get('status', '')
        if project_id:
            qs = qs.filter(project_id=project_id)
        if month:
            qs = qs.filter(month=month)
        if keyword:
            qs = qs.filter(project__project_name__icontains=keyword) | qs.filter(project__project_code__icontains=keyword)
        if s:
            qs = qs.filter(status=s)
        return qs
