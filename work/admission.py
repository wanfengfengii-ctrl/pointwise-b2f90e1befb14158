from pools.readback import read_pool
from rooms.band import POOL_NAMES
from rooms.status import require_open_room
from work.queue import next_waiting_segment
from work.segments import read_segment, register_segment


def count_in_flight(db, room, pool):
    return db.execute("SELECT COUNT(*) FROM segments WHERE room = ? AND pool = ? AND status = 'admitted'",
                      (room, pool)).fetchone()[0]


def dispatch_waiting(db, pools, room):
    waiting = next_waiting_segment(db, room)
    if waiting is None:
        return
    # The application writer transaction also gates room quota writes through the pool port.
    for pool in POOL_NAMES:
        actual = read_pool(pools[pool], room)
        if not actual.confirmed:
            continue
        available = actual.slots - count_in_flight(db, room, pool)
        for _ in range(available):
            db.execute("UPDATE segments SET status = 'admitted', pool = ? WHERE segment = ? AND status = 'queued'",
                       (pool, waiting.segment))
            waiting = next_waiting_segment(db, room)
            if waiting is None:
                return


def submit_segment(db, pools, room, segment, work):
    require_open_room(db, room)
    original = register_segment(db, room, segment, work)
    if original.status == 'queued':
        dispatch_waiting(db, pools, room)
        return read_segment(db, segment)
    return original
