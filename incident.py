import argparse
import json
from tempfile import TemporaryDirectory

from pools.commands import submit_quota_command
from pools.quotas import QuotaConflict
from tests.support import INITIAL, LocalService, TARGET


FLOOR = 6
CEILING = 10


def require_status(response, expected):
    status, body = response
    if status != expected:
        raise RuntimeError(f'Expected HTTP {expected}, got {status}: {body}')
    return body


def require_pending(service):
    pending = require_status(service.read_switch(), 200)
    handover = require_status(service.handover(), 200)
    if pending['status'] != 'pending' or 'receipt' in pending or handover['receipts']:
        raise AssertionError(f'Early confirmation: {pending}, {handover}')


def inspect_case(case):
    with TemporaryDirectory() as directory, LocalService(directory) as service:
        require_status(service.open_room(floor=FLOOR, ceiling=CEILING), 200)
        service.commits.clear()
        held = None
        paused = None

        if case != 'band':
            service.lose_next(case)
            pending = require_status(service.switch(), 202)
            if pending['status'] != 'pending' or 'receipt' in pending:
                raise AssertionError(f'Unexpected response to unanswered delivery: {pending}')
            if len(service.held) != 1:
                raise RuntimeError('The fixture did not intercept exactly one delivery')
            held = service.held[0]
            paused = service.actual_pair()
            if bool(service.commits) != (case == 'after'):
                raise RuntimeError(f'The fixture did not produce the requested commit boundary: {case}')
            require_pending(service)
            service.restart()
            require_pending(service)

        result = require_status(service.switch(), 200)
        active = service.actual_pair()
        if (result['status'] != 'completed' or result['allocation'] != TARGET or not result.get('receipt')
                or active != (TARGET['A'], TARGET['B'])):
            raise AssertionError(f'Incorrect completed switch: {result}, live={active}')
        if not service.commits:
            raise RuntimeError('No actual pool commits were observed')
        if held is not None:
            try:
                submit_quota_command(service.runtime.pools[held.pool], held)
            except QuotaConflict:
                pass
        after_delivery = service.actual_pair()
        if require_status(service.switch(), 200) != result or require_status(service.read_switch(), 200) != result:
            raise AssertionError('The original receipt changed on reread')
        require_status(service.switch(target=INITIAL), 409)

        if any(type(slots) is not int for _, pair in service.commits for slots in pair):
            raise RuntimeError(f'Unconfirmed pool observation: {service.commits}')
        report = {'case': case, 'paused': paused, 'commits': service.commits,
                  'at_receipt': active, 'after_redelivery': after_delivery, 'receipt': result['receipt']}
        print(json.dumps(report, sort_keys=True), flush=True)
        breaches = [(pool, pair, sum(pair)) for pool, pair in service.commits
                    if not FLOOR <= sum(pair) <= CEILING]
        if breaches:
            print(f'SLOT_BAND_BREACH {case}: {breaches}', flush=True)
        if after_delivery != active:
            print(f'STALE_QUOTA_REAPPLIED {case}: {active} -> {after_delivery}', flush=True)
        return not breaches and after_delivery == active


def main():
    parser = argparse.ArgumentParser(description='Check the main-room maintenance switch')
    parser.add_argument('case', nargs='?', choices=('band', 'before', 'after', 'all'), default='all')
    selected = parser.parse_args().case
    cases = ('band', 'before', 'after') if selected == 'all' else (selected,)
    results = [inspect_case(case) for case in cases]
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
