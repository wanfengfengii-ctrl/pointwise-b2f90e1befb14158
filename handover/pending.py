from dataclasses import dataclass

from rooms.band import POOL_NAMES
from transfer.exclusivity import read_active_switch
from transfer.store import read_request


@dataclass(frozen=True)
class PendingSwitch:
    switch_id: str
    target: tuple[int, int]

    def as_dict(self):
        return {'switch_id': self.switch_id, 'status': 'pending',
                'target': dict(zip(POOL_NAMES, self.target))}


def read_pending_switch(db, room):
    switch_id = read_active_switch(db, room)
    if switch_id is None:
        return None
    request = read_request(db, room, switch_id)
    if request is None or request.status != 'pending':
        raise RuntimeError('Active position does not resolve to a pending switch')
    return PendingSwitch(switch_id, request.target)
