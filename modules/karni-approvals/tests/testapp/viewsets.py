from karni.api import BaseViewSet, Granted

from tests.testapp.models import Branch, Contract, Invoice, Memo


class BranchViewSet(BaseViewSet):
    model = Branch
    access = Granted()


class InvoiceViewSet(BaseViewSet):
    model = Invoice
    access = Granted()


class ContractViewSet(BaseViewSet):
    model = Contract
    access = Granted()


class MemoViewSet(BaseViewSet):
    model = Memo
    access = Granted()
