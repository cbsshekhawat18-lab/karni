from django.apps import AppConfig


class CrmConfig(AppConfig):
    name = "crm"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from karni.accounts.roles import register_scope

        from crm.scopes import workspace_rows

        register_scope("workspace", workspace_rows)
