from handover.receipts import find_receipt
from rooms.band import RuleError
from transfer.store import read_request


def read_switch(db, room, switch_id):
    request = read_request(db, room, switch_id)
    if request is None:
        raise RuleError(404, 'switch_not_found', 'Unknown switch number for this room')
    if request.status == 'pending':
        return {'room': room, 'switch_id': switch_id, 'status': 'pending'}
    receipt = find_receipt(db, room, switch_id)
    if receipt is None:
        raise RuntimeError('Completed switch has no persisted receipt')
    return receipt.as_dict()
