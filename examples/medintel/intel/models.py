"""intel models. Each class extends the one karni build writes in intel/karni/models.py
from karni.yaml: add your methods here.
"""

from intel.karni import models as karni


class Condition(karni.Condition):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    class Karni(karni.Condition.Karni):
        natural_key = "code"  # files name a row by it (the spec's `key` is only the import key)


    def __str__(self) -> str:
        return self.name  # the generated __str__ is the first field, the code


class Intervention(karni.Intervention):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    class Karni(karni.Intervention.Karni):
        natural_key = "code"  # files name a row by it (the spec's `key` is only the import key)


    def __str__(self) -> str:
        return self.name  # the generated __str__ is the first field, the code


class Company(karni.Company):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    class Karni(karni.Company.Karni):
        natural_key = "name"  # files name a row by it (the spec's `key` is only the import key)


class Person(karni.Person):
    """The base class comes from karni.yaml (karni build). Add your own code here."""


class Trial(karni.Trial):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    class Karni(karni.Trial.Karni):
        cascade = {"sponsor": "a company is soft-deleted, so nothing is hard-deleted by cascade"}


class Brand(karni.Brand):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    class Karni(karni.Brand.Karni):
        natural_key = "name"  # files name a row by it (the spec's `key` is only the import key)


class Deal(karni.Deal):
    """The base class comes from karni.yaml (karni build). Add your own code here."""

    class Karni(karni.Deal.Karni):
        cascade = {
            "acquirer": "a company is soft-deleted, so nothing is hard-deleted by cascade",
            "seller": "a company is soft-deleted, so nothing is hard-deleted by cascade",
        }
