import json
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pools.commands import DeliveryUncertain
from pools.readback import read_pool
from rooms.http import LiveCaptionHandler, create_runtime, make_server
from work.admission import count_in_flight


ROOM = 'main'
INITIAL = {'A': 8, 'B': 0}
TARGET = {'A': 0, 'B': 8}


class QuietHandler(LiveCaptionHandler):
    def log_request(self, code='-', size='-'):
        pass


class LocalService:
    def __init__(self, directory, *, capacities=None, watch_room=ROOM):
        self.directory = Path(directory)
        self.watch_room = watch_room
        self.commits = []
        self.sent = []
        self.held = []
        self.loss = None
        self.server = None
        self._start(capacities)

    def _start(self, capacities=None):
        self.runtime = create_runtime(self.directory, capacities=capacities)
        for store in self.runtime.pools.values():
            store.on_commit = self._observe_commit
        self.runtime.transport = self._deliver
        self.server = make_server(self.runtime, '127.0.0.1', 0, QuietHandler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01})
        self.thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('HTTP server thread did not close')
            self.server = None

    def restart(self):
        self.close()
        self._start()

    def _observe_commit(self, pool):
        self.commits.append((pool, self.actual_pair()))

    def actual_pair(self, room=None):
        room = self.watch_room if room is None else room
        return tuple(read_pool(self.runtime.pools[pool], room).slots for pool in ('A', 'B'))

    def lose_next(self, when, predicate=None):
        if when not in ('before', 'after'):
            raise ValueError('Delivery loss must occur before or after commit')
        self.loss = (when, predicate)

    def _deliver(self, command):
        self.sent.append(command)
        loss = self.loss
        if loss is None:
            return self.runtime.apply_command(command)
        when, predicate = loss
        if predicate is not None and not predicate(command):
            return self.runtime.apply_command(command)
        self.loss = None
        self.held.append(command)
        if when == 'after':
            self.runtime.apply_command(command)
        raise DeliveryUncertain()

    def redeliver(self, command):
        return self.runtime.apply_command(command)

    @contextmanager
    def offline(self, pool):
        path = self.runtime.pools[pool].path
        saved = path.with_suffix('.offline')
        path.rename(saved)
        try:
            yield
        finally:
            saved.rename(path)

    def request(self, path, *, query=None, body=None):
        url = self.base + path
        if query:
            url += '?' + urlencode(query)
        encoded = None if body is None else json.dumps(body).encode('utf-8')
        request = Request(url, data=encoded, headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def open_room(self, *, room=ROOM, initial=INITIAL, floor=6, ceiling=10):
        return self.request('/rooms', body={'room': room, 'floor': floor, 'ceiling': ceiling, 'initial': initial})

    def segment(self, segment, work=1, room=ROOM):
        return self.request('/segments', body={'room': room, 'segment': segment, 'work': work})

    def complete(self, segment, pool):
        return self.request('/segments/complete', body={'segment': segment, 'pool': pool})

    def switch(self, switch_id='S1', target=TARGET, room=ROOM):
        return self.request('/switches', body={'room': room, 'switch_id': switch_id, 'target': target})

    def read_switch(self, switch_id='S1', room=ROOM):
        return self.request('/switches', query={'room': room, 'switch_id': switch_id})

    def handover(self, room=ROOM):
        return self.request('/handover', query={'room': room})

    def in_flight(self, pool, room=ROOM):
        with self.runtime.transaction() as db:
            return count_in_flight(db, room, pool)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.service = self.enterContext(LocalService(directory, capacities={'A': 12, 'B': 12}))

    def open_sample(self):
        status, result = self.service.open_room()
        self.assertEqual(status, 200, result)
        self.assertEqual((result['status'], result['initial']), ('open', INITIAL))
        self.assertEqual(self.service.actual_pair(), (8, 0))

    def assert_band(self, commits):
        self.assertTrue(commits, 'No actual pool commits observed')
        for pool, pair in commits:
            self.assertTrue(all(type(slots) is int for slots in pair), f'Unconfirmed observation: {pool} {pair}')
            self.assertTrue(all(0 <= slots <= 12 for slots in pair), f'Pool capacity breach: {pool} {pair}')
            self.assertTrue(6 <= sum(pair) <= 10, f'SLOT_BAND_BREACH {pool} committed {pair}')


def record_scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }, sort_keys=True))
