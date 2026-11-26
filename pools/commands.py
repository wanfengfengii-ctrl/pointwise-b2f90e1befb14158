from dataclasses import dataclass

from pools.quotas import QuotaConflict, apply_quota_change


class DeliveryUncertain(Exception):
    """The caller did not get a definitive result from the pool port."""


@dataclass(frozen=True)
class PoolCommand:
    room: str
    switch_id: str
    step_id: int
    pool: str
    slots: int


@dataclass(frozen=True)
class CommandOutcome:
    command: PoolCommand
    status: str


def _check_address(store, command):
    if command.pool != store.name or type(command.step_id) is not int or command.step_id < 1:
        raise QuotaConflict('Command has an invalid pool or step identity')
    if type(command.slots) is not int or command.slots < 0:
        raise QuotaConflict('Command has an invalid slot count')


def _read_latest_outcome(db, command):
    row = db.execute('SELECT switch_id, step_id, slots FROM latest_delivery WHERE room = ?',
                     (command.room,)).fetchone()
    if row is None or row[:2] != (command.switch_id, command.step_id):
        return None
    if int(row[2]) != command.slots:
        raise QuotaConflict('Step identity is bound to a different command')
    return CommandOutcome(command, 'committed')


def read_command_outcome(store, command, *, transaction=None):
    _check_address(store, command)
    if transaction is not None:
        return _read_latest_outcome(transaction, command)
    with store.open() as db:
        return _read_latest_outcome(db, command)


def submit_quota_command(store, command):
    with store.write_transaction() as db:
        original = read_command_outcome(store, command, transaction=db)
        if original is not None:
            return original
        apply_quota_change(db, command.room, command.slots)
        db.execute('''INSERT INTO latest_delivery (room, switch_id, step_id, slots) VALUES (?, ?, ?, ?)
                      ON CONFLICT (room) DO UPDATE SET switch_id = excluded.switch_id,
                          step_id = excluded.step_id, slots = excluded.slots''',
                   (command.room, command.switch_id, command.step_id, str(command.slots)))
    return CommandOutcome(command, 'committed')
