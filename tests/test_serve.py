from tests.support import ServiceTestCase, record_scenario


class ServeTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.open_sample()

    def fill_pool(self):
        for number in range(8):
            status, segment = self.service.segment(f'base-{number}', 9)
            self.assertEqual((status, segment['pool']), (200, 'A'))

    def demand(self, cycle_work):
        return self.service.request('/demand', query={'room': 'main', 'cycle_work': cycle_work})

    def test_demand(self):
        self.fill_pool()
        status, lead = self.service.segment('queue-lead', 3)
        self.assertEqual((status, lead['status']), (200, 'queued'))
        for number, work in enumerate((13, 10, 8)):
            status, queued = self.service.segment(f'queue-{number}', work)
            self.assertEqual((status, queued['status']), (200, 'queued'))
        self.assertEqual(self.service.complete('base-0', 'A')[0], 200)
        self.assertEqual(self.service.segment('queue-lead', 3)[1]['pool'], 'A')
        self.assertEqual(self.service.segment('queue-0', 13)[1]['status'], 'queued')
        before = self.service.actual_pair()
        commits = list(self.service.commits)
        status, demand = self.demand(4)
        expected = {'waiting_work': 31, 'suggested_slots': 8, 'cycle_work': 4}
        self.assertEqual((status, demand), (200, expected))
        self.assertGreaterEqual(demand['suggested_slots'] * 4, 31)
        self.assertEqual(self.demand(1), (200, {'waiting_work': 31, 'suggested_slots': 10, 'cycle_work': 1}))
        self.assertEqual(self.service.actual_pair(), before)
        self.assertEqual(self.service.commits, commits)
        for number, work in enumerate((13, 10, 8), start=1):
            queued = f'queue-{number - 1}'
            self.assertEqual(self.service.complete(f'base-{number}', 'A')[0], 200)
            self.assertEqual(self.service.segment(queued, work)[1]['pool'], 'A')
        status, empty = self.demand(4)
        self.assertEqual((status, empty), (200, {'waiting_work': 0, 'suggested_slots': 6, 'cycle_work': 4}))
        self.assertEqual(self.service.actual_pair(), before)
        record_scenario('demand', {'waiting_work': [13, 10, 8], 'cycle_work': 4, 'band': [6, 10]},
                        expected, demand, {'empty_slots': 6, 'actual_allocation': [8, 0]},
                        {'empty_slots': empty['suggested_slots'], 'actual_allocation': self.service.actual_pair()},
                        ['work/demand.py', 'work/queue.py', 'work/completion.py'],
                        'Seven slots supply 28 units, eight supply 32, and an empty queue uses the floor.')

    def test_invalid_rate_and_unknown_room(self):
        for value in (0, -1, 'four', '4.5'):
            with self.subTest(rate=value):
                status, body = self.demand(value)
                self.assertEqual((status, body['error']), (400, 'invalid_cycle_work'))
        self.assertEqual(self.service.request('/demand', query={'room': 'main'})[0], 400)
        self.assertEqual(self.service.request('/demand', query={'room': 'missing', 'cycle_work': 4})[0], 400)
        for work in (True, 0, -1, '1'):
            self.assertEqual(self.service.segment('invalid', work)[0], 400)

    def test_complete_with_original_pool(self):
        self.fill_pool()
        self.assertEqual(self.service.segment('head')[1]['status'], 'queued')
        self.assertEqual(self.service.segment('tail')[1]['status'], 'queued')
        wrong, body = self.service.complete('base-0', 'B')
        self.assertEqual((wrong, body['error']), (409, 'wrong_pool'))
        self.assertEqual(self.service.complete('missing', 'A')[0], 404)
        self.assertEqual(self.service.complete('head', 'A')[0], 409)
        self.assertEqual(self.service.in_flight('A'), 8)
        blocked = self.service.segment('head')[1]['status']
        self.assertEqual(blocked, 'queued')
        completed = self.service.complete('base-0', 'A')
        self.assertEqual((completed[0], completed[1]['status'], completed[1]['pool']), (200, 'completed', 'A'))
        head = self.service.segment('head')[1]['pool']
        self.assertEqual(head, 'A')
        self.assertEqual(self.service.complete('base-0', 'A'), completed)
        self.assertEqual(self.service.segment('base-0', 9), completed)
        self.assertEqual(self.service.in_flight('A'), 8)
        tail = self.service.segment('tail')[1]['status']
        self.assertEqual(tail, 'queued')
        record_scenario('wrong_pool', {'assigned_pool': 'A', 'notifications': ['B', 'A', 'A']},
                        {'wrong_status': 409, 'head_before_release': 'queued'},
                        {'wrong_status': wrong, 'head_before_release': blocked},
                        {'head_pool': 'A', 'tail': 'queued'}, {'head_pool': head, 'tail': tail},
                        ['work/completion.py', 'work/admission.py', 'work/queue.py'],
                        'Only the first A completion releases a slot, and that slot belongs to the queue head.')
