from dataclasses import dataclass

from handover.pending import PendingSwitch, read_pending_switch
from handover.receipts import SwitchReceipt, list_confirmed_receipts
from pools.readback import PoolReading, read_pool
from rooms.band import POOL_NAMES
from rooms.status import read_room_status


@dataclass(frozen=True)
class HandoverSummary:
    room: str
    pools: tuple[PoolReading, ...]
    pending: PendingSwitch | None
    receipts: list[SwitchReceipt]

    def as_dict(self):
        total = None
        if all(reading.confirmed for reading in self.pools):
            total = sum(reading.slots for reading in self.pools)
        return {
            'room': self.room,
            'pools': {reading.pool: reading.as_dict() for reading in self.pools},
            'total': total,
            'pending': None if self.pending is None else self.pending.as_dict(),
            'receipts': [receipt.as_dict() for receipt in self.receipts],
        }


def read_handover(db, pools, room):
    read_room_status(db, room)
    readings = tuple(read_pool(pools[pool], room) for pool in POOL_NAMES)
    return HandoverSummary(room, readings, read_pending_switch(db, room), list_confirmed_receipts(db, room))
