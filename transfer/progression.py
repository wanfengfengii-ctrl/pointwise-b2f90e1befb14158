from handover.receipts import write_receipt
from pools.commands import PoolCommand
from pools.readback import read_pool
from rooms.band import POOL_NAMES
from rooms.status import require_open_room
from transfer.exclusivity import read_active_switch, release_active_switch
from transfer.store import mark_switch_completed, next_delivery_attempt, read_request


def choose_next_adjustment(band, current, target):
    total = sum(current)
    for index, pool in enumerate(POOL_NAMES):
        slots = current[index]
        delta = target[index] - slots
        if delta == 0:
            continue
        if delta < 0 and total > band.floor:
            delta = max(delta, band.floor - total)
        elif delta > 0 and total < band.ceiling:
            delta = min(delta, band.ceiling - total)
        return pool, slots + delta
    return None


def next_command(runtime, room, switch_id):
    with runtime.transaction(write=True) as db:
        request = read_request(db, room, switch_id)
        if request is None or request.status == 'completed':
            return None
        if read_active_switch(db, room) != switch_id:
            raise RuntimeError('Pending switch does not own the active position')
        actual = tuple(read_pool(runtime.pools[pool], room).slots for pool in POOL_NAMES)
        if None in actual:
            return None
        if actual == request.target:
            mark_switch_completed(db, request)
            write_receipt(db, room, switch_id, request.target)
            release_active_switch(db, request)
            return None

        band = require_open_room(db, room).band
        pool, slots = choose_next_adjustment(band, actual, request.target)
        attempt = next_delivery_attempt(db, request)
        return PoolCommand(room, switch_id, attempt, pool, slots)
