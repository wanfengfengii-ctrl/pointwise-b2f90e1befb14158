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


def _read_history(db, command):
    """Return the recorded slots for this exact command identity, or None."""
    row = db.execute('''SELECT slots FROM delivery_history
                        WHERE room = ? AND switch_id = ? AND step_id = ?''',
                     (command.room, command.switch_id, command.step_id)).fetchone()
    return None if row is None else int(row[0])


def _latest_step(db, room, switch_id):
    row = db.execute('''SELECT MAX(step_id) FROM delivery_history
                        WHERE room = ? AND switch_id = ?''', (room, switch_id)).fetchone()
    return row[0]


def read_command_outcome(store, command, *, transaction=None):
    _check_address(store, command)
    if transaction is not None:
        return _read_history(transaction, command)
    with store.open() as db:
        return _read_history(db, command)


def submit_quota_command(store, command):
    with store.write_transaction() as db:
        _check_address(store, command)
        recorded = _read_history(db, command)
        if recorded is not None:
            # Same identity, same parameters: the original commit stands and the
            # quota must not move again. Different parameters are a hard conflict.
            if recorded != command.slots:
                raise QuotaConflict('Step identity is bound to a different command')
            return CommandOutcome(command, 'committed')

        latest = _latest_step(db, command.room, command.switch_id)
        if latest is not None and command.step_id < latest:
            # A late delivery from an earlier step of this switch: it can never
            # change the quota again, even if the caller never saw its reply.
            return CommandOutcome(command, 'superseded')

        apply_quota_change(db, command.room, command.slots)
        db.execute('''INSERT INTO delivery_history (room, switch_id, step_id, slots)
                      VALUES (?, ?, ?, ?)''',
                   (command.room, command.switch_id, command.step_id, str(command.slots)))
    return CommandOutcome(command, 'committed')
