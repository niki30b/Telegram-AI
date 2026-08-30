import aiogram
from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
	API_Key = State()
	Behavior = State()