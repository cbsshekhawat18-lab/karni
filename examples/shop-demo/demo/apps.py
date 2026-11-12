from django.apps import AppConfig


class DemoConfig(AppConfig):
    """The public demo (see the package docstring)."""

    name = "demo"
    verbose_name = "Public demo"

    def ready(self) -> None:
        """The admin's sign-in page shows the demo login too (``demo/admin_login.html``).

        Karni's admin app gives the site its login page first, and this one
        extends it. While ``DEMO_MODE`` is off the page is Karni's unchanged.
        """
        from django.contrib import admin

        admin.site.login_template = "demo/admin_login.html"
