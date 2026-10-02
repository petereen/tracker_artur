"""Small request-scoped language helpers for human-readable API messages."""

from __future__ import annotations

from collections.abc import Mapping
import re

SUPPORTED_LANGUAGES = frozenset({"mn", "ru", "en"})


def normalize_language(value: str | None) -> str | None:
    """Normalize a stored or platform language code to a supported language."""
    if not value:
        return None
    language = value.strip().replace("_", "-").split("-", 1)[0].lower()
    return language if language in SUPPORTED_LANGUAGES else None


def resolve_language(*candidates: str | None, default: str = "mn") -> str:
    """Return the first supported locale, keeping Mongolian as safe fallback."""
    for candidate in candidates:
        normalized = normalize_language(candidate)
        if normalized:
            return normalized
    return normalize_language(default) or "mn"

_ERRORS_EN = {
    "Хандах эрхгүй өгөгдөл.": "You do not have permission to access this data.",
    "Лицензийн хэрэглэгчийн хязгаар дүүрсэн байна. Багцаа өргөтгөнө үү.": "The license user limit has been reached. Upgrade your plan.",
    "Хуучин цалингийн урсгал хаагдсан. Сарын цалингийн самбарыг ашиглана уу.": "The previous payroll workflow is closed. Use the monthly payroll workspace.",
    "Invalid credentials": "The email or password is incorrect.",
    "Account is temporarily locked": "This account is temporarily locked. Please try again later.",
    "Invalid Telegram login": "The Telegram sign-in is invalid.",
    "Telegram user is not registered as an active employee": "This Telegram account is not linked to an active employee.",
    "This Telegram identity is already linked to another employee": "This Telegram account is already linked to another employee.",
    "Employee email is linked to another account": "This employee email is linked to another account.",
    "Organization setup is incomplete": "The organization setup is incomplete.",
    "This account is linked to another Telegram identity": "This account is linked to a different Telegram identity.",
    "Account is disabled": "This account is disabled.",
    "Telegram authentication is not configured": "Telegram sign-in is not configured.",
    "Telegram authentication is temporarily unavailable": "Telegram sign-in is temporarily unavailable.",
    "Notification not found": "Notification not found.",
    "Task not found": "Task not found.",
    "Project not found": "Project not found.",
    "Project code already exists": "A project with this code already exists.",
    "Client auditors have read-only task access": "Client auditors have read-only access to tasks.",
    "Company file search is temporarily unavailable": "Company file search is temporarily unavailable.",
    "HR цалингийн хуучин үүсгэх урсгал хаагдсан. Сарын цалингийн самбарыг ашиглана уу.": "The previous HR payroll creation workflow is closed. Use the monthly payroll workspace.",
    "QR-аар цаг бүртгэх боломжийг админ хаасан байна.": "The administrator has disabled QR attendance.",
    "Telegram бот холбогдоогүй байна.": "The Telegram bot is not connected.",
    "Telegram бот холбогдоогүй байна. Тохиргоо → Интеграци хэсэгт ботоо холбоно уу.": "The Telegram bot is not connected. Connect it under Settings → Integrations.",
    "Админ эрхийг үүргээр олгох боломжгүй; хэрэглэгчид шууд оноогоорой.": "Administrator access cannot be granted through a role; assign it directly to the user.",
    "Ажил эхлүүлэхийн тулд байршлын зөвшөөрөл шаардлагатай.": "Location permission is required to start work.",
    "Байгууллагын эрх идэвхгүй байна. Үйлчилгээ үзүүлэгчтэй холбогдоно уу.": "The organization is inactive. Contact your service provider.",
    "Байршлаар бүртгэх боломжийг хаасан байна. Оффисын QR кодыг уншуулж ажлаа эхлүүлнэ үү.": "Location-based attendance is disabled. Scan the office QR code to start work.",
    "Батлах урсгалд ашиглагдаж байна.": "This role is used in an approval workflow.",
    "Бот холболтын баталгаажуулалт хүлээгээгүй байна.": "No bot connection is waiting for confirmation.",
    "Бусад суутгалын дүн 0-ээс их байх ёстой.": "Other deductions must be greater than zero.",
    "Бүлэг өөрийн дэд бүлэгт харьяалагдаж болохгүй": "A group cannot belong to one of its own subgroups.",
    "Бүр мөсөн устгахаас өмнө ажилтныг архивлана уу.": "Archive the employee before permanently deleting them.",
    "Домэйн олдсонгүй.": "Domain not found.",
    "Зөвхөн баталсан эсвэл төлсөн бодолтыг нээнэ.": "Only an approved or paid payroll run can be reopened.",
    "Зөвхөн батлагдаагүй урьдчилгааны бодолтыг чөлөөлнө.": "Only an unapproved advance run can be released.",
    "Идэвхгүй хэлтэст ажилтан оноох боломжгүй.": "Employees cannot be assigned to an inactive department.",
    "Ийм кодтой хэлтэс бүртгэлтэй байна.": "A department with this code already exists.",
    "Ийм кодтой үүрэг байна.": "A role with this code already exists.",
    "Ийм нэртэй хэлтэс бүртгэлтэй байна.": "A department with this name already exists.",
    "Ийм нэртэй үүрэг байна.": "A role with this name already exists.",
    "Илүү цаг сөрөг байж болохгүй.": "Overtime cannot be negative.",
    "Лицензийн хэрэглэгчийн хязгаар дүүрсэн байна.": "The license user limit has been reached.",
    "Нийтлэгдсэн татварын дүрэм алга.": "No published tax rules were found.",
    "Нэг удаагийн урьдчилгаанд цалингийн профайлтай ажилтныг сонгоно уу.": "Select an employee with a payroll profile for a one-time advance.",
    "Оффисын байршлыг админ тохиргоонд хадгалсны дараа ажил эхлүүлнэ үү.": "Save the office location in administrator settings before starting work.",
    "Регистрын дугаар, имэйл эсвэл Telegram ID давхардаж байна.": "The registration number, email, or Telegram ID is already in use.",
    "Сар аль хэдийн хаагдсан байна.": "This month is already closed.",
    "Системийн загвар үүргийг устгах боломжгүй.": "System role templates cannot be deleted.",
    "Сүүл цалин сөрөг байна.": "Final pay cannot be negative.",
    "Толгой харилцагч нь өөрийн салбар байж болохгүй": "A parent customer cannot be its own branch.",
    "Урьдчилгаа 0-ээс их байх ёстой.": "The advance must be greater than zero.",
    "Хаалтын шалгалтын алдааг засна уу.": "Resolve the closing review errors first.",
    "Цалингийн профайлтай, энэ сард ажилласан ажилтныг сонгоно уу.": "Select an employee with a payroll profile who worked this month.",
    "Чөлөөлөх шалтгаан бичнэ үү.": "Enter a reason for the waiver.",
    "Эдгээр модуль таны лицензэд ороогүй байна.": "These modules are not included in your license.",
    "Энэ Telegram ID өөр ажилтанд холбогдсон байна.": "This Telegram ID is linked to another employee.",
    "Энэ ажилтан ажлын түүх эсвэл нэвтрэх эрхтэй тул бүр мөсөн устгах боломжгүй. Архивт үлдээнэ үү.": "This employee has work history or login access and cannot be permanently deleted. Archive them instead.",
    "Энэ багт үүрэг аль хэдийн оноогдсон.": "This team already has an assigned role.",
    "Энэ имэйл өөр ажилтанд бүртгэлтэй байна.": "This email is already registered to another employee.",
    "Энэ регистрын дугаартай ажилтан бүртгэлтэй байна.": "An employee with this registration number already exists.",
    "Энэ хэлтсээр цалин бодогдсон тул устгах боломжгүй. Идэвхгүй болгоно уу.": "This department has payroll history and cannot be deleted. Deactivate it instead.",
    "Энэ хэрэглэгчид үүрэг аль хэдийн оноогдсон.": "This user already has an assigned role.",
    "Энэ үүрэг хэрэглэгч эсвэл багт оноогдсон байна. Эхлээд хасах эсвэл идэвхгүй болгоно уу.": "This role is assigned to a user or team. Remove the assignment or deactivate the role first.",
    "Эхлээд сарыг шалтгаантайгаар нээнэ үү.": "Reopen the month with a reason first.",
    "Үүрэгт дор хаяж нэг эрх сонгоно уу.": "Select at least one permission for the role.",
    "Өөрийгөө архивлах эсвэл устгах боломжгүй.": "You cannot archive or delete yourself.",
    "Өөрийгөө идэвхгүй болгох боломжгүй.": "You cannot deactivate yourself.",
}

