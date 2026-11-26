from pools.capacity import CapacityExceeded, fits_capacity


class QuotaConflict(Exception):
    pass


def read_committed_quota(db, room):
    row = db.execute('SELECT slots FROM quotas WHERE room = ?', (room,)).fetchone()
    return None if row is None else int(row[0])


def set_initial_quota(store, room, slots):
    with store.write_transaction() as db:
        original = read_committed_quota(db, room)
        if original is not None:
            if original != slots:
                raise QuotaConflict('Existing pool quota differs from the opening allocation')
            return original
        if not fits_capacity(db, room, slots):
            raise CapacityExceeded(f'Pool {store.name} cannot establish the initial quota')
        db.execute('INSERT INTO quotas (room, slots) VALUES (?, ?)', (room, str(slots)))
    return slots


def apply_quota_change(db, room, slots):
    if not fits_capacity(db, room, slots):
        raise CapacityExceeded('Command would exceed the pool commitment limit')
    cursor = db.execute('UPDATE quotas SET slots = ? WHERE room = ?', (str(slots), room))
    if cursor.rowcount != 1:
        raise QuotaConflict('Room has no established pool quota')
