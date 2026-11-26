import sqlite3

from pools.quotas import QuotaConflict, set_initial_quota
from pools.readback import read_pool
from pools.storage import is_unavailable
from rooms.band import POOL_NAMES, RuleError, validate_allocation, validate_band
from rooms.registration import activate_registration, read_registration, register_room


def confirm_open(db, pools, registration):
    if registration.status == 'open':
        return registration
    actual = tuple(read_pool(pools[pool], registration.room).slots for pool in POOL_NAMES)
    if actual == registration.initial:
        return activate_registration(db, registration.room)
    return registration


def open_room(runtime, room, floor, ceiling, initial):
    band = validate_band(floor, ceiling)
    allocation = validate_allocation(initial, band)
    with runtime.transaction(write=True) as db:
        if read_registration(db, room) is None:
            runtime.require_capacity(db, room, allocation)
        registration = register_room(db, room, band, allocation)
    if registration.status == 'open':
        return registration

    for pool, slots in zip(POOL_NAMES, allocation):
        with runtime.transaction(write=True) as db:
            registration = read_registration(db, room)
            if registration.status == 'open':
                return registration
            try:
                set_initial_quota(runtime.pools[pool], room, slots)
            except sqlite3.OperationalError as error:
                if not is_unavailable(error):
                    raise
                return registration
            except QuotaConflict as error:
                raise RuleError(409, 'initial_quota_conflict', str(error)) from error

    with runtime.transaction(write=True) as db:
        return confirm_open(db, runtime.pools, read_registration(db, room))
