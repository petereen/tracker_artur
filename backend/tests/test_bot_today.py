import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot import handlers


def test_ask_question_sends_directly_to_command_message(monkeypatch):
    class Callback:
        pass

    monkeypatch.setattr(handlers, "CallbackQuery", Callback)
    message = SimpleNamespace(answer=AsyncMock())
    state = SimpleNamespace(update_data=AsyncMock())
    question = SimpleNamespace(id=7, text="Өнөөдөр хэдэн ажил хийсэн бэ?", answer_type="integer")

    asyncio.run(handlers._ask_question(message, question, state, session_id=11, q_index=0, questions=[question]))

    message.answer.assert_awaited_once()
    assert "Асуулт 1/1" in message.answer.await_args.args[0]
    state.update_data.assert_awaited_once_with(session_id=11, q_index=0, questions=[7])


def test_ask_question_sends_callback_followup_to_its_message(monkeypatch):
    class Callback:
        def __init__(self):
            self.message = SimpleNamespace(answer=AsyncMock())

    monkeypatch.setattr(handlers, "CallbackQuery", Callback)
    callback = Callback()
    state = SimpleNamespace(update_data=AsyncMock())
    question = SimpleNamespace(id=8, text="Тайлбар", answer_type="text")

    asyncio.run(handlers._ask_question(callback, question, state, session_id=12, q_index=1, questions=[question, question]))

    callback.message.answer.assert_awaited_once()
    assert "Асуулт 2/2" in callback.message.answer.await_args.args[0]
