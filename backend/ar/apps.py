from django.apps import AppConfig


class ArConfig(AppConfig):
    name = 'ar'
    verbose_name = '应收账款'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        import ar.signals  # noqa: F401
