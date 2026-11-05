"""Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.

Your own code goes in intel/viewsets.py, in the subclass of each class here.
"""

from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole

from intel.models import Brand, Company, Condition, Deal, Intervention, Person, Trial


class ConditionViewSet(BaseViewSet):
    model = Condition
    access = Access(read=Authenticated(), write=HasRole("staff"))
    search_fields = ("name",)


class InterventionViewSet(BaseViewSet):
    model = Intervention
    access = Access(read=Authenticated(), write=HasRole("staff"))
    search_fields = ("name",)


class CompanyViewSet(BaseViewSet):
    model = Company
    access = Granted()
    search_fields = ("name",)


class PersonViewSet(BaseViewSet):
    model = Person
    access = Granted()
    search_fields = ("name",)


class TrialViewSet(BaseViewSet):
    model = Trial
    access = Granted()
    search_fields = ("code", "title")


class BrandViewSet(BaseViewSet):
    model = Brand
    access = Granted()
    search_fields = ("name",)


class DealViewSet(BaseViewSet):
    model = Deal
    access = Granted()
    search_fields = ("title",)
