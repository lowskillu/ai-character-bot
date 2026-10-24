from aiogram.fsm.state import State, StatesGroup


class BroadcastState(StatesGroup):
    BS1 = State()
    BS2 = State()


# Three more state groups lived here and were never set or filtered on
# anywhere — three of the five groups were dead. Language is
# chosen with inline buttons, and the character wizard keeps everything in
# ProfileCustomizationState.


class ProfileCustomizationState(StatesGroup):
    customizing = State()
