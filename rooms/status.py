from dataclasses import dataclass

from rooms.band import RoomBand, RuleError
from rooms.registration import read_registration


@dataclass(frozen=True)
class RoomStatus:
    room: str
    band: RoomBand
    status: str


def read_room_status(db, room):
    registration = read_registration(db, room)
    if registration is None:
        raise RuleError(404, 'room_not_found', 'Unknown room')
    return RoomStatus(room, registration.band, registration.status)


def require_open_room(db, room):
    status = read_room_status(db, room)
    if status.status != 'open':
        raise RuleError(409, 'room_not_open', 'Room is still opening')
    return status
