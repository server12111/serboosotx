"""FSM state groups referenced from more than one layer (e.g. both a handler and a
background service) live here instead of inside a handler module, to avoid a
services -> handlers -> services import cycle."""
from aiogram.fsm.state import State, StatesGroup


class OrderStates(StatesGroup):
    waiting_link = State()
    waiting_quantity = State()
    confirming = State()
