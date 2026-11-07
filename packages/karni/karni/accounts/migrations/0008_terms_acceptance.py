"""Terms acceptance (experimental): the ``TermsAcceptance`` table.

One row per user and accepted version of ``KARNI_TERMS``, unique per (user,
version) among live rows, with when, the client's IP, its user agent and what
the app sent about itself. The table is append-only. Nothing else changes.
"""

import django.db.models.deletion
import django.utils.timezone
import karni.fields
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('karni_accounts', '0007_login_code'),
        # Orders the user FK after a swapped-in user model's app. A no-op
        # self-reference when the default karni user is kept.
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TermsAcceptance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, editable=False, null=True)),
                ('version', models.CharField(max_length=100)),
                ('accepted_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=1024)),
                ('client', models.JSONField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='terms_acceptances', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'terms acceptance',
                'verbose_name_plural': 'terms acceptances',
                'ordering': ['-accepted_at'],
                'abstract': False,
                'default_manager_name': 'objects',
                'constraints': [karni.fields.LiveUniqueConstraint(fields=('user', 'version'), name='karni_termsacceptance_user_version')],
            },
        ),
    ]
