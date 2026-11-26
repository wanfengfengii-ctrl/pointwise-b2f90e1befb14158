import sqlite3
from dataclasses import dataclass

from pools.quotas import read_committed_quota
from pools.storage import is_unavailable


@dataclass(frozen=True)
class PoolReading:
    pool: str
    slots: int | None

    @property
    def confirmed(self):
        return self.slots is not None

    def as_dict(self):
        return {'pool': self.pool, 'slots': self.slots,
                'status': 'confirmed' if self.confirmed else 'unconfirmed'}


def read_pool(store, room):
    try:
        with store.open() as db:
            return PoolReading(store.name, read_committed_quota(db, room))
    except sqlite3.OperationalError as error:
        if not is_unavailable(error):
            raise
        return PoolReading(store.name, None)