_ERRORS_RU = {
    "Хандах эрхгүй өгөгдөл.": "У вас нет доступа к этим данным.",
    "Лицензийн хэрэглэгчийн хязгаар дүүрсэн байна. Багцаа өргөтгөнө үү.": "Достигнут лимит пользователей по лицензии. Расширьте тариф.",
    "Хуучин цалингийн урсгал хаагдсан. Сарын цалингийн самбарыг ашиглана уу.": "Прежний процесс расчёта зарплаты закрыт. Используйте рабочее пространство месячной зарплаты.",
    "Invalid credentials": "Неверный адрес электронной почты или пароль.",
    "Account is temporarily locked": "Учётная запись временно заблокирована. Попробуйте позже.",
    "Invalid Telegram login": "Недействительный вход через Telegram.",
    "Telegram user is not registered as an active employee": "Этот аккаунт Telegram не связан с активным сотрудником.",
    "This Telegram identity is already linked to another employee": "Этот аккаунт Telegram уже связан с другим сотрудником.",
    "Employee email is linked to another account": "Эта рабочая почта уже связана с другой учётной записью.",
    "Organization setup is incomplete": "Настройка организации не завершена.",
    "This account is linked to another Telegram identity": "Эта учётная запись связана с другим аккаунтом Telegram.",
    "Account is disabled": "Эта учётная запись отключена.",
    "Telegram authentication is not configured": "Вход через Telegram не настроен.",
    "Telegram authentication is temporarily unavailable": "Вход через Telegram временно недоступен.",
    "Notification not found": "Уведомление не найдено.",
    "Task not found": "Задача не найдена.",
    "Project not found": "Проект не найден.",
    "Project code already exists": "Проект с таким кодом уже существует.",
    "Client auditors have read-only task access": "Клиентские аудиторы могут только просматривать задачи.",
    "Company file search is temporarily unavailable": "Поиск по файлам компании временно недоступен.",
    "HR цалингийн хуучин үүсгэх урсгал хаагдсан. Сарын цалингийн самбарыг ашиглана уу.": "Прежний процесс создания зарплаты в HR закрыт. Используйте рабочее пространство месячной зарплаты.",
    "QR-аар цаг бүртгэх боломжийг админ хаасан байна.": "Администратор отключил учёт времени по QR-коду.",
    "Telegram бот холбогдоогүй байна.": "Telegram-бот не подключён.",
    "Telegram бот холбогдоогүй байна. Тохиргоо → Интеграци хэсэгт ботоо холбоно уу.": "Telegram-бот не подключён. Подключите его в разделе «Настройки → Интеграции».",
    "Админ эрхийг үүргээр олгох боломжгүй; хэрэглэгчид шууд оноогоорой.": "Права администратора нельзя выдать через роль; назначьте их пользователю напрямую.",
    "Ажил эхлүүлэхийн тулд байршлын зөвшөөрөл шаардлагатай.": "Чтобы начать работу, необходимо разрешить доступ к местоположению.",
    "Байгууллагын эрх идэвхгүй байна. Үйлчилгээ үзүүлэгчтэй холбогдоно уу.": "Организация неактивна. Обратитесь к поставщику услуги.",
    "Байршлаар бүртгэх боломжийг хаасан байна. Оффисын QR кодыг уншуулж ажлаа эхлүүлнэ үү.": "Учёт по местоположению отключён. Отсканируйте офисный QR-код, чтобы начать работу.",
    "Батлах урсгалд ашиглагдаж байна.": "Роль используется в процессе согласования.",
    "Бот холболтын баталгаажуулалт хүлээгээгүй байна.": "Нет подключения бота, ожидающего подтверждения.",
    "Бусад суутгалын дүн 0-ээс их байх ёстой.": "Сумма прочих удержаний должна быть больше нуля.",
    "Бүлэг өөрийн дэд бүлэгт харьяалагдаж болохгүй": "Группа не может входить в одну из собственных подгрупп.",
    "Бүр мөсөн устгахаас өмнө ажилтныг архивлана уу.": "Архивируйте сотрудника перед окончательным удалением.",
    "Домэйн олдсонгүй.": "Домен не найден.",
    "Зөвхөн баталсан эсвэл төлсөн бодолтыг нээнэ.": "Повторно открыть можно только утверждённый или оплаченный расчёт зарплаты.",
    "Зөвхөн батлагдаагүй урьдчилгааны бодолтыг чөлөөлнө.": "Можно разблокировать только неутверждённый расчёт авансов.",
    "Идэвхгүй хэлтэст ажилтан оноох боломжгүй.": "Нельзя назначить сотрудника в неактивный отдел.",
    "Ийм кодтой хэлтэс бүртгэлтэй байна.": "Отдел с таким кодом уже существует.",
    "Ийм кодтой үүрэг байна.": "Роль с таким кодом уже существует.",
    "Ийм нэртэй хэлтэс бүртгэлтэй байна.": "Отдел с таким названием уже существует.",
    "Ийм нэртэй үүрэг байна.": "Роль с таким названием уже существует.",
    "Илүү цаг сөрөг байж болохгүй.": "Сверхурочные часы не могут быть отрицательными.",
    "Лицензийн хэрэглэгчийн хязгаар дүүрсэн байна.": "Достигнут лимит пользователей по лицензии.",
    "Нийтлэгдсэн татварын дүрэм алга.": "Опубликованные налоговые правила не найдены.",
    "Нэг удаагийн урьдчилгаанд цалингийн профайлтай ажилтныг сонгоно уу.": "Для разового аванса выберите сотрудника с зарплатным профилем.",
    "Оффисын байршлыг админ тохиргоонд хадгалсны дараа ажил эхлүүлнэ үү.": "Сохраните местоположение офиса в настройках администратора, прежде чем начинать работу.",
    "Регистрын дугаар, имэйл эсвэл Telegram ID давхардаж байна.": "Регистрационный номер, адрес электронной почты или Telegram ID уже используются.",
    "Сар аль хэдийн хаагдсан байна.": "Этот месяц уже закрыт.",
    "Системийн загвар үүргийг устгах боломжгүй.": "Системные шаблоны ролей нельзя удалить.",
    "Сүүл цалин сөрөг байна.": "Окончательный расчёт зарплаты не может быть отрицательным.",
    "Толгой харилцагч нь өөрийн салбар байж болохгүй": "Головной клиент не может быть собственным филиалом.",
    "Урьдчилгаа 0-ээс их байх ёстой.": "Аванс должен быть больше нуля.",
    "Хаалтын шалгалтын алдааг засна уу.": "Сначала устраните ошибки проверки закрытия.",
    "Цалингийн профайлтай, энэ сард ажилласан ажилтныг сонгоно уу.": "Выберите сотрудника с зарплатным профилем, который работал в этом месяце.",
    "Чөлөөлөх шалтгаан бичнэ үү.": "Укажите причину освобождения.",
    "Эдгээр модуль таны лицензэд ороогүй байна.": "Эти модули не входят в вашу лицензию.",
    "Энэ Telegram ID өөр ажилтанд холбогдсон байна.": "Этот Telegram ID связан с другим сотрудником.",
    "Энэ ажилтан ажлын түүх эсвэл нэвтрэх эрхтэй тул бүр мөсөн устгах боломжгүй. Архивт үлдээнэ үү.": "У сотрудника есть история работы или доступ к системе, поэтому удалить его окончательно нельзя. Вместо этого архивируйте его.",
    "Энэ багт үүрэг аль хэдийн оноогдсон.": "Этой команде уже назначена роль.",
    "Энэ имэйл өөр ажилтанд бүртгэлтэй байна.": "Этот адрес электронной почты уже зарегистрирован за другим сотрудником.",
    "Энэ регистрын дугаартай ажилтан бүртгэлтэй байна.": "Сотрудник с таким регистрационным номером уже существует.",
    "Энэ хэлтсээр цалин бодогдсон тул устгах боломжгүй. Идэвхгүй болгоно уу.": "Для этого отдела уже рассчитывалась зарплата, поэтому удалить его нельзя. Деактивируйте его.",
    "Энэ хэрэглэгчид үүрэг аль хэдийн оноогдсон.": "Пользователю уже назначена роль.",
    "Энэ үүрэг хэрэглэгч эсвэл багт оноогдсон байна. Эхлээд хасах эсвэл идэвхгүй болгоно уу.": "Эта роль назначена пользователю или команде. Сначала снимите назначение или деактивируйте роль.",
    "Эхлээд сарыг шалтгаантайгаар нээнэ үү.": "Сначала откройте месяц, указав причину.",
    "Үүрэгт дор хаяж нэг эрх сонгоно уу.": "Выберите для роли хотя бы одно разрешение.",
    "Өөрийгөө архивлах эсвэл устгах боломжгүй.": "Нельзя архивировать или удалить себя.",
    "Өөрийгөө идэвхгүй болгох боломжгүй.": "Нельзя деактивировать себя.",
}

