from rooms.band import RuleError
from work.admission import dispatch_waiting
from work.segments import read_segment


def complete_segment(db, pools, segment, pool):
    original = read_segment(db, segment)
    if original is None:
        raise RuleError(404, 'segment_not_found', 'Unknown segment')
    if original.status == 'queued':
        raise RuleError(409, 'segment_not_admitted', 'Queued segment has no pool assignment')
    if original.pool != pool:
        raise RuleError(409, 'wrong_pool', 'Completion must come from the original pool')
    if original.status == 'completed':
        return original
    db.execute("UPDATE segments SET status = 'completed' WHERE segment = ?", (segment,))
    dispatch_waiting(db, pools, original.room)
    return read_segment(db, segment)
