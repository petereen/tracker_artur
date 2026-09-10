"""Render the stored preview without another model call or invented fields."""


def task_preview_text(preview: dict, language: str = "mn") -> str:
    labels = {
        "mn": ("Даалгаврын ноорог бэлэн боллоо", "Хариуцагч", "Оролцогчид", "Эхлэх", "Дуусах", "Хянагч", "Эрэмбэ", "Тайлбар", "Баталгаажуулбал үүсгэнэ."),
        "en": ("Task draft ready", "Owner", "Participants", "Start", "Deadline", "Reviewer", "Priority", "Description", "Confirm to create it."),
        "ru": ("Черновик задачи готов", "Ответственный", "Участники", "Начало", "Срок", "Проверяющий", "Приоритет", "Описание", "Подтвердите создание."),
    }
    title, owner, participants, start, end, reviewer, priority, description, confirm = labels.get(language, labels["en"])
    lines = [f"{title}: {preview.get('title') or ''}"]
    for label, value in (
        (owner, preview.get("assignee_name")),
        (participants, ", ".join(preview.get("assignee_names") or [])),
        (start, preview.get("start_at")), (end, preview.get("deadline_at")),
        (reviewer, preview.get("reviewer_name")), (priority, preview.get("priority")),
        (description, preview.get("description")),
    ):
        if value is not None and value != "":
            lines.append(f"{label}: {value}")
    return "\n".join([*lines, confirm])
