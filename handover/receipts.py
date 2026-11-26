import hashlib
import json
from dataclasses import dataclass

from rooms.band import POOL_NAMES


@dataclass(frozen=True)
class SwitchReceipt:
    room: str
    switch_id: str
    allocation: tuple[int, int]
    receipt: str

    def as_dict(self):
        return {'room': self.room, 'switch_id': self.switch_id, 'status': 'completed',
                'allocation': dict(zip(POOL_NAMES, self.allocation)), 'receipt': self.receipt}


def initialize_receipts(db):
    db.execute('''CREATE TABLE IF NOT EXISTS receipts (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        room TEXT NOT NULL,
        switch_id TEXT NOT NULL,
        actual_a TEXT NOT NULL,
        actual_b TEXT NOT NULL,
        receipt TEXT NOT NULL UNIQUE,
        UNIQUE (room, switch_id),
        FOREIGN KEY (room, switch_id) REFERENCES switches(room, switch_id)
    )''')


def write_receipt(db, room, switch_id, allocation):
    payload = json.dumps([room, switch_id, *allocation], ensure_ascii=True, separators=(',', ':'))
    token = 'caption-' + hashlib.sha256(payload.encode('ascii')).hexdigest()
    db.execute('INSERT INTO receipts (room, switch_id, actual_a, actual_b, receipt) VALUES (?, ?, ?, ?, ?)',
               (room, switch_id, str(allocation[0]), str(allocation[1]), token))
    return SwitchReceipt(room, switch_id, allocation, token)


def _from_row(room, row):
    switch_id, a, b, receipt = row
    return SwitchReceipt(room, switch_id, (int(a), int(b)), receipt)


def find_receipt(db, room, switch_id):
    row = db.execute('SELECT switch_id, actual_a, actual_b, receipt FROM receipts WHERE room = ? AND switch_id = ?',
                     (room, switch_id)).fetchone()
    return None if row is None else _from_row(room, row)


def list_confirmed_receipts(db, room):
    rows = db.execute('SELECT switch_id, actual_a, actual_b, receipt FROM receipts WHERE room = ? ORDER BY sequence',
                      (room,))
    return [_from_row(room, row) for row in rows]
