from dataclasses import dataclass

from rooms.band import RuleError
from rooms.status import read_room_status
from work.queue import sum_waiting_work


@dataclass(frozen=True)
class DemandEstimate:
    waiting_work: int
    suggested_slots: int
    cycle_work: int


def estimate_slots(waiting_work, cycle_work, band):
    if type(cycle_work) is not int or cycle_work <= 0:
        raise RuleError(400, 'invalid_cycle_work', 'Cycle work must be a positive integer')
    required = (waiting_work + cycle_work - 1) // cycle_work
    return DemandEstimate(waiting_work, band.clamp(required), cycle_work)


def read_demand(db, room, cycle_work):
    try:
        status = read_room_status(db, room)
    except RuleError as error:
        raise RuleError(400, 'unknown_demand_room', 'Demand requires a known room') from error
    return estimate_slots(sum_waiting_work(db, room), cycle_work, status.band)
