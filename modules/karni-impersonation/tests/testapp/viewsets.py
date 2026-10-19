from karni.api import BaseViewSet, Granted

from tests.testapp.models import Note, Secret


class NoteViewSet(BaseViewSet):
    model = Note
    access = Granted()


class SecretViewSet(BaseViewSet):
    model = Secret
    access = Granted()
