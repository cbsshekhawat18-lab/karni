"""Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.

Your own code goes in intel/models.py, in the subclass of each class here.
"""

from django.db import models
from karni.fields import CountryField, EmailField, MarkdownField, MoneyField
from karni.models import BaseModel, TreeModel


class Condition(TreeModel, BaseModel):
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    overview = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]

    class Karni:
        import_key = "code"
        search = {"fields": ["name"], "title": "name"}

    def __str__(self) -> str:
        return self.code


class Intervention(TreeModel, BaseModel):
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    overview = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]

    class Karni:
        import_key = "code"
        search = {"fields": ["name"], "title": "name"}

    def __str__(self) -> str:
        return self.code


class Company(BaseModel):
    name = models.CharField(max_length=200)
    country = CountryField()
    website = models.URLField(blank=True)
    summary = MarkdownField(blank=True)
    strategy = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]

    class Karni:
        import_key = "name"
        audit = True
        taxonomies = {"interventions": "intel.Intervention"}
        aggregate = {"group_by": ["country"], "metrics": ["count"]}
        search = {"fields": ["name"], "title": "name"}
        field_groups = {
            "Profile": ["name", "country", "website"],
            "Analysis": ["summary", "strategy"],
        }

    def __str__(self) -> str:
        return self.name


class Person(BaseModel):
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    company = models.ForeignKey("Company", on_delete=models.CASCADE)
    email = EmailField(unique=True)
    bio = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]

    class Karni:
        import_key = "email"
        search = {"fields": ["name"], "title": "name", "subtitle": "title"}

    def __str__(self) -> str:
        return self.name


class Trial(BaseModel):
    class Phase(models.TextChoices):
        PHASE_1 = "phase_1"
        PHASE_2 = "phase_2"
        PHASE_3 = "phase_3"
        PHASE_4 = "phase_4"
    class Status(models.TextChoices):
        RECRUITING = "recruiting"
        ACTIVE = "active"
        COMPLETED = "completed"
        TERMINATED = "terminated"

    code = models.CharField(max_length=30)
    title = models.CharField(max_length=300)
    phase = models.CharField(
        max_length=20, choices=Phase.choices, default=Phase.PHASE_1
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RECRUITING
    )
    start_year = models.IntegerField()
    enrollment = models.IntegerField()
    sponsor = models.ForeignKey("Company", on_delete=models.CASCADE)
    investigator = models.ForeignKey(
        "Person", on_delete=models.SET_NULL, null=True, blank=True
    )
    summary = MarkdownField(blank=True)
    design = MarkdownField(blank=True)
    eligibility = MarkdownField(blank=True)
    results = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["-start_year", "code"]

    class Karni:
        import_key = "code"
        audit = True
        taxonomies = {
            "conditions": "intel.Condition",
            "interventions": "intel.Intervention",
        }
        aggregate = {
            "group_by": ["phase", "status", "start_year", "sponsor__name"],
            "values": ["enrollment"],
            "metrics": ["count", "sum", "avg"],
        }
        search = {"fields": ["code", "title"], "title": "title", "subtitle": "code"}
        field_groups = {
            "Identity": ["code", "title", "phase", "status", "start_year", "enrollment"],
            "People": ["sponsor", "investigator"],
            "Protocol": ["summary", "design", "eligibility"],
            "Outcome": ["results"],
        }
        column_sets = {
            "default": ["code", "title", "phase", "status", "start_year"],
            "sponsor": ["code", "sponsor", "enrollment", "start_year"],
        }

    def __str__(self) -> str:
        return self.code


class Brand(BaseModel):
    name = models.CharField(max_length=200)
    company = models.ForeignKey("Company", on_delete=models.CASCADE)
    description = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]

    class Karni:
        import_key = "name"
        taxonomies = {"interventions": "intel.Intervention"}
        search = {"fields": ["name"], "title": "name"}

    def __str__(self) -> str:
        return self.name


class Deal(BaseModel):
    title = models.CharField(max_length=300)
    value = MoneyField(currency="USD")
    year = models.IntegerField()
    acquirer = models.ForeignKey(
        "Company", on_delete=models.CASCADE, related_name="deal_acquirer_set"
    )
    seller = models.ForeignKey(
        "Company", on_delete=models.CASCADE, related_name="deal_seller_set"
    )
    brand = models.ForeignKey("Brand", on_delete=models.SET_NULL, null=True, blank=True)
    rationale = MarkdownField(blank=True)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["-year", "title"]

    class Karni:
        import_key = "title"
        audit = True
        taxonomies = {"interventions": "intel.Intervention"}
        aggregate = {
            "group_by": ["year", "acquirer__name"],
            "values": ["value"],
            "metrics": ["count", "sum", "avg"],
        }
        search = {"fields": ["title"], "title": "title"}

    def __str__(self) -> str:
        return self.title