# Fixed FastAPI validation and workflow details used by payroll, HR and reports.
# Keep source strings as keys so status codes and machine-readable response
# values remain unchanged while human-readable detail follows Accept-Language.
_ERRORS_EN.update({
    "Excel файл 5 MB-аас бага байх ёстой.": "The Excel file must be smaller than 5 MB.",
    "Ажилтан олдсонгүй": "Employee not found.",
    "Ажилтан олдсонгүй.": "Employee not found.",
    "Алба HR-аас оноогдсон тул зөвхөн HR өөрчилнө": "This department was assigned by HR and can only be changed by HR.",
    "Алба сонгох шаардлагатай": "A department is required.",
    "Баталсан бодолтын дараа Excel экспорт нээгдэнэ.": "Excel export is available after the payroll run is approved.",
    "Баталсан бодолтын мөр засах боломжгүй.": "Rows in an approved payroll run cannot be edited.",
    "Баталсан мөрийг тэмдэглэх боломжгүй.": "An approved row cannot be flagged.",
    "Батлагдсан мөр олдсонгүй.": "Approved row not found.",
    "Бодолтын ажилтан олдсонгүй.": "Payroll employee not found.",
    "Бодолтын батлалтыг эхлээд цуцална уу.": "Revoke the payroll approval first.",
    "Дүрмийн хувилбар олдсонгүй.": "Rule version not found.",
    "Зөвхөн баталсан бодолтыг төлсөн гэж тэмдэглэнэ.": "Only an approved payroll run can be marked as paid.",
    "Зөвхөн ноорог бодолтод Excel оролт оруулна.": "Excel input can only be imported into a draft payroll run.",
    "Зөвхөн ноорог бодолтод HR өөрчлөлт хүлээн авна.": "HR changes can only be accepted in a draft payroll run.",
    "Зөвхөн ноорог бодолтыг батална.": "Only a draft payroll run can be approved.",
    "Зөвхөн ноорог бодолтын ажилтны жагсаалтыг шинэчилнэ.": "The employee list can only be refreshed for a draft payroll run.",
    "Зөвхөн ноорог бодолтын мөрийг тэмдэглэнэ.": "Only a row in a draft payroll run can be flagged.",
    "Зөвхөн ноорог бодолтын мөрийн тэмдэглэгээг арилгана.": "A row flag can only be cleared in a draft payroll run.",
    "Зөвхөн ноорог бодолтын оролтыг буцаах боломжтой.": "Input can only be reverted in a draft payroll run.",
    "Зөвхөн ноорог бодолтын тооцсон дүнг буцаана.": "Calculated amounts can only be reverted in a draft payroll run.",
    "Зөвхөн ноорог бодолтын тооцсон дүнг засна.": "Calculated amounts can only be edited in a draft payroll run.",
    "Зөвхөн ноорог дүрмийг шалгана.": "Only a draft rule set can be validated.",
    "Зөвхөн ноорог сүүл цалингийн бодолтод урьдчилгаа дахин татна.": "Advances can only be recalculated in a draft final-pay run.",
    "Зөвхөн ноорог урьдчилгааны бодолтод ажилтан нэмнэ.": "Employees can only be added to a draft advance run.",
    "Зөвхөн нээлттэй сарын баталсан, төлөөгүй бодолтын батлалтыг цуцална.": "Approval can only be revoked for an approved, unpaid run in an open month.",
    "Зөвхөн нээлттэй сарын төлсөн бодолтыг төлөөгүй болгоно.": "A paid run can only be marked unpaid while its month is open.",
    "Зөвхөн хаагдсан сарыг нээнэ.": "Only a closed month can be reopened.",
    "Идэвхтэй алба сонгоно уу": "Select an active department.",
    "Мөр тэмдэглэгдээгүй байна.": "The row is not flagged.",
    "Нийтлэхийн өмнө дүрмийг шалгана уу.": "Validate the rules before publishing.",
    "Нийтэлсэн дүрмийг засах боломжгүй. Шинэ хувилбар ноороглоно уу.": "Published rules cannot be edited. Create a new draft version.",
    "Ноорог бодолтын мөрийг батална.": "Approve the row in the draft payroll run.",
    "Ноорог бодолтын цагийн мэдээллийг шинэчилнэ.": "Time data can only be refreshed in a draft payroll run.",
    "Ноорог төлөвтэй бодолтыг дахин тооцно.": "Only a draft payroll run can be recalculated.",
    "Сард зөвхөн нэг сүүл цалингийн бодолт үүсгэж болно.": "Only one final-pay run can be created per month.",
    "Сарыг 1-12 хооронд сонгоно уу.": "Choose a month from 1 to 12.",
    "Сарыг YYYY-MM форматаар оруулна уу.": "Enter the month in YYYY-MM format.",
    "Сарын мужийг YYYY-MM форматаар оруулна уу.": "Enter the month range in YYYY-MM format.",
    "Сарын хуанли бодолтод хадгалагдсан тул өөрчлөх боломжгүй.": "The month calendar is saved with the payroll run and cannot be changed.",
    "Сонгосон данс танай байгууллагын идэвхтэй данс биш байна.": "The selected account is not an active account in your organization.",
    "Сонгосон хугацаанд тайлан олдсонгүй": "No report was found for the selected period.",
    "Сүүл цалингийн бодолт сарын бүх ажилтныг нэг хүснэгтэд хамарна; хэлтсээр хүснэгт дотор шүүнэ үү.": "A final-pay run includes all employees for the month in one register. Filter by department within the register.",
    "Таслах өдөр төлбөрийн өдрөөс хойш байж болохгүй.": "The cutoff date cannot be after the payment date.",
    "Тухайн сард хүчинтэй нийтэлсэн цалингийн дүрэм алга.": "There is no published payroll rule set valid for this month.",
    "Тэмдэглэсэн эсвэл баталсан мөрийг батлах боломжгүй.": "A flagged or already approved row cannot be approved.",
    "Төлбөрийн өдөр сонгосон сард багтах ёстой.": "The payment date must fall within the selected month.",
    "Төлбөрийн өдөрт тохирох идэвхтэй ажилтан, цалингийн профайл олдсонгүй.": "No active employee with a payroll profile was found for the payment date.",
    "Төлсөн эсвэл хаасан бодолтыг устгах боломжгүй. Эхлээд «Дахин нээх»-ээр ноорог болгоно уу.": "Paid or closed runs cannot be deleted. Reopen the run as a draft first.",
    "Хаагдсан сарын бодолт өөрчлөх боломжгүй.": "A payroll run in a closed month cannot be edited.",
    "Хаагдсан сарын бодолтыг шинэчлэх боломжгүй.": "A payroll run in a closed month cannot be refreshed.",
    "Хаагдсан сарын бодолтыг өөрчлөх боломжгүй.": "A payroll run in a closed month cannot be changed.",
    "Хэлтэс олдсонгүй": "Department not found.",
    "Хүлээн авах HR өөрчлөлт алга.": "There are no HR changes to accept.",
    "Энэ дүнд засвар бүртгэгдээгүй байна.": "No adjustment has been recorded for this amount.",
    "Энэ төлбөрийн өдөр урьдчилгааны бодолт байна. «Ажилтан нэмэх»-ээр нэмнэ үү.": "An advance run already exists for this payment date. Add the employee there instead.",
    "Эхлэх сар төгсөх сараас хойш байж болохгүй.": "The start month cannot be after the end month.",
})

