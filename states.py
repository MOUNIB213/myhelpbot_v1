from aiogram.fsm.state import State, StatesGroup


class AIChatStates(StatesGroup):
    chatting = State()
    entering_end_code = State()


class ProjectVaultStates(StatesGroup):
    entering_name = State()
    entering_category = State()
    entering_description = State()
    entering_keywords = State()
    uploading_files = State()
    searching_project = State()


class LinkVaultStates(StatesGroup):
    entering_title = State()
    entering_url = State()
    entering_category = State()
    entering_description = State()
    searching_links = State()


class NoteStates(StatesGroup):
    entering_title = State()
    entering_content = State()


class TaskStates(StatesGroup):
    entering_title = State()
    entering_priority = State()


class ReminderStates(StatesGroup):
    entering_message = State()
    entering_minutes = State()


class GlobalSearchStates(StatesGroup):
    entering_query = State()


class InBotAdminStates(StatesGroup):
    adding_user_id = State()
    adding_user_role = State()
    removing_user_id = State()
    updating_gemini_key = State()
    updating_config_value = State()
    sending_broadcast_text = State()
