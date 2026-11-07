"""Contact import from a CSV file, in one request."""

import csv
import io

from crm.models import Company, Contact
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from karni.accounts.permissions import has_role
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ImportContactsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not has_role(request.user, "manager", "admin"):
            raise PermissionDenied("Only managers and admins import contacts.")
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": ["Upload a CSV file."]})
        reader = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")))
        created = updated = 0
        errors = []
        for number, row in enumerate(reader, start=2):
            email = (row.get("email") or "").strip().lower()
            try:
                validate_email(email)
            except DjangoValidationError:
                errors.append({"line": number, "error": "Invalid email."})
                continue
            with transaction.atomic():
                name = (row.get("company") or "").strip()
                company = Company.objects.get_or_create(name=name)[0] if name else None
                _contact, was_created = Contact.objects.update_or_create(
                    email=email,
                    defaults={
                        "first_name": (row.get("first_name") or "").strip(),
                        "last_name": (row.get("last_name") or "").strip(),
                        "phone": (row.get("phone") or "").strip(),
                        "company": company,
                    },
                )
            created += was_created
            updated += not was_created
        return Response({"created": created, "updated": updated, "errors": errors})
