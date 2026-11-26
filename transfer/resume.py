from handover.replay import read_switch
from transfer.progression import next_command
from work.admission import dispatch_waiting


def resume_switch(runtime, room, switch_id):
    while True:
        command = next_command(runtime, room, switch_id)
        if command is None:
            break
        outcome = runtime.send_command(command)
        if outcome is None:
            break
        if outcome.command != command:
            raise RuntimeError('Pool replied to a different command')
        if outcome.status == 'superseded':
            # Another delivery already advanced this room past this step. Drop the
            # stale plan and recompute the next move from the actual pool state.
            continue
        if outcome.status != 'committed':
            raise RuntimeError('Pool did not confirm the requested adjustment')
        with runtime.transaction(write=True) as db:
            dispatch_waiting(db, runtime.pools, room)

    with runtime.transaction() as db:
        return read_switch(db, room, switch_id)
