"""The leaky part: it reaches into the CRM part three ways, which karni check refuses."""

from django.apps import apps


def deals() -> object:
    from crm.models import Deal

    return Deal.objects.all()


def deal_model() -> object:
    return apps.get_model("crm", "Deal")


DEAL = "crm.Deal"
