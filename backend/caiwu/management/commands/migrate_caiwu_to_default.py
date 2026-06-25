"""Copy all caiwu data from the legacy 'caiwu' DB into the 'default' DB.

Platform-integration stage 1: caiwu tables now live in the default database.
This command backfills the historical rows from the old standalone DB.

Idempotent: rows are matched by primary key and updated in place, so it is safe
to run repeatedly. Source ('caiwu') is read-only; nothing is deleted there.

Usage:
    python manage.py migrate_caiwu_to_default            # apply
    python manage.py migrate_caiwu_to_default --dry-run  # report only
"""
from django.core.management.base import BaseCommand
from django.db import connections, transaction

from caiwu.models import (
    CaiwuUser, L1Category, L2Category, L3Category,
    ImportBatch, FinancialEntry, CaiwuJobPermission,
)

# Order matters: parents before children (FK dependencies).
MODELS_IN_ORDER = [
    CaiwuUser, L1Category, L2Category, L3Category,
    ImportBatch, FinancialEntry, CaiwuJobPermission,
]

SOURCE = 'caiwu'
TARGET = 'default'


class Command(BaseCommand):
    help = 'Backfill caiwu rows from the legacy caiwu DB into the default DB.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be copied without writing.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']

        # Guard: if the legacy 'caiwu' connection is gone, nothing to do.
        if SOURCE not in connections:
            self.stdout.write(self.style.WARNING(
                f"No '{SOURCE}' database configured — nothing to migrate."))
            return

        # Guard: source tables must exist (skip cleanly on fresh installs).
        try:
            with connections[SOURCE].cursor() as cur:
                cur.execute("SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name='caiwu_user'")
                if cur.fetchone() is None:
                    self.stdout.write(self.style.WARNING(
                        f"Legacy '{SOURCE}' DB has no caiwu tables — skipping."))
                    return
        except Exception:
            # Non-sqlite backends: fall through and let per-model reads decide.
            pass

        totals = {}
        with transaction.atomic(using=TARGET):
            for Model in MODELS_IN_ORDER:
                created, updated = self._copy_model(Model, dry)
                totals[Model.__name__] = (created, updated)

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Dry-run summary:' if dry else 'Migration summary:'))
        for name, (c, u) in totals.items():
            self.stdout.write(f'  {name:22} +{c} new, ~{u} updated')
        if dry:
            self.stdout.write(self.style.WARNING(
                '\nDry run — no changes written. Re-run without --dry-run to apply.'))
        else:
            self.stdout.write(self.style.SUCCESS('\nDone.'))

    def _copy_model(self, Model, dry):
        """Copy one model's rows source→target, matching by pk. Returns (created, updated)."""
        fields = [f for f in Model._meta.concrete_fields]
        created = updated = 0

        try:
            src_rows = list(Model.objects.using(SOURCE).all())
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f'  {Model.__name__}: source read failed ({e}); skipped.'))
            return 0, 0

        existing_ids = set(Model.objects.using(TARGET).values_list('pk', flat=True))

        for obj in src_rows:
            is_new = obj.pk not in existing_ids
            if is_new:
                created += 1
            else:
                updated += 1
            if dry:
                continue
            # Preserve original pk and raw FK ids by copying attname values.
            data = {f.attname: getattr(obj, f.attname) for f in fields}
            # ImportBatch.uploaded_by now targets PaikuanUser; the legacy
            # CaiwuUser ids carried in the source rows don't map across, so
            # drop them rather than create dangling references.
            if Model is ImportBatch:
                data['uploaded_by_id'] = None
            Model.objects.using(TARGET).update_or_create(
                pk=obj.pk, defaults=data)

        self.stdout.write(
            f'  {Model.__name__:22} source={len(src_rows):5}  '
            f'+{created} new ~{updated} updated')
        return created, updated
