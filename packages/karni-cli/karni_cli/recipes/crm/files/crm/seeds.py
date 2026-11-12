"""crm demo data for karni seed. Each seeder extends the one karni build writes in
crm/karni/seeds.py: steer a field's values here.

The companies, people and deals are invented, and every web address ends in .example.
Replace COMPANIES and the lists below with your own.
"""

import datetime as dt
from decimal import Decimal
from typing import Any, NamedTuple

from crm.karni import seeds as karni
from karni.seeding import SeedContext, cycled

from crm.models import Company, Contact, Deal


class Firm(NamedTuple):
    name: str
    industry: str
    domain: str
    notes: str
    deals: tuple[tuple[str, int], ...]  # a deal's title and its value


COMPANIES = [
    Firm(
        "Larchmont Freight",
        "Logistics",
        "larchmont-freight.example",
        "Regional hauler with forty vehicles and a growing cold-chain business.",
        (("Fleet tracking rollout", 48000), ("Depot scheduling software", 26000)),
    ),
    Firm(
        "Brightwater Dental Group",
        "Dental care",
        "brightwater-dental.example",
        "Six clinics in two counties, opened the newest one this spring.",
        (("Patient reminder service", 9500), ("Clinic booking portal", 18000)),
    ),
    Firm(
        "Ashgrove Architects",
        "Architecture",
        "ashgrove-architects.example",
        "Twelve-person practice that designs schools and community buildings.",
        (("Project file archive", 7200), ("Drawing review workflow", 12500)),
    ),
    Firm(
        "Millstone Bakehouse",
        "Food manufacturing",
        "millstone-bakehouse.example",
        "Wholesale bakery supplying cafes and grocers before dawn each day.",
        (("Order intake system", 15500), ("Production planning pilot", 11000)),
    ),
    Firm(
        "Fernhill Software",
        "Software",
        "fernhill-software.example",
        "Builds scheduling tools for clinics and is looking for a reseller partner.",
        (("Partner portal build", 32000), ("Support desk integration", 14000)),
    ),
    Firm(
        "Harrow Veterinary Centre",
        "Veterinary",
        "harrow-vets.example",
        "Two-site practice with an out-of-hours emergency service.",
        (("Appointment and records system", 21000), ("Client messaging add-on", 5400)),
    ),
    Firm(
        "Solbright Energy",
        "Renewable energy",
        "solbright-energy.example",
        "Installs rooftop solar for homes and small farms.",
        (("Installation job tracker", 38000), ("Customer quote generator", 16500)),
    ),
    Firm(
        "Pemberton and Wray Solicitors",
        "Legal services",
        "pemberton-wray.example",
        "Family and property law firm with eight fee earners.",
        (("Matter management system", 29000), ("Client intake forms", 6800)),
    ),
    Firm(
        "Ironbridge Construction",
        "Construction",
        "ironbridge-construction.example",
        "Mid-size builder working on housing and light commercial sites.",
        (
            ("Site diary and snagging app", 24500),
            ("Subcontractor payments tracker", 17500),
        ),
    ),
    Firm(
        "Kestmere Language School",
        "Education",
        "kestmere-school.example",
        "Adult language school with day and evening classes in four languages.",
        (("Course enrolment portal", 13500), ("Teacher timetable planner", 8200)),
    ),
    Firm(
        "The Quayside Hotel",
        "Hospitality",
        "quayside-hotel.example",
        "Forty-room harbour hotel with a restaurant and a conference suite.",
        (("Group booking engine", 22500), ("Event enquiry pipeline", 9800)),
    ),
    Firm(
        "Marlowe Print Works",
        "Printing",
        "marlowe-print.example",
        "Commercial printer for packaging, labels and short-run books.",
        (("Job quoting tool", 14500), ("Press schedule board", 12000)),
    ),
    Firm(
        "Dunmore Accountancy",
        "Accounting",
        "dunmore-accountancy.example",
        "Small-business accountants with three hundred ongoing clients.",
        (("Client document portal", 11500), ("Deadline tracking dashboard", 7600)),
    ),
    Firm(
        "Greenfurrow Farms",
        "Agriculture",
        "greenfurrow-farms.example",
        "Family-run arable and dairy farm selling directly to local shops.",
        (("Produce ordering site", 10500), ("Field and yield records", 8900)),
    ),
    Firm(
        "Wexcombe Community Health",
        "Healthcare",
        "wexcombe-health.example",
        "Primary care network covering three towns and a mobile clinic.",
        (("Referral tracking system", 41000), ("Staff rota planner", 19500)),
    ),
    Firm(
        "Tolland and Pike Outfitters",
        "Retail",
        "tolland-pike.example",
        "Outdoor clothing and equipment shop with two stores and a web shop.",
        (("Stock and web shop sync", 27500), ("Loyalty scheme platform", 15000)),
    ),
    Firm(
        "Calder Precision Parts",
        "Manufacturing",
        "calder-precision.example",
        "Machines small metal parts for pump and valve makers.",
        (("Quality inspection log", 23500), ("Machine maintenance planner", 18500)),
    ),
    Firm(
        "Bluepine Marketing",
        "Marketing",
        "bluepine-marketing.example",
        "Eight-person agency running campaigns for local councils and charities.",
        (("Campaign reporting hub", 12500), ("Client approvals tool", 6400)),
    ),
    Firm(
        "Oakhurst Property Management",
        "Property",
        "oakhurst-property.example",
        "Manages around nine hundred rented homes for private landlords.",
        (
            ("Maintenance request portal", 33500),
            ("Tenant communications module", 14800),
        ),
    ),
    Firm(
        "Redfern Coaches",
        "Transport",
        "redfern-coaches.example",
        "Coach hire for schools, tours and weddings, with a fleet of twenty.",
        (("Charter booking system", 20500), ("Driver hours tracker", 9300)),
    ),
]
FIRST = [
    "Amara",
    "Daniel",
    "Priya",
    "Tomas",
    "Hannah",
    "Kofi",
    "Elena",
    "Marcus",
    "Sana",
    "Liam",
    "Ingrid",
    "Rahul",
    "Chloe",
    "Mateo",
    "Yuki",
    "Fatima",
    "Oscar",
    "Nadia",
    "Callum",
    "Ruth",
]
LAST = [
    "Okafor",
    "Lindqvist",
    "Sharma",
    "Novak",
    "Whitfield",
    "Mensah",
    "Rossi",
    "Hartley",
    "Qureshi",
    "Brennan",
    "Halvorsen",
    "Iyer",
    "Fontaine",
    "Alvarez",
    "Tanaka",
    "Haddad",
    "Pearce",
    "Volkov",
    "Mackenzie",
    "Adeyemi",
]
JOB_TITLES = [
    "Managing Director",
    "Operations Manager",
    "Head of Finance",
    "Office Manager",
    "IT Manager",
    "Purchasing Lead",
    "Practice Manager",
    "Commercial Director",
    "Customer Service Lead",
    "Project Manager",
    "Head of People",
    "General Manager",
]
STAGES = [
    "lead",
    "qualified",
    "proposal",
    "won",
    "lead",
    "qualified",
    "proposal",
    "lost",
    "qualified",
    "won",
]
OPEN = {"lead", "qualified", "proposal"}
KINDS = ["call", "email", "meeting"]
NOTES = {
    "call": [
        "Intro call to learn how they handle this today.",
        "Called to check the quote arrived and answer questions.",
        "Follow-up call about timing and who signs off.",
    ],
    "email": [
        "Sent the overview and two customer examples.",
        "Emailed the revised quote with the changes they asked for.",
        "Sent the draft contract for their legal review.",
    ],
    "meeting": [
        "Walked the team through a demo on their own data.",
        "On-site visit to see the current process.",
        "Workshop with the buyers to agree the scope.",
    ],
}


