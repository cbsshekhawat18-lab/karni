"""The permission matrix (ADR 0002, P5): where a grant came from, and revoked grants.

``RolePermission.origin`` says whether the sync (``declared``) or the matrix
(``matrix``) owns the row; the new ``none`` scope is a declared grant the
matrix revoked, kept so the next sync does not restore it. Existing rows
are ``declared``, which is what they were.
"""


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('karni_accounts', '0002_roles'),
    ]

    operations = [
        migrations.AddField(
            model_name='rolepermission',
            name='origin',
            field=models.CharField(choices=[('declared', 'Declared in KARNI_ROLES'), ('matrix', 'Set in the permission matrix')], default='declared', max_length=16),
        ),
        migrations.AlterField(
            model_name='rolepermission',
            name='scope',
            field=models.CharField(choices=[('all', 'All rows'), ('own', 'Own rows'), ('related', 'Rows related through a scope path'), ('custom', 'Rows a registered scope returns'), ('none', 'No rows (revoked in the permission matrix)')], default='all', max_length=16),
        ),
    ]
