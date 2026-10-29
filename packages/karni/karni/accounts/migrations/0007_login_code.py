"""Sign-in with a code sent by email (experimental): the ``LoginCode`` table.

One row per code sent, holding the address, the account that had it (if
any), an HMAC of the code, its expiry, its attempt count and when it was
used. The code itself is never stored. Nothing else changes.
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('karni_accounts', '0006_social_identity'),
        # Orders the user FK after a swapped-in user model's app. A no-op
        # self-reference when the default karni user is kept.
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginCode',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, editable=False, null=True)),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('code_hash', models.CharField(max_length=64)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='login_codes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'login code',
                'verbose_name_plural': 'login codes',
                'ordering': ['-created_at'],
                'abstract': False,
                'default_manager_name': 'objects',
            },
        ),
    ]
