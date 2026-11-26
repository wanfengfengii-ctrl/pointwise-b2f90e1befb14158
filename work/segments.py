from dataclasses import dataclass

from rooms.band import RuleError


@dataclass(frozen=True)
class CaptionSegment:
    segment: str
    room: str
    work: int
    status: str
    pool: str | None

    def as_dict(self):
        return {'segment': self.segment, 'room': self.room, 'work': self.work,
                'status': self.status, 'pool': self.pool}


def initialize_segments(db):
    db.execute('''CREATE TABLE IF NOT EXISTS segments (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        segment TEXT NOT NULL UNIQUE,
        room TEXT NOT NULL REFERENCES rooms(room),
        work TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued', 'admitted', 'completed')),
        pool TEXT CHECK (pool IN ('A', 'B')),
        CHECK ((status = 'queued' AND pool IS NULL) OR (status <> 'queued' AND pool IS NOT NULL))
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS segments_room_queue ON segments(room, status, sequence)')
    db.execute('CREATE INDEX IF NOT EXISTS segments_room_pool ON segments(room, status, pool)')


def segment_from_row(row):
    if row is None:
        return None
    segment, room, work, status, pool = row
    return CaptionSegment(segment, room, int(work), status, pool)


def read_segment(db, segment):
    return segment_from_row(db.execute(
        'SELECT segment, room, work, status, pool FROM segments WHERE segment = ?', (segment,)
    ).fetchone())


def register_segment(db, room, segment, work):
    if type(work) is not int or work <= 0:
        raise RuleError(400, 'invalid_work', 'Work must be a positive integer')
    original = read_segment(db, segment)
    if original is not None:
        if (original.room, original.work) != (room, work):
            raise RuleError(409, 'segment_conflict', 'Segment already has different parameters')
        return original
    db.execute("INSERT INTO segments (segment, room, work, status) VALUES (?, ?, ?, 'queued')",
               (segment, room, str(work)))
    return CaptionSegment(segment, room, work, 'queued', None)
