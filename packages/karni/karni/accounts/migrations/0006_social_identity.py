"""Sign-in with an ID token (experimental): the ``SocialIdentity`` table.

One row per provider identity linked to a user, unique per (provider,
subject) among live rows, so a deleted link frees its subject. Nothing else
changes, and allauth's own ``SocialAccount`` table is untouched.
"""

import django.db.models.deletion
import karni.fields
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('karni_accounts', '0005_btree_gist'),
        # Orders the user FK after a swapped-in user model's app. A no-op
        # self-reference when the default karni user is kept.
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SocialIdentity',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, editable=False, null=True)),
                ('provider', models.CharField(max_length=32)),
                ('subject', models.CharField(max_length=255)),
                ('email_at_link', models.EmailField(blank=True, default='', max_length=254)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='social_identities', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'social identity',
                'verbose_name_plural': 'social identities',
                'ordering': ['provider', 'created_at'],
                'abstract': False,
                'default_manager_name': 'objects',
                'constraints': [karni.fields.LiveUniqueConstraint(fields=('provider', 'subject'), name='karni_socialidentity_provider_subject')],
            },
        ),
    ]
