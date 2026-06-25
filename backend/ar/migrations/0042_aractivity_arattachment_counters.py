import os
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def migrate_collection_logs_to_activities(apps, schema_editor):
    """Copy existing ARCollectionLog rows into ARActivity (stage='dunning')."""
    ARCollectionLog = apps.get_model('ar', 'ARCollectionLog')
    ARActivity = apps.get_model('ar', 'ARActivity')
    ARRecord = apps.get_model('ar', 'ARRecord')

    # Map old log_type to new act_type (same values)
    batch = []
    for log in ARCollectionLog.objects.all():
        batch.append(ARActivity(
            ar_record_id=log.ar_record_id,
            stage='dunning',
            act_type=log.log_type,
            contact_person=log.contact_person,
            note=log.note,
            status=log.status,
            follow_up_date=log.follow_up_date,
            created_by_id=log.created_by_id,
            created_at=log.created_at,
            updated_at=log.updated_at,
        ))
    if batch:
        ARActivity.objects.bulk_create(batch, ignore_conflicts=False)

    # Update activity_count on ARRecord
    from django.db.models import Count
    for rec in ARRecord.objects.annotate(cnt=Count('activities')).filter(cnt__gt=0):
        ARRecord.objects.filter(pk=rec.pk).update(activity_count=rec.cnt)


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0041_agingbucketconfig'),
    ]

    operations = [
        # 1. New ARActivity table
        migrations.CreateModel(
            name='ARActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('stage', models.CharField(choices=[('reconciliation', '对账'), ('invoice', '开票'), ('collection', '回款'), ('dunning', '催款'), ('general', '通用')], db_index=True, default='dunning', max_length=20, verbose_name='阶段')),
                ('act_type', models.CharField(choices=[('call', '电话'), ('email', '邮件'), ('visit', '拜访'), ('meeting', '会议'), ('system', '系统事件'), ('note', '备注'), ('other', '其他')], default='call', max_length=10, verbose_name='类型')),
                ('contact_person', models.CharField(blank=True, default='', max_length=100, verbose_name='联系人')),
                ('note', models.TextField(blank=True, default='', verbose_name='内容')),
                ('status', models.CharField(choices=[('pending', '待回复'), ('in_progress', '跟进中'), ('resolved', '已解决'), ('no_response', '无响应')], default='in_progress', max_length=20, verbose_name='状态')),
                ('follow_up_date', models.DateField(blank=True, null=True, verbose_name='计划跟进日期')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('ar_record', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='ar.arrecord')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ar_activities', to='paikuan.paikuanuser')),
            ],
            options={'db_table': 'ar_activities', 'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='aractivity',
            index=models.Index(fields=['ar_record', 'stage', 'created_at'], name='ar_activiti_ar_reco_idx'),
        ),
        # 2. New ARAttachment table
        migrations.CreateModel(
            name='ARAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('stage', models.CharField(choices=[('reconciliation', '对账'), ('invoice', '开票'), ('collection', '回款'), ('dunning', '催款'), ('general', '通用')], default='general', max_length=20, verbose_name='阶段')),
                ('file', models.FileField(max_length=500, upload_to='', verbose_name='文件')),
                ('file_name', models.CharField(max_length=255, verbose_name='原始文件名')),
                ('file_size', models.IntegerField(default=0, verbose_name='文件大小(字节)')),
                ('mime_type', models.CharField(blank=True, default='', max_length=100, verbose_name='MIME类型')),
                ('thumb_path', models.CharField(blank=True, default='', max_length=500, verbose_name='缩略图相对路径')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ar_record', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='ar.arrecord')),
                ('activity', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attachments', to='ar.aractivity')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ar_attachments', to='paikuan.paikuanuser')),
            ],
            options={'db_table': 'ar_attachments', 'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='arattachment',
            index=models.Index(fields=['ar_record', 'stage', 'created_at'], name='ar_attachme_ar_reco_idx'),
        ),
        # 3. Add counter columns to ARRecord
        migrations.AddField(
            model_name='arrecord',
            name='activity_count',
            field=models.IntegerField(default=0, verbose_name='动态数'),
        ),
        migrations.AddField(
            model_name='arrecord',
            name='attachment_count',
            field=models.IntegerField(default=0, verbose_name='附件数'),
        ),
        # 4. Data migration: copy ARCollectionLog -> ARActivity
        migrations.RunPython(
            migrate_collection_logs_to_activities,
            migrations.RunPython.noop,
        ),
    ]
