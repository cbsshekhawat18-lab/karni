"""The tree scope (experimental): ``tree`` among a role grant's scopes.

``RolePermission.scope`` takes ``tree`` (its ``scope_path`` is the path to a
tree model), and the help texts of ``UserGrant.scope`` and ``targets`` name
``tree:<path>``. No column changes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('karni_accounts', '0009_user_grant'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolepermission',
            name='scope',
            field=models.CharField(choices=[('all', 'All rows'), ('own', 'Own rows'), ('related', 'Rows related through a scope path'), ('custom', 'Rows a registered scope returns'), ('tree', "Rows under the user's nodes of a tree"), ('none', 'No rows (revoked in the permission matrix)')], default='all', max_length=16),
        ),
        migrations.AlterField(
            model_name='usergrant',
            name='scope',
            field=models.CharField(default='all', help_text='all, own, related:<scope path key>, custom:<registered name> or tree:<path to a tree model>.', max_length=120),
        ),
        migrations.AlterField(
            model_name='usergrant',
            name='targets',
            field=models.JSONField(blank=True, default=list, help_text='Row ids (for a related:<key> or tree:<path> scope): the rows or nodes the grant points at.'),
        ),
    ]