def _firm(company: Company, position: int) -> Firm:
    """The firm a company row was made from (also with a suffix), else by position."""
    for firm in COMPANIES:
        if company.name.startswith(firm.name):
            return firm
    return COMPANIES[position % len(COMPANIES)]


class CompanySeeder(karni.CompanySeeder):
    """Businesses in different trades, each with a site on its own address."""

    def seed(self, context: SeedContext) -> list[Any]:
        names = [firm.name for firm in COMPANIES]
        rows: list[Any] = []
        for number in range(context.count):
            firm = COMPANIES[number % len(COMPANIES)]
            round_ = number // len(COMPANIES) + 1
            domain = firm.domain if round_ == 1 else f"{round_}.{firm.domain}"
            rows += context.create(
                1,
                name=cycled(names, number),
                website=f"https://www.{domain}/",
                industry=firm.industry,
                notes=firm.notes,
            )
        return rows


class ContactSeeder(karni.ContactSeeder):
    """People at the companies, three at each, with an email on the company's domain."""

    def seed(self, context: SeedContext) -> list[Any]:
        companies = list(Company.objects.order_by("name"))
        taken = set(Contact.objects.values_list("email", flat=True))
        rows: list[Any] = []
        for number in range(context.count):
            first = FIRST[(number * 7 + number // len(FIRST)) % len(FIRST)]
            last = LAST[(number * 3 + number // len(LAST) * 11) % len(LAST)]
            company = companies[number % len(companies)] if companies else None
            domain = (
                company.website.split("//", 1)[-1].removeprefix("www.").rstrip("/")
                if company and company.website
                else "contacts.example"
            )
            email = f"{first}.{last}@{domain}".lower()
            suffix = 1
            while email in taken:
                suffix += 1
                email = f"{first}.{last}{suffix}@{domain}".lower()
            taken.add(email)
            rows += context.create(
                1,
                company=company,
                first_name=first,
                last_name=last,
                email=email,
                title=JOB_TITLES[number % len(JOB_TITLES)],
            )
        return rows


class DealSeeder(karni.DealSeeder):
    """Sales to the companies, each with a contact there and a fitting stage."""

    def seed(self, context: SeedContext) -> list[Any]:
        companies = list(Company.objects.order_by("name"))
        today = context.run.anchor.date()
        rows: list[Any] = []
        for number in range(context.count):
            if not companies:
                rows += context.create(1)
                continue
            position = number % len(companies)
            company = companies[position]
            firm = _firm(company, position)
            round_ = number // len(companies)
            title, value = firm.deals[round_ % len(firm.deals)]
            if round_ >= len(firm.deals):
                title = cycled([title], round_ // len(firm.deals))
            people = list(Contact.objects.filter(company=company).order_by("email"))
            stage = STAGES[number % len(STAGES)]
            close = (
                today + dt.timedelta(days=21 + number * 3 % 90)
                if stage in OPEN
                else today - dt.timedelta(days=7 + number * 5 % 80)
            )
            rows += context.create(
                1,
                company=company,
                contact=people[round_ % len(people)] if people else None,
                title=title,
                value=Decimal(value + round_ // len(firm.deals) * 1000),
                stage=stage,
                expected_close=close,
            )
        return rows


class ActivitySeeder(karni.ActivitySeeder):
    """Calls, emails and meetings on each deal, done when their date has passed."""

    def seed(self, context: SeedContext) -> list[Any]:
        deals = list(Deal.objects.order_by("company__name", "title", "pk"))
        now = context.run.anchor.replace(minute=0, second=0, microsecond=0)
        rows: list[Any] = []
        for number in range(context.count):
            if not deals:
                rows += context.create(1)
                continue
            deal = deals[number % len(deals)]
            turn = number // len(deals)
            kind = KINDS[turn % len(KINDS)]
            if deal.stage in OPEN:
                days = (
                    turn - 1
                ) * 6 + number % 4  # the first is behind, the rest ahead
            else:
                days = -(3 + turn * 4 + number % 3)  # a closed deal's activity is over
            due = (now + dt.timedelta(days=days)).replace(hour=9 + number % 8)
            rows += context.create(
                1,
                deal=deal,
                salesperson=deal.salesperson,
                kind=kind,
                due_at=due,
                done=due < now,
                notes=NOTES[kind][number % len(NOTES[kind])],
            )
        return rows
