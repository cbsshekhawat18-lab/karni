"""Per-user grants (experimental): the ``UserGrant`` table.

One row per grant to one user: a permission pattern and a scope written as in
``KARNI_ROLES``, the row ids the scope points at, an optional expiry, who gave
it and why. Rows count only while ``KARNI_USER_GRANTS`` is on. Nothing else
changes.
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('karni_accounts', '0008_terms_acceptance'),
        # Orders the user FKs after a swapped-in user model's app. A no-op
        # self-reference when the default karni user is kept.
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserGrant',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, editable=False, null=True)),
                ('permission', models.CharField(help_text='A KARNI_ROLES pattern: app_label.model:action, with * for either part.', max_length=200)),
                ('scope', models.CharField(default='all', help_text='all, own, related:<scope path key> or custom:<registered name>.', max_length=120)),
                ('targets', models.JSONField(blank=True, default=list, help_text='Row ids (for a related:<key> scope): the rows the grant points at.')),
                ('expires_at', models.DateTimeField(blank=True, db_index=True, help_text='Empty: the grant never expires.', null=True)),
                ('reason', models.CharField(blank=True, default='', max_length=255)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('granted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_grants', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'user grant',
                'verbose_name_plural': 'user grants',
                'ordering': ['-created_at'],
                'abstract': False,
                'default_manager_name': 'objects',
            },
        ),
    ]
