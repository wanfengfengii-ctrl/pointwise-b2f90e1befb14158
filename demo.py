import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import LocalService


def require(response, status=200):
    actual, body = response
    if actual != status:
        raise RuntimeError(f'Expected HTTP {status}, got {actual}: {body}')
    return body


def show(event, result):
    print(json.dumps({'event': event, 'result': result}, sort_keys=True))


def main():
    samples = Path(__file__).resolve().parent / 'samples'
    program = json.loads((samples / 'show.json').read_text(encoding='utf-8'))
    segments = json.loads((samples / 'segments.json').read_text(encoding='utf-8'))
    opening = program['opening']
    room = opening['room']
    demand_query = {'room': room, 'cycle_work': program['cycle_work']}
    switch_id = program['maintenance_switch']
    with TemporaryDirectory() as directory, LocalService(directory, watch_room=room) as service:
        opened = require(service.request('/rooms', body=opening))
        show('opened', opened)
        admitted = [require(service.segment(room=room, **item)) for item in segments['before_maintenance']]
        first = segments['before_maintenance'][0]
        repeated = require(service.segment(room=room, **first))
        if repeated != admitted[0] or admitted[-1]['status'] != 'queued':
            raise RuntimeError('Initial admissions do not match the sample supply')
        show('gateway', {'first': repeated, 'queued': [item['segment'] for item in admitted if item['status'] == 'queued']})

        completed = require(service.complete(**program['completion']))
        show('completed', completed)
        demand = require(service.request('/demand', query=demand_query))
        if (demand['waiting_work'], demand['suggested_slots']) != (31, 8):
            raise RuntimeError(f'Unexpected sample demand: {demand}')
        show('demand_before_maintenance', demand)
        service.commits.clear()
        target = {pool: 0 if pool == program['maintenance_pool'] else demand['suggested_slots'] for pool in ('A', 'B')}
        result = require(service.switch(switch_id, target, room))
        trace = service.commits.copy()
        if not trace or not all(opening['floor'] <= sum(pair) <= opening['ceiling'] for _, pair in trace):
            raise RuntimeError(f'SLOT_BAND_BREACH in sample switch: {trace}')
        if result['allocation'] != target or service.actual_pair() != (target['A'], target['B']):
            raise RuntimeError('The maintenance target is not effective')
        show('maintenance_commits', trace)
        show('maintenance_receipt', result)
        following = require(service.segment(room=room, **segments['after_maintenance']))
        if following['pool'] != 'B':
            raise RuntimeError('The new segment should use pool B')
        show('new_caption', following)
        empty = require(service.request('/demand', query=demand_query))
        if (empty['waiting_work'], empty['suggested_slots']) != (0, opening['floor']):
            raise RuntimeError(f'Unexpected demand after draining the queue: {empty}')
        show('empty_queue_demand', empty)

        service.restart()
        require(service.switch(program['return_switch'], opening['initial'], room))
        original = require(service.read_switch(switch_id, room))
        current = require(service.handover(room))
        if original != result or current['pools']['A']['slots'] != 8 or current['pools']['B']['slots'] != 0:
            raise RuntimeError('Original confirmation and current supply do not reconcile')
        show('handover', current)


if __name__ == '__main__':
    main()
