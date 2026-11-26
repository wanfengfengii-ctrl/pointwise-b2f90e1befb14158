class CapacityExceeded(Exception):
    pass


def seed_capacity(store, slots):
    if type(slots) is not int or slots < 0:
        raise ValueError('Pool capacity must be a nonnegative integer')
    with store.write_transaction() as db:
        db.execute('INSERT OR IGNORE INTO capacity (singleton, slots) VALUES (1, ?)', (str(slots),))


def read_capacity(db):
    entry = db.execute('SELECT slots FROM capacity WHERE singleton = 1').fetchone()
    if entry is None:
        raise RuntimeError('Pool capacity configuration is missing')
    return int(entry[0])


def fits_capacity(db, room, slots, commitments=None):
    if type(slots) is not int or slots < 0:
        return False
    others = {
        owner: int(allocated)
        for owner, allocated in db.execute('SELECT room, slots FROM quotas WHERE room <> ?', (room,))
    }
    for owner, promised in (commitments or {}).items():
        if owner != room:
            others[owner] = max(others.get(owner, 0), promised)
    return slots + sum(others.values()) <= read_capacity(db)
