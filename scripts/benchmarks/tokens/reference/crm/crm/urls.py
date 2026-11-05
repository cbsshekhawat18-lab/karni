from crm.importing import ImportContactsView
from django.urls import path

urlpatterns = [path("contacts/import/", ImportContactsView.as_view())]
