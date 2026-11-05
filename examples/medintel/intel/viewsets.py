"""intel API. Each viewset extends the one karni build writes in intel/karni/api.py from
karni.yaml: add your actions here.
"""

from intel.karni import api as karni


class ConditionViewSet(karni.ConditionViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class InterventionViewSet(karni.InterventionViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class CompanyViewSet(karni.CompanyViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class PersonViewSet(karni.PersonViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class TrialViewSet(karni.TrialViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class BrandViewSet(karni.BrandViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class DealViewSet(karni.DealViewSet):
    """The base class comes from karni.yaml (karni build). Add your own code here."""
