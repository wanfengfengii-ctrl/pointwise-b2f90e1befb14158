from handover.replay import read_switch
from rooms.band import RuleError, validate_allocation
from rooms.status import require_open_room
from transfer.exclusivity import claim_active_switch
from transfer.resume import resume_switch
from transfer.store import create_request, read_request


def validate_switch_target(runtime, db, status, target):
    allocation = validate_allocation(target, status.band)
    runtime.require_capacity(db, status.room, allocation)
    return allocation


def start_switch(runtime, room, switch_id, target):
    with runtime.transaction(write=True) as db:
        status = require_open_room(db, room)
        request = read_request(db, room, switch_id)
        if request is None:
            allocation = validate_switch_target(runtime, db, status, target)
            request = create_request(db, room, switch_id, allocation)
            claim_active_switch(db, request)
        else:
            allocation = validate_allocation(target, status.band)
            if allocation != request.target:
                raise RuleError(409, 'switch_conflict', 'Switch number is bound to another target')
            if request.status == 'completed':
                return read_switch(db, room, switch_id)
    return resume_switch(runtime, room, switch_id)
