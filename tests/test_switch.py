from concurrent.futures import ThreadPoolExecutor

from tests.support import INITIAL, TARGET, ServiceTestCase, record_scenario


class SwitchTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.open_sample()
        self.service.commits.clear()

    def assert_pending(self, result):
        self.assertEqual(result, {'room': 'main', 'switch_id': 'S1', 'status': 'pending'})
        self.assertEqual(self.service.read_switch(), (200, result))
        status, handover = self.service.handover()
        self.assertEqual(status, 200)
        self.assertEqual(handover['pending']['switch_id'], 'S1')
        self.assertEqual(handover['receipts'], [])

    def test_move_pool(self):
        status, result = self.service.switch()
        self.assert_band(self.service.commits)
        self.assertEqual((status, result['status'], result['allocation']), (200, 'completed', TARGET))
        self.assertTrue(result['receipt'])
        self.assertEqual(self.service.read_switch(), (200, result))
        self.assertEqual(self.service.actual_pair(), (0, 8))
        status, accepted = self.service.segment('after-maintenance')
        self.assertEqual((status, accepted['pool']), (200, 'B'))
        record_scenario('ordinary_switch', {'initial': INITIAL, 'target': TARGET, 'band': [6, 10]},
                        {'band_respected': True, 'allocation': TARGET},
                        {'band_respected': all(6 <= sum(pair) <= 10 for _, pair in self.service.commits),
                         'allocation': result['allocation'], 'commits': self.service.commits},
                        {'new_pool': 'B', 'receipt_confirmed': True},
                        {'new_pool': accepted['pool'], 'receipt_confirmed': bool(result['receipt'])},
                        ['transfer/progression.py', 'pools/commands.py', 'work/admission.py'],
                        'Sum the two independent pool values after every real commit. At the end only B has quota.')

    def test_invalid_target(self):
        status, rejected = self.service.switch(target={'A': 0, 'B': 11})
        self.assertEqual((status, rejected['error']), (400, 'outside_band'))
        self.assertEqual(self.service.read_switch()[0], 404)
        self.assertEqual(self.service.commits, [])
        self.assertEqual(self.service.actual_pair(), (8, 0))
        _, handover = self.service.handover()
        self.assertEqual(handover['receipts'], [])
        self.assertIsNone(handover['pending'])
        for target in ({'A': -1, 'B': 9}, {'A': False, 'B': 8}, {'A': 8}):
            self.assertEqual(self.service.switch(target=target)[0], 400)
        record_scenario('invalid_target', {'target': [0, 11], 'ceiling': 10}, 400, status,
                        {'actual': [8, 0], 'receipts': [], 'pending': None},
                        {'actual': self.service.actual_pair(), 'receipts': handover['receipts'],
                         'pending': handover['pending']},
                        ['rooms/band.py', 'transfer/requests.py', 'handover/summary.py'],
                        '11 exceeds the declared ceiling of 10. No records or quota writes follow.')

    def _resume_with_first_loss(self, when):
        self.service.lose_next(when)
        status, pending = self.service.switch()
        self.assertEqual(status, 202, pending)
        self.assert_pending(pending)
        self.assertEqual(len(self.service.held), 1)
        command = self.service.held[0]
        before_restart = self.service.actual_pair()
        if when == 'before':
            self.assertEqual(before_restart, (8, 0))
            self.assertEqual(self.service.commits, [])
        else:
            self.assertNotEqual(before_restart, (8, 0))
            self.assert_band(self.service.commits)
        self.service.restart()
        self.assert_pending(pending)
        self.assertEqual(self.service.actual_pair(), before_restart)
        conflicting_status, conflicting = self.service.switch('S2', INITIAL)
        self.assertEqual((conflicting_status, conflicting['error']), (409, 'switch_in_progress'))
        self.assertEqual(self.service.read_switch('S2')[0], 404)
        self.assertEqual(self.service.switch(target=INITIAL)[0], 409)
        status, result = self.service.switch()
        self.assert_band(self.service.commits)
        self.assertEqual((status, result['status'], result['allocation']), (200, 'completed', TARGET))
        self.assertTrue(result['receipt'])
        self.assertEqual(self.service.actual_pair(), (0, 8))
        end_of_transfer = list(self.service.commits)
        for message in [command, *reversed(self.service.sent)]:
            self.service.redeliver(message)
        self.assert_band(self.service.commits)
        self.assertEqual(self.service.commits, end_of_transfer)
        self.assertEqual(self.service.actual_pair(), (0, 8))
        self.assertEqual(self.service.switch(), (200, result))
        self.assertEqual(self.service.read_switch(), (200, result))
        self.assertEqual(self.service.switch(target=INITIAL)[0], 409)
        return pending, result

    def test_resume_after_lost_reply(self):
        pending, result = self._resume_with_first_loss('after')
        record_scenario('resume_switch', {'initial': INITIAL, 'target': TARGET, 'loss': 'after_commit'},
                        'pending', pending['status'], {'actual': [0, 8], 'receipt_preserved': True},
                        {'actual': self.service.actual_pair(),
                         'receipt_preserved': self.service.read_switch()[1]['receipt'] == result['receipt']},
                        ['transfer/resume.py', 'pools/commands.py', 'handover/replay.py'],
                        'The first real write is observed before restarting. Redelivery after completion adds no writes.')

    def test_resume_after_loss_before_commit(self):
        self._resume_with_first_loss('before')

    def test_no_receipt_before_last_commit(self):
        def is_last_step(command):
            candidate = dict(zip(('A', 'B'), self.service.actual_pair()))
            candidate[command.pool] = command.slots
            return candidate == TARGET

        self.service.lose_next('before', is_last_step)
        status, pending = self.service.switch()
        self.assertEqual(status, 202, pending)
        self.assert_pending(pending)
        self.assertNotEqual(self.service.actual_pair(), (0, 8))
        self.assert_band(self.service.commits)
        self.assertEqual(self.service.switch()[1]['allocation'], TARGET)
        self.assert_band(self.service.commits)

    def test_admission_uses_applied_quota_while_switch_is_pending(self):
        for number in range(8):
            self.assertEqual(self.service.segment(f'active-{number}')[1]['pool'], 'A')
        self.assertEqual(self.service.segment('waiting')[1]['status'], 'queued')
        self.service.lose_next('after', lambda cmd: cmd.pool == 'B' and cmd.slots > 0)
        status, pending = self.service.switch()
        self.assertEqual(status, 202, pending)
        self.assert_pending(pending)
        self.assertEqual(self.service.segment('waiting')[1]['pool'], 'B')
        self.assertEqual(self.service.in_flight('A'), 8)
        self.assert_band(self.service.commits)
        self.assertEqual(self.service.switch()[1]['allocation'], TARGET)
        self.assertEqual(self.service.complete('active-0', 'A')[1]['status'], 'completed')
        self.assertEqual(self.service.in_flight('A'), 7)
        self.assertEqual(self.service.segment('following')[1]['pool'], 'B')

    def test_pool_commitments_reserved_during_unanswered_transfer(self):
        self.service.lose_next('before')
        status, pending = self.service.switch()
        self.assertEqual(status, 202, pending)
        self.assert_pending(pending)
        self.assertEqual(self.service.actual_pair(), (8, 0))
        status, rejected = self.service.open_room(room='other', initial={'A': 0, 'B': 6})
        self.assertEqual((status, rejected['error']), (400, 'pool_capacity'))
        self.assertEqual(self.service.actual_pair('other'), (None, None))
        self.assertEqual(self.service.switch()[1]['allocation'], TARGET)

    def test_concurrent_same_number_replays_one_result(self):
        with ThreadPoolExecutor(max_workers=2) as callers:
            first = callers.submit(self.service.switch)
            second = callers.submit(self.service.switch)
            status, result = first.result(timeout=10)
            self.assertEqual((status, result['allocation']), (200, TARGET))
            self.assertEqual(second.result(timeout=10), (200, result))
        self.assert_band(self.service.commits)
        _, handover = self.service.handover()
        self.assertEqual(handover['receipts'], [result])
