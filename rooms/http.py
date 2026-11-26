import argparse
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from handover.receipts import initialize_receipts
from handover.replay import read_switch
from handover.summary import read_handover
from pools.capacity import CapacityExceeded, fits_capacity, seed_capacity
from pools.commands import DeliveryUncertain, submit_quota_command
from pools.readback import read_pool
from pools.storage import PoolStore, is_unavailable
from rooms.band import POOL_NAMES, RuleError
from rooms.lifecycle import open_room
from rooms.registration import initialize_rooms, opening_allocations, read_registration
from rooms.status import read_room_status
from transfer.requests import start_switch
from transfer.store import active_targets, initialize_switch_store
from work.admission import dispatch_waiting, submit_segment
from work.completion import complete_segment
from work.demand import read_demand
from work.segments import initialize_segments


class ServiceRuntime:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.pools = {pool: PoolStore(self.directory / f'pool-{pool}.sqlite3', pool) for pool in POOL_NAMES}
        self.transport = self.apply_command

    @contextmanager
    def transaction(self, *, write=False):
        path = self.directory / 'service.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA foreign_keys = ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            with db:
                yield db

    def require_capacity(self, db, room, allocation):
        promises = opening_allocations(db) | active_targets(db)
        for index, pool in enumerate(POOL_NAMES):
            reserved = {owner: promise[index] for owner, promise in promises.items()}
            try:
                with self.pools[pool].open() as pool_db:
                    fits = fits_capacity(pool_db, room, allocation[index], reserved)
            except sqlite3.OperationalError as error:
                if not is_unavailable(error):
                    raise
                raise RuleError(503, 'pool_unconfirmed', f'Cannot verify capacity of pool {pool}') from error
            if not fits:
                raise RuleError(400, 'pool_capacity', f'Pool {pool} cannot honor the allocation')

    def apply_command(self, command):
        with self.transaction(write=True) as db:
            outcome = submit_quota_command(self.pools[command.pool], command)
            if outcome.status == 'committed':
                dispatch_waiting(db, self.pools, command.room)
            return outcome

    def send_command(self, command):
        try:
            return self.transport(command)
        except (DeliveryUncertain, CapacityExceeded):
            return None
        except sqlite3.OperationalError as error:
            if not is_unavailable(error):
                raise
            return None


def create_runtime(directory, *, capacities=None):
    capacities = {'A': 16, 'B': 16} if capacities is None else capacities
    if set(capacities) != set(POOL_NAMES) or any(type(value) is not int or value < 0 for value in capacities.values()):
        raise ValueError('Expected nonnegative integer capacity defaults for both pools')
    runtime = ServiceRuntime(directory)
    runtime.directory.mkdir(parents=True, exist_ok=True)
    with runtime.transaction(write=True) as db:
        initialize_rooms(db)
        initialize_segments(db)
        initialize_switch_store(db)
        initialize_receipts(db)
    for pool, store in runtime.pools.items():
        store.initialize()
        seed_capacity(store, capacities[pool])
    return runtime


def _require_fields(data, *names):
    if set(data) != set(names):
        raise RuleError(400, 'invalid_fields', 'Expected fields: ' + ', '.join(names))


def _identifier(data, field):
    value = data[field]
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise RuleError(400, 'invalid_identifier', f'{field} must be a nonempty identifier')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise RuleError(400, 'invalid_identifier', f'{field} must be valid UTF-8') from error
    return value


def _pool_name(data):
    pool = data['pool']
    if pool not in POOL_NAMES:
        raise RuleError(400, 'unknown_pool', 'Pool must be A or B')
    return pool


class LiveCaptionHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve(self._get)

    def do_POST(self):
        self._serve(self._post)

    def _serve(self, route):
        try:
            status, body = route()
        except RuleError as error:
            status, body = error.status, {'error': error.code, 'message': str(error)}
        except CapacityExceeded:
            status, body = 409, {'error': 'pool_capacity', 'message': 'Pool capacity is unavailable'}
        except sqlite3.Error as error:
            self.log_error('Storage operation failed: %s', error)
            status, body = 500, {'error': 'storage_error'}
        encoded = json.dumps(body, ensure_ascii=True, sort_keys=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self):
        try:
            length = int(self.headers.get('Content-Length', ''))
            if not 0 < length <= 65536:
                raise ValueError('Unexpected request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
        except (ValueError, RecursionError) as error:
            raise RuleError(400, 'invalid_json', 'Expected a JSON object up to 64 KiB') from error
        return data

    def _post(self):
        runtime = self.server.runtime
        path = urlsplit(self.path).path
        data = self._read_json()
        if path == '/rooms':
            _require_fields(data, 'room', 'floor', 'ceiling', 'initial')
            result = open_room(runtime, _identifier(data, 'room'), data['floor'], data['ceiling'], data['initial'])
            return (200 if result.status == 'open' else 202), result.as_dict()
        if path == '/segments':
            _require_fields(data, 'room', 'segment', 'work')
            with runtime.transaction(write=True) as db:
                result = submit_segment(db, runtime.pools, _identifier(data, 'room'),
                                        _identifier(data, 'segment'), data['work'])
            return 200, result.as_dict()
        if path == '/segments/complete':
            _require_fields(data, 'segment', 'pool')
            with runtime.transaction(write=True) as db:
                result = complete_segment(db, runtime.pools, _identifier(data, 'segment'), _pool_name(data))
            return 200, result.as_dict()
        if path == '/switches':
            _require_fields(data, 'room', 'switch_id', 'target')
            result = start_switch(runtime, _identifier(data, 'room'), _identifier(data, 'switch_id'), data['target'])
            return (200 if result['status'] == 'completed' else 202), result
        raise RuleError(404, 'route_not_found', 'Unknown request path')

    def _get(self):
        runtime = self.server.runtime
        parts = urlsplit(self.path)
        try:
            items = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
        except ValueError as error:
            raise RuleError(400, 'invalid_query', 'Malformed query parameters') from error
        data = dict(items)
        if len(data) != len(items):
            raise RuleError(400, 'invalid_query', 'Repeated query parameter')

        path = parts.path
        fields = {
            '/rooms': ('room',), '/demand': ('room', 'cycle_work'),
            '/switches': ('room', 'switch_id'), '/pools': ('room', 'pool'), '/handover': ('room',),
        }
        if path not in fields:
            raise RuleError(404, 'route_not_found', 'Unknown request path')
        _require_fields(data, *fields[path])
        room = _identifier(data, 'room')
        with runtime.transaction(write=path == '/handover') as db:
            if path == '/rooms':
                read_room_status(db, room)
                return 200, read_registration(db, room).as_dict()
            if path == '/demand':
                try:
                    rate = int(data['cycle_work'])
                except ValueError as error:
                    raise RuleError(400, 'invalid_cycle_work', 'Cycle work must be a positive integer') from error
                return 200, asdict(read_demand(db, room, rate))
            if path == '/switches':
                return 200, read_switch(db, room, _identifier(data, 'switch_id'))
            if path == '/pools':
                read_room_status(db, room)
                reading = read_pool(runtime.pools[_pool_name(data)], room)
                return (200 if reading.confirmed else 503), reading.as_dict()
            return 200, read_handover(db, runtime.pools, room).as_dict()


def make_server(runtime, host, port, handler=LiveCaptionHandler):
    server = ThreadingHTTPServer((host, port), handler)
    server.runtime = runtime
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Live caption rendering supply service')
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--capacity-a', type=int, default=16)
    parser.add_argument('--capacity-b', type=int, default=16)
    parser.add_argument('--initialize-only', action='store_true')
    args = parser.parse_args(argv)
    if min(args.capacity_a, args.capacity_b) < 0:
        parser.error('Capacity defaults must be nonnegative')
    runtime = create_runtime(args.data_dir, capacities={'A': args.capacity_a, 'B': args.capacity_b})
    if args.initialize_only:
        return
    with make_server(runtime, args.host, args.port) as server:
        bound_host, bound_port = server.server_address
        print(f'Listening at http://{bound_host}:{bound_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
