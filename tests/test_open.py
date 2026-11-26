from pools.capacity import read_capacity, seed_capacity
from tests.support import INITIAL, ServiceTestCase, record_scenario


class OpenTests(ServiceTestCase):
    def test_open_and_admit(self):
        self.open_sample()
        self.assertEqual(self.service.commits, [('A', (8, None)), ('B', (8, 0))])
        for pool, slots in INITIAL.items():
            self.assertEqual(self.service.request('/pools', query={'room': 'main', 'pool': pool}),
                             (200, {'pool': pool, 'slots': slots, 'status': 'confirmed'}))
        accepted = self.service.segment('first', 4)
        self.assertEqual(accepted, (200, {'segment': 'first', 'room': 'main', 'work': 4,
                                          'status': 'admitted', 'pool': 'A'}))
        self.assertEqual(self.service.segment('first', 4), accepted)
        self.assertEqual(self.service.segment('first', 5)[0], 409)
        self.assertEqual(self.service.in_flight('A'), 1)
        for number in range(7):
            status, segment = self.service.segment(f'fill-{number}')
            self.assertEqual((status, segment['pool']), (200, 'A'))
        status, queued = self.service.segment('ninth')
        self.assertEqual((status, queued['status'], queued['pool']), (200, 'queued', None))
        occupied = self.service.in_flight('A')
        self.assertEqual(occupied, 8)
        record_scenario('ordinary_open', {'initial': INITIAL, 'distinct_submissions': 9, 'retries': 1},
                        [8, 0], self.service.actual_pair(), {'occupied': 8, 'last': 'queued'},
                        {'occupied': occupied, 'last': queued['status']},
                        ['rooms/lifecycle.py', 'pools/quotas.py', 'work/admission.py'],
                        'One slot per distinct segment, so the first eight use A and the ninth waits.')

    def test_open_below_floor(self):
        status, rejected = self.service.open_room(initial={'A': 5, 'B': 0})
        self.assertEqual((status, rejected['error']), (400, 'outside_band'))
        self.assertEqual(self.service.actual_pair(), (None, None))
        self.assertEqual(self.service.commits, [])
        self.assertEqual(self.service.request('/rooms', query={'room': 'main'})[0], 404)
        intake, _ = self.service.segment('too-early')
        self.assertEqual(intake, 404)
        record_scenario('invalid_open', {'initial': [5, 0], 'floor': 6}, 400, status,
                        {'commits': 0, 'segment_status': 404},
                        {'commits': len(self.service.commits), 'segment_status': intake},
                        ['rooms/band.py', 'rooms/lifecycle.py', 'work/admission.py'],
                        '5 + 0 is below 6 and cannot establish either pool allocation.')

    def test_reinitialization_preserves_existing_business_state(self):
        self.open_sample()
        self.assertEqual(self.service.switch()[0], 200)
        admitted = self.service.segment('caption', 7)
        self.assertEqual((admitted[0], admitted[1]['pool']), (200, 'B'))
        original = self.service.read_switch()
        self.service.restart()
        for store in self.service.runtime.pools.values():
            with store.open() as db:
                self.assertEqual(read_capacity(db), 12)
        self.assertEqual(self.service.actual_pair(), (0, 8))
        self.assertEqual(self.service.segment('caption', 7), admitted)
        self.assertEqual(self.service.in_flight('B'), 1)
        self.assertEqual(self.service.read_switch(), original)
        self.assertEqual(self.service.open_room()[0], 200)
        self.assertEqual(self.service.actual_pair(), (0, 8))

    def test_opening_can_resume_after_partial_pool_establishment(self):
        # A real pool commit makes B temporarily unavailable before B establishes its quota.
        store = self.service.runtime.pools['A']
        b_path = self.service.runtime.pools['B'].path
        saved = b_path.with_suffix('.offline')

        def after_a(pool):
            b_path.rename(saved)
            self.service._observe_commit(pool)

        store.on_commit = after_a
        try:
            status, opening = self.service.open_room()
            self.assertEqual((status, opening['status']), (202, 'opening'))
            self.assertEqual(self.service.actual_pair(), (8, None))
            self.assertEqual(self.service.segment('not-open')[0], 409)
            self.assertEqual(self.service.open_room(initial={'A': 7, 'B': 1})[0], 409)
        finally:
            if saved.exists():
                saved.rename(b_path)
            store.on_commit = self.service._observe_commit
        self.service.restart()
        self.open_sample()
        self.assertEqual(self.service.commits, [('A', (8, None)), ('B', (8, 0))])

    def test_initial_allocation_checks_existing_pool_commitments(self):
        self.open_sample()
        seed_capacity(self.service.runtime.pools['A'], 50)
        with self.service.runtime.pools['A'].open() as db:
            self.assertEqual(read_capacity(db), 12)
        before = list(self.service.commits)
        status, rejected = self.service.open_room(room='other', initial={'A': 5, 'B': 1})
        self.assertEqual((status, rejected['error']), (400, 'pool_capacity'))
        self.assertEqual(self.service.actual_pair('other'), (None, None))
        self.assertEqual(self.service.commits, before)
