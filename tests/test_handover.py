from tests.support import INITIAL, TARGET, ServiceTestCase, record_scenario


class HandoverTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.open_sample()

    def test_read_original_receipt(self):
        status, first = self.service.switch()
        self.assertEqual((status, first['allocation']), (200, TARGET))
        self.assertEqual(self.service.switch(), (200, first))
        status, second = self.service.switch('S2', INITIAL)
        self.assertEqual((status, second['allocation']), (200, INITIAL))
        self.assertNotEqual(first['receipt'], second['receipt'])
        self.service.restart()
        status, original = self.service.read_switch()
        self.assertEqual((status, original), (200, first))
        self.assertEqual(self.service.switch(), (200, first))
        self.assertEqual(self.service.switch(target=INITIAL)[0], 409)
        self.assertEqual(self.service.read_switch('unknown')[0], 404)
        status, handover = self.service.handover()
        supply = {key: value['slots'] for key, value in handover['pools'].items()}
        self.assertEqual((status, supply, handover['total']), (200, INITIAL, 8))
        self.assertIsNone(handover['pending'])
        self.assertEqual(handover['receipts'], [first, second])
        record_scenario('receipt', {'S1': TARGET, 'S2': INITIAL}, TARGET, original['allocation'],
                        {'current': INITIAL, 'same_receipt': True},
                        {'current': supply, 'same_receipt': original['receipt'] == first['receipt']},
                        ['handover/replay.py', 'handover/receipts.py', 'handover/summary.py'],
                        'The first and second targets differ. Current supply follows the second and S1 keeps the first.')

    def test_unavailable_pool_keeps_original_receipts_visible(self):
        status, first = self.service.switch()
        self.assertEqual(status, 200)
        with self.service.offline('A'):
            status, reading = self.service.request('/pools', query={'room': 'main', 'pool': 'A'})
            self.assertEqual((status, reading), (503, {'pool': 'A', 'slots': None, 'status': 'unconfirmed'}))
            status, handover = self.service.handover()
            self.assertEqual(status, 200)
            self.assertIsNone(handover['total'])
            self.assertEqual(handover['pools']['A'], reading)
            self.assertEqual(handover['pools']['B']['slots'], 8)
            self.assertEqual(handover['receipts'], [first])
            self.assertEqual(self.service.read_switch(), (200, first))
            self.assertEqual(self.service.segment('during-outage')[1]['pool'], 'B')
        self.assertEqual(self.service.handover()[1]['total'], 8)
        self.assertEqual(self.service.handover('unknown')[0], 404)

    def test_failed_receipt_write_keeps_request_pending(self):
        with self.service.runtime.transaction(write=True) as db:
            db.execute('''CREATE TRIGGER reject_receipt BEFORE INSERT ON receipts
                          BEGIN SELECT RAISE(ABORT, 'receipt store unavailable'); END''')
        status, failure = self.service.switch()
        self.assertEqual((status, failure['error']), (500, 'storage_error'))
        self.assertEqual(self.service.actual_pair(), (0, 8))
        _, pending = self.service.read_switch()
        self.assertEqual(pending['status'], 'pending')
        self.assertNotIn('receipt', pending)
        _, handover = self.service.handover()
        self.assertEqual(handover['pending']['switch_id'], 'S1')
        self.assertEqual(handover['receipts'], [])
        with self.service.runtime.transaction(write=True) as db:
            db.execute('DROP TRIGGER reject_receipt')
        before = list(self.service.commits)
        status, result = self.service.switch()
        self.assertEqual((status, result['allocation']), (200, TARGET))
        self.assertEqual(self.service.commits, before)
        self.assertEqual(self.service.handover()[1]['receipts'], [result])
