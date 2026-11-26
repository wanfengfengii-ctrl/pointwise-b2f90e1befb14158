from work.segments import segment_from_row


def next_waiting_segment(db, room):
    return segment_from_row(db.execute('''
        SELECT segment, room, work, status, pool FROM segments
        WHERE room = ? AND status = 'queued' ORDER BY sequence LIMIT 1
    ''', (room,)).fetchone())


def sum_waiting_work(db, room):
    return sum(int(work) for (work,) in db.execute(
        "SELECT work FROM segments WHERE room = ? AND status = 'queued'", (room,)
    ))
