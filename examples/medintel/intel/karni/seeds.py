"""Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.

The rows karni seed makes. Steer a field's values in intel/seeds.py.
"""

from karni.seeding import Seeder

from intel.models import Brand, Company, Condition, Deal, Intervention, Person, Trial


class ConditionSeeder(Seeder):
    class Meta:
        model = Condition
        count = 90


class InterventionSeeder(Seeder):
    class Meta:
        model = Intervention
        count = 35


class CompanySeeder(Seeder):
    class Meta:
        model = Company
        count = 40


class PersonSeeder(Seeder):
    class Meta:
        model = Person
        count = 80


class TrialSeeder(Seeder):
    class Meta:
        model = Trial
        count = 300


class BrandSeeder(Seeder):
    class Meta:
        model = Brand
        count = 60


class DealSeeder(Seeder):
    class Meta:
        model = Deal
        count = 120
