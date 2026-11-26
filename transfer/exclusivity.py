from rooms.band import RuleError


def read_active_switch(db, room):
    row = db.execute('SELECT switch_id FROM active_switches WHERE room = ?', (room,)).fetchone()
    return None if row is None else row[0]


def claim_active_switch(db, request):
    if read_active_switch(db, request.room) is not None:
        raise RuleError(409, 'switch_in_progress', 'Another switch is pending for this room')
    db.execute('INSERT INTO active_switches (room, switch_id) VALUES (?, ?)',
               (request.room, request.switch_id))


def release_active_switch(db, request):
    row = db.execute('DELETE FROM active_switches WHERE room = ? AND switch_id = ?',
                     (request.room, request.switch_id))
    if row.rowcount != 1:
        raise RuntimeError('Switch does not own the active position')