_ERRORS_RU.update({
    "Excel файл 5 MB-аас бага байх ёстой.": "Размер файла Excel должен быть меньше 5 МБ.",
    "Ажилтан олдсонгүй": "Сотрудник не найден.",
    "Ажилтан олдсонгүй.": "Сотрудник не найден.",
    "Алба HR-аас оноогдсон тул зөвхөн HR өөрчилнө": "Этот отдел назначен HR и может быть изменён только сотрудником HR.",
    "Алба сонгох шаардлагатай": "Необходимо выбрать отдел.",
    "Баталсан бодолтын дараа Excel экспорт нээгдэнэ.": "Экспорт в Excel доступен после утверждения расчёта зарплаты.",
    "Баталсан бодолтын мөр засах боломжгүй.": "Строки утверждённого расчёта зарплаты нельзя редактировать.",
    "Баталсан мөрийг тэмдэглэх боломжгүй.": "Нельзя пометить утверждённую строку.",
    "Батлагдсан мөр олдсонгүй.": "Утверждённая строка не найдена.",
    "Бодолтын ажилтан олдсонгүй.": "Сотрудник в расчёте зарплаты не найден.",
    "Бодолтын батлалтыг эхлээд цуцална уу.": "Сначала отмените утверждение расчёта зарплаты.",
    "Дүрмийн хувилбар олдсонгүй.": "Версия правил не найдена.",
    "Зөвхөн баталсан бодолтыг төлсөн гэж тэмдэглэнэ.": "Только утверждённый расчёт зарплаты можно отметить как оплаченный.",
    "Зөвхөн ноорог бодолтод Excel оролт оруулна.": "Импортировать данные из Excel можно только в черновой расчёт зарплаты.",
    "Зөвхөн ноорог бодолтод HR өөрчлөлт хүлээн авна.": "Изменения HR можно принять только в черновом расчёте зарплаты.",
    "Зөвхөн ноорог бодолтыг батална.": "Утвердить можно только черновой расчёт зарплаты.",
    "Зөвхөн ноорог бодолтын ажилтны жагсаалтыг шинэчилнэ.": "Список сотрудников можно обновить только в черновом расчёте зарплаты.",
    "Зөвхөн ноорог бодолтын мөрийг тэмдэглэнэ.": "Пометить можно только строку чернового расчёта зарплаты.",
    "Зөвхөн ноорог бодолтын мөрийн тэмдэглэгээг арилгана.": "Снять отметку можно только со строки чернового расчёта зарплаты.",
    "Зөвхөн ноорог бодолтын оролтыг буцаах боломжтой.": "Отменить ввод данных можно только в черновом расчёте зарплаты.",
    "Зөвхөн ноорог бодолтын тооцсон дүнг буцаана.": "Отменить рассчитанные суммы можно только в черновом расчёте зарплаты.",
    "Зөвхөн ноорог бодолтын тооцсон дүнг засна.": "Изменить рассчитанные суммы можно только в черновом расчёте зарплаты.",
    "Зөвхөн ноорог дүрмийг шалгана.": "Проверить можно только черновой набор правил.",
    "Зөвхөн ноорог сүүл цалингийн бодолтод урьдчилгаа дахин татна.": "Пересчитать авансы можно только в черновом окончательном расчёте зарплаты.",
    "Зөвхөн ноорог урьдчилгааны бодолтод ажилтан нэмнэ.": "Сотрудников можно добавлять только в черновой расчёт аванса.",
    "Зөвхөн нээлттэй сарын баталсан, төлөөгүй бодолтын батлалтыг цуцална.": "Утверждение можно отменить только для утверждённого неоплаченного расчёта в открытом месяце.",
    "Зөвхөн нээлттэй сарын төлсөн бодолтыг төлөөгүй болгоно.": "Расчёт можно отметить как неоплаченный только в открытом месяце.",
    "Зөвхөн хаагдсан сарыг нээнэ.": "Повторно открыть можно только закрытый месяц.",
    "Идэвхтэй алба сонгоно уу": "Выберите действующий отдел.",
    "Мөр тэмдэглэгдээгүй байна.": "Строка не отмечена.",
    "Нийтлэхийн өмнө дүрмийг шалгана уу.": "Проверьте правила перед публикацией.",
    "Нийтэлсэн дүрмийг засах боломжгүй. Шинэ хувилбар ноороглоно уу.": "Опубликованные правила нельзя редактировать. Создайте новый черновик версии.",
    "Ноорог бодолтын мөрийг батална.": "Утвердите строку чернового расчёта зарплаты.",
    "Ноорог бодолтын цагийн мэдээллийг шинэчилнэ.": "Данные о времени можно обновить только в черновом расчёте зарплаты.",
    "Ноорог төлөвтэй бодолтыг дахин тооцно.": "Пересчитать можно только черновой расчёт зарплаты.",
    "Сард зөвхөн нэг сүүл цалингийн бодолт үүсгэж болно.": "За месяц можно создать только один окончательный расчёт зарплаты.",
    "Сарыг 1-12 хооронд сонгоно уу.": "Выберите месяц от 1 до 12.",
    "Сарыг YYYY-MM форматаар оруулна уу.": "Укажите месяц в формате YYYY-MM.",
    "Сарын мужийг YYYY-MM форматаар оруулна уу.": "Укажите диапазон месяцев в формате YYYY-MM.",
    "Сарын хуанли бодолтод хадгалагдсан тул өөрчлөх боломжгүй.": "Календарь месяца сохранён в расчёте и не может быть изменён.",
    "Сонгосон данс танай байгууллагын идэвхтэй данс биш байна.": "Выбранный счёт не является действующим счётом вашей организации.",
    "Сонгосон хугацаанд тайлан олдсонгүй": "За выбранный период отчёт не найден.",
    "Сүүл цалингийн бодолт сарын бүх ажилтныг нэг хүснэгтэд хамарна; хэлтсээр хүснэгт дотор шүүнэ үү.": "Окончательный расчёт включает всех сотрудников месяца в одном реестре. Фильтруйте реестр по отделу.",
    "Таслах өдөр төлбөрийн өдрөөс хойш байж болохгүй.": "Дата отсечения не может быть позже даты выплаты.",
    "Тухайн сард хүчинтэй нийтэлсэн цалингийн дүрэм алга.": "Нет опубликованного набора правил зарплаты, действующего в этом месяце.",
    "Тэмдэглэсэн эсвэл баталсан мөрийг батлах боломжгүй.": "Нельзя утвердить отмеченную или уже утверждённую строку.",
    "Төлбөрийн өдөр сонгосон сард багтах ёстой.": "Дата выплаты должна приходиться на выбранный месяц.",
    "Төлбөрийн өдөрт тохирох идэвхтэй ажилтан, цалингийн профайл олдсонгүй.": "На дату выплаты не найден действующий сотрудник с профилем зарплаты.",
    "Төлсөн эсвэл хаасан бодолтыг устгах боломжгүй. Эхлээд «Дахин нээх»-ээр ноорог болгоно уу.": "Нельзя удалить оплаченный или закрытый расчёт. Сначала откройте его повторно как черновик.",
    "Хаагдсан сарын бодолт өөрчлөх боломжгүй.": "Нельзя редактировать расчёт за закрытый месяц.",
    "Хаагдсан сарын бодолтыг шинэчлэх боломжгүй.": "Нельзя обновить расчёт за закрытый месяц.",
    "Хаагдсан сарын бодолтыг өөрчлөх боломжгүй.": "Нельзя изменить расчёт за закрытый месяц.",
    "Хэлтэс олдсонгүй": "Отдел не найден.",
    "Хүлээн авах HR өөрчлөлт алга.": "Нет изменений HR для принятия.",
    "Энэ дүнд засвар бүртгэгдээгүй байна.": "Для этой суммы не зарегистрирована корректировка.",
    "Энэ төлбөрийн өдөр урьдчилгааны бодолт байна. «Ажилтан нэмэх»-ээр нэмнэ үү.": "Для этой даты выплаты уже есть расчёт аванса. Добавьте сотрудника в него.",
    "Эхлэх сар төгсөх сараас хойш байж болохгүй.": "Начальный месяц не может быть позже конечного.",
})


