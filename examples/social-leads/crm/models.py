"""crm models, each on karni.models.BaseModel: `karni make model <Name>`."""

from django.conf import settings
from django.db import models
from karni.models import BaseModel


class Workspace(BaseModel):
    name = models.CharField(max_length=200)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL)

    def __str__(self) -> str:
        return self.name


class Contact(BaseModel):
    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE)
    phone = models.CharField(max_length=30)
    name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self) -> str:
        return self.phone


class Lead(BaseModel):
    class Status(models.TextChoices):
        NEW = "new"
        CONTACTED = "contacted"
        QUALIFIED = "qualified"
        CONVERTED = "converted"
        LOST = "lost"
        SPAM = "spam"

    workspace = models.ForeignKey("Workspace", on_delete=models.CASCADE)
    contact = models.ForeignKey("Contact", on_delete=models.CASCADE)
    name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    interest = models.CharField(max_length=200, blank=True)
    budget = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    source_channel = models.CharField(max_length=50, default="whatsapp")
    source_ad_id = models.CharField(max_length=100, blank=True)
    source_ad_name = models.CharField(max_length=200, blank=True)
    source_campaign_id = models.CharField(max_length=100, blank=True)
    source_campaign_name = models.CharField(max_length=200, blank=True)
    source_adset_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    quality_score = models.IntegerField(default=50)  # 0-100, set by the scorer
    quality_reason = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    conversion_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    capi_pushed_at = models.DateTimeField(null=True, blank=True)

    class Karni:
        audit = True  # every status change, assignment and conversion is history

    def __str__(self) -> str:
        return self.name or self.phone


class LeadActivity(BaseModel):
    class ActivityType(models.TextChoices):
        NOTE = "note"
        CALL = "call"
        EMAIL = "email"
        WHATSAPP = "whatsapp"
        STATUS_CHANGE = "status_change"
        ASSIGNMENT = "assignment"
        TAG = "tag"

    lead = models.ForeignKey("Lead", on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    activity_type = models.CharField(
        max_length=20, choices=ActivityType.choices, default=ActivityType.NOTE
    )
    content = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name_plural = "lead activities"

    def __str__(self) -> str:
        return f"{self.activity_type} on {self.lead_id}"
