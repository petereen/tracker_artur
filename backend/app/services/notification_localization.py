"""Recipient-language copy for newly generated system notifications."""

from __future__ import annotations

from app.core.localization import resolve_language

# Generic system-owned copy. User-authored names, titles, descriptions, and
# historical notification text stay in the JSON template parameters unchanged.
_COPY = {
    "task_assigned": {
        "mn": ("Шинэ даалгавар оноолоо", "Танд шинэ даалгавар оноогдлоо."),
        "ru": ("Назначена новая задача", "Вам назначена новая задача."),
        "en": ("New task assigned", "A new task has been assigned to you."),
    },
    "task_review_requested": {
        "mn": ("Даалгавар хянах шаардлагатай", "Хянах шаардлагатай даалгавар байна."),
        "ru": ("Задача ожидает проверки", "Есть задача, ожидающая вашей проверки."),
        "en": ("Task ready for review", "A task is waiting for your review."),
    },
    "task_collaboration_updated": {
        "mn": ("Даалгаврын оролцогч шинэчлэгдлээ", "Хамтран ажиллах даалгаврын мэдээлэл шинэчлэгдлээ."),
        "ru": ("Изменились участники задачи", "Обновлена информация о совместной работе над задачей."),
        "en": ("Task collaboration updated", "The task collaboration details have been updated."),
    },
    "task_overdue": {
        "mn": ("Даалгаврын хугацаа хэтэрлээ", "Даалгаврын хугацаа хэтэрсэн байна."),
        "ru": ("Срок задачи истёк", "Срок выполнения задачи истёк."),
        "en": ("Task overdue", "A task has passed its deadline."),
    },
    "task_deadline": {
        "mn": ("Даалгаврын сануулга", "Даалгаврын хугацаа ойртож байна."),
        "ru": ("Напоминание о задаче", "Приближается срок выполнения задачи."),
        "en": ("Task deadline reminder", "A task deadline is approaching."),
    },
    "contract_submitted": {
        "mn": ("Шинэ гэрээ хянахаар ирлээ", "Шинэ гэрээ эсвэл баримт бичиг хянуулах хүсэлт ирлээ."),
        "ru": ("Новый договор на проверку", "Поступил новый договор или документ на проверку."),
        "en": ("New contract for review", "A new contract or document has been submitted for review."),
    },
    "contract_changes_requested": {
        "mn": ("Гэрээнд засвар шаардлагатай", "Гэрээний засварын санал ирлээ."),
        "ru": ("Запрошены изменения в договоре", "Поступили замечания и предложения по договору."),
        "en": ("Contract changes requested", "A reviewer has requested changes to the contract."),
    },
    "contract_rejected": {
        "mn": ("Баримт буцаагдлаа", "Илгээсэн баримтыг буцаалаа."),
        "ru": ("Документ возвращён", "Отправленный документ был возвращён."),
        "en": ("Document returned", "The submitted document was returned."),
    },
    "contract_approved": {
        "mn": ("Гэрээ батлагдлаа", "Гэрээ батлагдлаа. Баримтыг хэвлэж, гарын үсэг зурж баталгаажуулна уу."),
        "ru": ("Договор утверждён", "Договор утверждён. Распечатайте документ, подпишите и заверьте его."),
        "en": ("Contract approved", "The contract is approved. Print, sign, and certify the document."),
    },
    "contract_signed": {
        "mn": ("Гэрээ архивлагдлаа", "Гарын үсэг, тамгатай гэрээг архивлалаа."),
        "ru": ("Договор помещён в архив", "Договор с подписями и печатями помещён в архив."),
        "en": ("Contract archived", "The signed and stamped contract has been archived."),
    },
    "contract_archive_review": {
        "mn": ("Архивын хяналт шаардлагатай", "Гарын үсэг зурсан гэрээг архивын хяналтад илгээлээ."),
        "ru": ("Требуется проверка архива", "Подписанный договор отправлен на проверку архива."),
        "en": ("Archive review required", "A signed contract has been submitted for archive review."),
    },
    "report_submitted": {
        "mn": ("Шинэ тайлан хянахаар ирлээ", "Ажилтан тайлангаа хянуулахаар илгээлээ."),
        "ru": ("Новый отчёт на проверку", "Сотрудник отправил отчёт на проверку."),
        "en": ("New report for review", "An employee submitted a report for review."),
    },
    "hr_leave_requested": {
        "mn": ("Чөлөөний хүсэлт ирлээ", "Ажилтан чөлөө хүссэн байна."),
        "ru": ("Новая заявка на отпуск", "Сотрудник подал заявку на отпуск."),
        "en": ("New leave request", "An employee has requested leave."),
    },
    "hr_leave_cancelled": {
        "mn": ("Чөлөөний хүсэлт цуцлагдлаа", "Ажилтан чөлөөний хүсэлтээ цуцаллаа."),
        "ru": ("Заявка на отпуск отменена", "Сотрудник отменил заявку на отпуск."),
        "en": ("Leave request cancelled", "An employee cancelled a leave request."),
    },
    "project_member_added": {
        "mn": ("Төсөлд нэмэгдлээ", "Таныг төсөлд оролцогчоор нэмлээ."),
        "ru": ("Вы добавлены в проект", "Вас добавили в участники проекта."),
        "en": ("Added to project", "You have been added as a project member."),
    },
    "project_request_reviewed": {
        "mn": ("Төслийн хүсэлт шинэчлэгдлээ", "Төслийн хүсэлтийг хянаж шийдвэрлэлээ."),
        "ru": ("Обновлён запрос проекта", "Запрос проекта рассмотрен."),
        "en": ("Project request updated", "The project request has been reviewed."),
    },
    "crm_activity_assigned": {
        "mn": ("Харилцагчийн ажил оноолоо", "Танд харилцагчтай холбоотой ажил оноолоо."),
        "ru": ("Назначена задача по клиенту", "Вам назначена задача, связанная с клиентом."),
        "en": ("Customer activity assigned", "A customer-related activity has been assigned to you."),
    },
    "crm_activity_due": {
        "mn": ("Харилцагчийн ажлын хугацаа дөхлөө", "Харилцагчтай холбоотой ажлын хугацаа удахгүй дуусна."),
        "ru": ("Приближается срок работы с клиентом", "Скоро истекает срок выполнения задачи по клиенту."),
        "en": ("Customer activity due soon", "A customer-related activity is due soon."),
    },
    "crm_activity_overdue": {
        "mn": ("Харилцагчийн ажил хугацаа хэтэрлээ", "Харилцагчтай холбоотой ажлын хугацаа өнгөрсөн байна."),
        "ru": ("Просрочена работа с клиентом", "Срок выполнения задачи по клиенту истёк."),
        "en": ("Customer activity overdue", "A customer-related activity is overdue."),
    },
    "crm_activity_escalated": {
        "mn": ("Харилцагчийн хоцорсон ажил", "Харилцагчтай холбоотой ажил ажлын өдрөөр хоцорсон байна."),
        "ru": ("Просроченная работа с клиентом", "Задача по клиенту просрочена на несколько рабочих дней."),
        "en": ("Overdue customer activity", "A customer-related activity is several business days overdue."),
    },
    "calendar_reminder": {
        "mn": ("Календарийн сануулга", "Календарийн үйл явдал удахгүй эхэлнэ."),
        "ru": ("Напоминание календаря", "Скоро начнётся событие в календаре."),
        "en": ("Calendar reminder", "A calendar event is starting soon."),
    },
    "company_plan_created": {
        "mn": ("Шинэ компанийн төлөвлөгөө", "Компанийн шинэ төлөвлөгөө нэмэгдлээ."),
        "ru": ("Новый план компании", "Добавлен новый план компании."),
        "en": ("New company plan", "A new company plan has been added."),
    },
    "project_deadline": {
        "mn": ("Төслийн хугацааны сануулга", "Төслийн хугацаа дуусах гэж байна."),
        "ru": ("Напоминание о сроке проекта", "Приближается срок завершения проекта."),
        "en": ("Project deadline reminder", "A project deadline is approaching."),
    },
    "contract_expiry_reminder": {
        "mn": ("Гэрээний хугацаа дуусах гэж байна", "Гэрээний хугацаа удахгүй дуусна."),
        "ru": ("Скоро истекает срок договора", "Срок действия договора скоро истекает."),
        "en": ("Contract expiry reminder", "A contract is nearing its expiry date."),
    },
    "contract_expired": {
        "mn": ("Гэрээний хугацаа дууслаа", "Гэрээний хугацаа өнөөдөр дууслаа."),
        "ru": ("Срок договора истёк", "Срок действия договора истёк сегодня."),
        "en": ("Contract expired", "A contract expires today."),
    },
    "daily_report": {
        "mn": ("Өдрийн тайлан", "Өнөөдрийн ажлын тайлангаа илгээнэ үү."),
        "ru": ("Ежедневный отчёт", "Отправьте отчёт о работе за сегодня."),
        "en": ("Daily report", "Please submit your work report for today."),
    },
    "daily_checkin": {
        "mn": ("Өдрийн check-in", "Өнөөдрийн check-in болон өдрийн тайлангаа бөглөнө үү."),
        "ru": ("Ежедневный опрос", "Пройдите ежедневный опрос и отправьте отчёт о работе."),
        "en": ("Daily check-in", "Complete today's check-in and submit your work report."),
    },
    "daily_reminder": {
        "mn": ("Өдрийн сануулга", "Өдрийн check-in эсвэл ажлын тайлангаа бөглөнө үү."),
        "ru": ("Ежедневное напоминание", "Заполните ежедневный опрос или отправьте отчёт о работе."),
        "en": ("Daily reminder", "Please complete your daily check-in or submit your work report."),
    },
    "worktime_reminder": {
        "mn": ("Ажлын цагийн сануулга", "Ажлын цагаа эхлүүлэх эсвэл дуусгахаа мартсан эсэхээ шалгана уу."),
        "ru": ("Напоминание о рабочем времени", "Проверьте, не забыли ли вы начать или завершить учёт рабочего времени."),
        "en": ("Work time reminder", "Check whether you need to start or end your work time."),
    },
    "birthday": {
        "mn": ("Төрсөн өдрийн мэндчилгээ", "Танд төрсөн өдрийн мэнд хүргэе! Эрүүл энх, аз жаргал, амжилт хүсье!"),
        "ru": ("Поздравление с днём рождения", "С днём рождения! Желаем здоровья, счастья и успехов!"),
        "en": ("Happy birthday", "Wishing you a wonderful birthday, good health, happiness, and success!"),
    },
    "hr_leave_rejected": {
        "mn": ("Чөлөөний хүсэлт татгалзагдлаа", "Таны чөлөөний хүсэлтийг татгалзлаа."),
        "ru": ("Заявка на отпуск отклонена", "Ваша заявка на отпуск отклонена."),
        "en": ("Leave request rejected", "Your leave request was rejected."),
    },
    "hr_leave_updated": {
        "mn": ("Чөлөөний хүсэлт шинэчлэгдлээ", "Таны чөлөөний хүсэлтийн мэдээлэл шинэчлэгдлээ."),
        "ru": ("Заявка на отпуск обновлена", "Информация о вашей заявке на отпуск обновлена."),
        "en": ("Leave request updated", "Your leave request has been updated."),
    },
    "hr_leave_approved": {
        "mn": ("Чөлөөний хүсэлт батлагдлаа", "Таны чөлөөний хүсэлт батлагдлаа."),
        "ru": ("Заявка на отпуск одобрена", "Ваша заявка на отпуск одобрена."),
        "en": ("Leave request approved", "Your leave request has been approved."),
    },
    "monthly_report": {
        "mn": ("Сарын тайлан", "Сарын тайлангаа илгээнэ үү."),
        "ru": ("Ежемесячный отчёт", "Отправьте ежемесячный отчёт."),
        "en": ("Monthly report", "Please submit your monthly report."),
    },
    "periodic_report": {
        "mn": ("Хугацаат тайлан", "Тайлангаа заасан хугацаанд илгээнэ үү."),
        "ru": ("Периодический отчёт", "Отправьте отчёт за указанный период."),
        "en": ("Periodic report", "Please submit your report for the selected period."),
    },
}


def notification_copy(kind: str, title: str, body: str, language: str | None) -> tuple[str, str]:
    """Use translated system copy when known; preserve original copy otherwise."""
    locale = resolve_language(language)
    message = _COPY.get(kind, {}).get(locale)
    return message if message else (title, body)


def render_notification_payload(kind: str, payload: dict, language: str | None) -> tuple[str, str]:
    """Resolve a newly stored template payload into recipient-language copy."""
    params = payload.get("template_params") or {}
    title = params.get("source_title", payload.get("title") or "Мэдэгдэл")
    body = params.get("source_body", payload.get("body") or "")
    return notification_copy(kind, str(title), str(body), language)
