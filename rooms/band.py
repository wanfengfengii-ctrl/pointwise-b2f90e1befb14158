from dataclasses import dataclass


POOL_NAMES = ('A', 'B')


class RuleError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class RoomBand:
    floor: int
    ceiling: int

    def contains(self, slots):
        return self.floor <= slots <= self.ceiling

    def clamp(self, slots):
        return max(self.floor, min(self.ceiling, slots))


def validate_band(floor, ceiling):
    if type(floor) is not int or type(ceiling) is not int or not 0 <= floor < ceiling:
        raise RuleError(400, 'invalid_band', 'Expected integers with 0 <= floor < ceiling')
    return RoomBand(floor, ceiling)


def validate_allocation(value, band):
    if not isinstance(value, dict) or set(value) != set(POOL_NAMES):
        raise RuleError(400, 'invalid_allocation', 'An allocation requires exactly A and B')
    slots = tuple(value[pool] for pool in POOL_NAMES)
    if any(type(count) is not int or count < 0 for count in slots):
        raise RuleError(400, 'invalid_allocation', 'Pool slots must be nonnegative integers')
    if not band.contains(sum(slots)):
        raise RuleError(400, 'outside_band', 'Total slots are outside the room service band')
    return slots
