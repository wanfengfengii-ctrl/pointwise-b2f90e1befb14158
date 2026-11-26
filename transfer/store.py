from dataclasses import dataclass


@dataclass(frozen=True)
class SwitchRequest:
    room: str
    switch_id: str
    target: tuple[int, int]
    status: str


def initialize_switch_store(db):
    db.execute('''CREATE TABLE IF NOT EXISTS switches (
        room TEXT NOT NULL REFERENCES rooms(room),
        switch_id TEXT NOT NULL,
        target_a TEXT NOT NULL,
        target_b TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'completed')),
        PRIMARY KEY (room, switch_id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS active_switches (
        room TEXT PRIMARY KEY NOT NULL,
        switch_id TEXT NOT NULL,
        FOREIGN KEY (room, switch_id) REFERENCES switches(room, switch_id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS switch_dispatch_counts (
        room TEXT NOT NULL,
        switch_id TEXT NOT NULL,
        attempts INTEGER NOT NULL CHECK (attempts > 0),
        PRIMARY KEY (room, switch_id),
        FOREIGN KEY (room, switch_id) REFERENCES switches(room, switch_id)
    )''')


def create_request(db, room, switch_id, target):
    db.execute("INSERT INTO switches VALUES (?, ?, ?, ?, 'pending')",
               (room, switch_id, str(target[0]), str(target[1])))
    return SwitchRequest(room, switch_id, target, 'pending')


def read_request(db, room, switch_id):
    row = db.execute('SELECT target_a, target_b, status FROM switches WHERE room = ? AND switch_id = ?',
                     (room, switch_id)).fetchone()
    if row is None:
        return None
    a, b, status = row
    return SwitchRequest(room, switch_id, (int(a), int(b)), status)


def active_targets(db):
    return {
        room: (int(a), int(b))
        for room, a, b in db.execute('''
            SELECT s.room, s.target_a, s.target_b FROM switches AS s
            JOIN active_switches AS a ON a.room = s.room AND a.switch_id = s.switch_id
        ''')
    }


def next_delivery_attempt(db, request):
    key = (request.room, request.switch_id)
    db.execute('''INSERT INTO switch_dispatch_counts (room, switch_id, attempts) VALUES (?, ?, 1)
                  ON CONFLICT (room, switch_id) DO UPDATE SET attempts = attempts + 1''', key)
    return db.execute('''SELECT attempts FROM switch_dispatch_counts
                         WHERE room = ? AND switch_id = ?''', key).fetchone()[0]


def mark_switch_completed(db, request):
    row = db.execute("UPDATE switches SET status = 'completed' WHERE room = ? AND switch_id = ? AND status = 'pending'",
                     (request.room, request.switch_id))
    if row.rowcount != 1:
        raise RuntimeError('Expected one pending switch during confirmation')