def request_language(header: str | None, *, default: str = "mn") -> str:
    """Resolve the first supported language in an Accept-Language header."""
    if not header:
        return default if default in SUPPORTED_LANGUAGES else "mn"
    choices: list[tuple[float, int, str]] = []
    for position, item in enumerate(header.split(",")):
        pieces = item.strip().split(";")
        language = normalize_language(pieces[0])
        if language is None:
            continue
        quality = 1.0
        for parameter in pieces[1:]:
            key, separator, value = parameter.strip().partition("=")
            if separator and key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0:
            choices.append((-quality, position, language))
    return sorted(choices)[0][2] if choices else "mn"


def _translate_text(value: str, language: str, catalog: Mapping[str, str]) -> str:
    exact = catalog.get(value)
    if exact is not None:
        return exact
    patterns = (
        (r"Та оффисоос (.+?)м зайтай байна\. Ажил эхлүүлэхийн тулд (.+?)м дотор очно уу\.",
         lambda m: f"You are {m.group(1)} m from the office. Move within {m.group(2)} m to start work." if language == "en" else f"Вы находитесь в {m.group(1)} м от офиса. Чтобы начать работу, подойдите на расстояние не более {m.group(2)} м."),
        (r"Telegram ID зөвхөн тооноос бүрдэнэ: (.+)",
         lambda m: f"Telegram ID must contain digits only: {m.group(1)}" if language == "en" else f"Telegram ID должен содержать только цифры: {m.group(1)}"),
        (r"Хэлтэст (\d+) ажилтан бүртгэлтэй\. Эхлээд ажилтнуудыг өөр хэлтэс рүү шилжүүлэх, эсвэл хэлтсийг идэвхгүй болгоно уу\.",
         lambda m: f"This department has {m.group(1)} employees. Move them to another department first or deactivate the department." if language == "en" else f"В отделе числятся сотрудники: {m.group(1)}. Сначала переведите их в другой отдел или деактивируйте этот отдел."),
        (r"Тодорхойгүй эрх: (.+)",
         lambda m: f"Unknown permission: {m.group(1)}" if language == "en" else f"Неизвестное разрешение: {m.group(1)}"),
        (r"(.+?): Excel-ийн утга буруу байна\.",
         lambda m: f"{m.group(1)}: The Excel value is invalid." if language == "en" else f"{m.group(1)}: Недопустимое значение Excel."),
        (r"(.+?): шалгах тэмдэглэгээтэй мөрийг эхлээд цэвэрлэнэ үү\.",
         lambda m: f"{m.group(1)}: Clear the flagged row before importing." if language == "en" else f"{m.group(1)}: Перед импортом снимите отметку проверки со строки."),
        (r"Лицензийн хэрэглэгчийн хязгаар \((\d+)\) дүүрсэн байна: (\d+) идэвхтэй хэрэглэгч\. Шинэ хэрэглэгч нэмэхийн тулд багцаа өргөтгөх эсвэл идэвхгүй хэрэглэгчийг хаана уу\.",
         lambda m: f"The license limit of {m.group(1)} users has been reached ({m.group(2)} active users). Upgrade your plan or deactivate an unused account to add another user." if language == "en" else f"Достигнут лимит лицензии: {m.group(1)} пользователей ({m.group(2)} активных). Чтобы добавить пользователя, расширьте тариф или отключите неиспользуемую учётную запись."),
    )
    for pattern, translate in patterns:
        match = re.fullmatch(pattern, value)
        if match:
            return translate(match)
    return value


