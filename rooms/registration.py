from dataclasses import dataclass

from rooms.band import POOL_NAMES, RoomBand, RuleError


@dataclass(frozen=True)
class RoomRegistration:
    room: str
    band: RoomBand
    initial: tuple[int, int]
    status: str

    def as_dict(self):
        return {
            'room': self.room,
            'floor': self.band.floor,
            'ceiling': self.band.ceiling,
            'initial': dict(zip(POOL_NAMES, self.initial)),
            'status': self.status,
        }


def initialize_rooms(db):
    db.execute('''CREATE TABLE IF NOT EXISTS rooms (
        room TEXT PRIMARY KEY NOT NULL,
        floor TEXT NOT NULL,
        ceiling TEXT NOT NULL,
        initial_a TEXT NOT NULL,
        initial_b TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('opening', 'open'))
    )''')


def read_registration(db, room):
    row = db.execute(
        'SELECT floor, ceiling, initial_a, initial_b, status FROM rooms WHERE room = ?',
        (room,),
    ).fetchone()
    if row is None:
        return None
    floor, ceiling, initial_a, initial_b, status = row
    return RoomRegistration(room, RoomBand(int(floor), int(ceiling)),
                            (int(initial_a), int(initial_b)), status)


def register_room(db, room, band, initial):
    original = read_registration(db, room)
    if original is not None:
        if (original.band, original.initial) != (band, initial):
            raise RuleError(409, 'room_conflict', 'Room already has a different registration')
        return original
    db.execute('''INSERT INTO rooms (room, floor, ceiling, initial_a, initial_b, status)
                  VALUES (?, ?, ?, ?, ?, 'opening')''',
               (room, str(band.floor), str(band.ceiling), str(initial[0]), str(initial[1])))
    return RoomRegistration(room, band, initial, 'opening')


def opening_allocations(db):
    return {
        room: (int(a), int(b))
        for room, a, b in db.execute(
            "SELECT room, initial_a, initial_b FROM rooms WHERE status = 'opening'"
        )
    }


def activate_registration(db, room):
    db.execute("UPDATE rooms SET status = 'open' WHERE room = ? AND status = 'opening'", (room,))
    return read_registration(db, room)
