from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from examples.demo import exchange
from release.service import running_server


def place(slot, track, recording, source, at, revision='1'):
    return {'op': 'place', 'slot': slot, 'track': track, 'recording': recording, 'revision': revision, 'source': source, 'at': at}


def move(slot, at):
    return {'op': 'move', 'slot': slot, 'at': at}


def copy(slot, target, at):
    return {'op': 'copy', 'slot': slot, 'as': target, 'at': at}


def trim(slot, source):
    return {'op': 'trim', 'slot': slot, 'source': source}


def remove(slot):
    return {'op': 'remove', 'slot': slot}


class ServiceCase(TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        directory = self.resources.enter_context(TemporaryDirectory(prefix='oral-history-test-'))
        self.database = Path(directory) / 'guide.sqlite3'
        self.server = ExitStack()
        self.resources.callback(self.server.close)
        self.reopen()

    def reopen(self):
        self.server.close()
        self.base = self.server.enter_context(running_server(self.database))

    def api(self, path, payload=None, *, status=200):
        actual, body = exchange(self.base, path, payload)
        self.assertEqual(actual, status, (path, body))
        return body

    def cut(self, version, parent, operations, *, status=200):
        return self.api('/edit_version', {'version': version, 'parent': parent, 'operations': operations}, status=status)

    def order(self, order_id, version, window, *, status=200):
        return self.api('/review_order', {'order_id': order_id, 'version': version, 'window': window}, status=status)

    def decide(self, request_id, order_id, decision='approve', *, status=200):
        return self.api('/review_decision', {'request_id': request_id, 'order_id': order_id, 'decision': decision}, status=status)

    def listen(self, order_id, version, window):
        self.order(order_id, version, window)
        return self.decide(order_id + '-approved', order_id)

    def issue(self, request_id, version, *, status=200):
        return self.api('/issue', {'request_id': request_id, 'version': version}, status=status)

    def prepare_mix(self):
        self.cut('R1', 'root', [place('c', 'narration', 'C', [1, 3], 4), place('d', 'translation', 'D', [1, 3], 4)])