def translate_detail(detail, language: str):
    """Translate a known human-readable detail while preserving API shape."""
    if language == "mn":
        return detail
    catalog = _ERRORS_EN if language == "en" else _ERRORS_RU if language == "ru" else None
    if catalog is None:
        return detail
    if isinstance(detail, str):
        translated = _translate_text(detail, language, catalog)
        if translated != detail:
            return translated
        # Payroll account-setting validation includes system-owned labels and
        # user-owned account code/name. Translate only the labels and sentence
        # frame; retain the account data verbatim.
        match = re.fullmatch(r"([^:]+): (.*?) · (.*?) данс (.+) ангиллынх байх ёстой\.", detail)
        if match:
            label, code, name, classifications = match.groups()
            labels = {
                "Цалингийн зардлын данс": ("Salary expense account", "Счёт расходов на оплату труда"),
                "Ажил олгогчийн НДШ-ийн зардлын данс": ("Employer social insurance expense account", "Счёт расходов на социальные взносы работодателя"),
                "Урьдчилгааны данс": ("Advance clearing account", "Счёт расчётов по авансам"),
            }
            classes = {
                "Хөрөнгө": ("assets", "активы"),
                "Өр төлбөр": ("liabilities", "обязательства"),
                "Эздийн өмч": ("equity", "собственный капитал"),
                "Орлого": ("income", "доходы"),
                "Зардал": ("expenses", "расходы"),
            }
            translated_label = labels.get(label)
            class_names = [classes.get(value.strip(" «»")) for value in classifications.split(" эсвэл ")]
            if translated_label and all(class_names):
                translated_classes = " or ".join(value[0] for value in class_names) if language == "en" else " или ".join(value[1] for value in class_names)
                if language == "en":
                    return f"{translated_label[0]}: account {code} · {name} must be classified as {translated_classes}."
                return f"{translated_label[1]}: счёт {code} · {name} должен относиться к категории «{translated_classes}»."
        return detail
    if isinstance(detail, Mapping):
        result = dict(detail)
        message = result.get("message")
        if isinstance(message, str):
            result["message"] = _translate_text(message, language, catalog)
        return result
    return detail
