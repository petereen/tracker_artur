"""Automatic geofence worktime: settings, consent text, rules and sweepers.

The phone only reports that it crossed (or is inside/outside) an office
geofence. Everything that decides pay lives here: whether the clock starts or
stops, the exit grace, accuracy and mock-location checks, and the gap
reconciliation. ``decide`` is a pure function so the rules can be tested
without a database.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enterprise_deps import ActorContext
from app.models.models import Employee, Organization, UserAccount, WorkReport, WorkTimeEntry
from app.models.worktime_geo import MobileDevice, WorktimeGeoEvent, WorktimeLocationConsent, WorktimeSite
from app.services.attendance_service import sync_worktime_attendance
from app.services.enterprise_events import record_change
from app.services.user_notifications import create_notifications
from app.services.worktime_geofence import WORKTIME_METHODS_KEY, distance_meters

log = logging.getLogger(__name__)

AUTO_MODES = ("off", "shadow", "on")
DEFAULT_EXIT_GRACE_MINUTES = 10
DEFAULT_MIN_ACCURACY_METERS = 100
DEFAULT_GEO_RETENTION_DAYS = 90
MAX_SITES_PER_DEVICE = 20  # iOS monitors at most 20 regions per app
MAX_EVENT_DELAY = timedelta(hours=6)
MAX_CLOCK_SKEW = timedelta(minutes=2)
SOURCE_CHANNEL = "geofence"
# Phones do not detect smaller areas reliably and register at least this radius.
DEVICE_MIN_RADIUS_METERS = 100

INSIDE_KINDS = frozenset({"enter", "state_inside"})
OUTSIDE_KINDS = frozenset({"exit", "state_outside"})

# ── Disclaimer shown to the employee ───────────────────────────────────────
# Changing any text means a new POLICY_VERSION: earlier acceptances stop being
# valid and every employee is asked again.
POLICY_VERSION = "2026-10-02"
CONSENT_TEXT: dict[str, str] = {
    "mn": (
        "Автомат цаг бүртгэл\n\n"
        "Та зөвшөөрвөл таны утас байгууллагын оффисын бүсэд орох, гарах мөчийг үйлдлийн системийн "
        "геофенс үйлчилгээгээр илрүүлж, ажлын цагийг тань автоматаар эхлүүлж, зогсооно.\n\n"
        "Ямар мэдээлэл боловсруулах вэ:\n"
        "• оффисын бүсэд орсон, гарсан цаг, аль оффис болох;\n"
        "• байршлын нарийвчлал (метрээр) болон хуурамч байршил ашигласан эсэх;\n"
        "• төхөөрөмжийн байршлын зөвшөөрөл, батарей хэмнэлтийн төлөв.\n"
        "Таны газарзүйн координат, явсан зам хадгалагдахгүй. Оффисын бүсээс гадуур таны байршлыг хянахгүй.\n\n"
        "Хэн харах вэ: бүртгэлийн тэмдэглэлийг зөвхөн байгууллагын админ болон хүний нөөцийн ажилтан харна. "
        "Удирдлага зөвхөн үүний үр дүнд үүссэн ажлын цагийн бичлэгийг харна.\n\n"
        "Хадгалах хугацаа: бүртгэлийн тэмдэглэлийг байгууллагын тогтоосон хугацаанд (анхдагчаар 90 хоног) хадгалаад устгана.\n\n"
        "Сайн дурын үндэс: энэ нь заавал биш. Та татгалзсан ч QR код эсвэл гараар цагаа бүртгэж болно, "
        "татгалзсан нь танд ямар нэг сөрөг үр дагавар үүсгэхгүй. Та зөвшөөрлөө Профайл хэсгээс хүссэн үедээ цуцалж болно; "
        "цуцалмагц утас бүсийг хянахаа зогсооно.\n\n"
        "«Зөвшөөрч байна» дээр дарснаар та дээрх нөхцөлөөр байгууллага таны байршлын мэдээллийг "
        "ажлын цаг бүртгэх зорилгоор боловсруулахыг зөвшөөрч байна."
    ),
    "ru": (
        "Автоматический учёт рабочего времени\n\n"
        "С вашего согласия телефон через системную службу геозон определяет момент входа в зону офиса "
        "организации и выхода из неё и автоматически запускает и останавливает учёт рабочего времени.\n\n"
        "Какие данные обрабатываются:\n"
        "• время входа в зону офиса и выхода из неё и какой это офис;\n"
        "• точность определения местоположения (в метрах) и признак подменённого местоположения;\n"
        "• состояние разрешения на геолокацию и режима экономии батареи на устройстве.\n"
        "Ваши географические координаты и маршруты не сохраняются. За пределами зоны офиса ваше местоположение не отслеживается.\n\n"
        "Кто видит данные: журнал событий доступен только администратору организации и сотруднику отдела кадров. "
        "Руководители видят только получившиеся записи рабочего времени.\n\n"
        "Срок хранения: журнал событий хранится в течение срока, установленного организацией (по умолчанию 90 дней), и затем удаляется.\n\n"
        "Добровольность: это не обязательно. При отказе вы можете отмечать время по QR-коду или вручную, "
        "отказ не влечёт для вас никаких неблагоприятных последствий. Согласие можно отозвать в любой момент в разделе «Профиль»; "
        "после отзыва телефон прекращает отслеживать зону.\n\n"
        "Нажимая «Согласен», вы разрешаете организации обрабатывать данные о вашем местоположении "
        "на указанных условиях в целях учёта рабочего времени."
    ),
    "en": (
        "Automatic work time tracking\n\n"
        "With your consent, your phone uses the operating system's geofencing service to detect when you enter "
        "and leave your organization's office area, and starts and stops your work clock automatically.\n\n"
        "What is processed:\n"
        "• the time you entered and left an office area, and which office it was;\n"
        "• the location accuracy (in metres) and whether a mock location was in use;\n"
        "• the state of the location permission and battery saving on your device.\n"
        "Your geographic coordinates and routes are not stored. Your location is not tracked outside the office area.\n\n"
        "Who can see it: the event log is visible only to your organization's administrator and HR staff. "
        "Managers see only the resulting work time entries.\n\n"
        "Retention: the event log is kept for the period set by your organization (90 days by default) and then deleted.\n\n"
        "Voluntary: this is optional. If you decline, you can still clock in by QR code or manually, "
        "and declining has no negative consequence for you. You can withdraw your consent at any time in Profile; "
        "the phone then stops monitoring the area.\n\n"
        "By tapping “I agree” you allow your organization to process your location data "
        "on these terms for the purpose of recording work time."
    ),
}


def consent_text(locale: str | None) -> dict[str, str]:
    language = (locale or "mn").split("-")[0].lower()
    if language not in CONSENT_TEXT:
        language = "mn"
    text = CONSENT_TEXT[language]
    return {"policy_version": POLICY_VERSION, "locale": language, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


# ── Organization settings ─────────────────────────────────────────────────
def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def auto_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Automatic-mode settings stored next to the other worktime methods."""
    value = (settings or {}).get(WORKTIME_METHODS_KEY) or {}
    mode = value.get("auto_geofence_mode")
    ack = value.get("employer_disclaimer_ack")
    return {
        "auto_geofence_mode": mode if mode in AUTO_MODES else "off",
        "exit_grace_minutes": _int(value.get("exit_grace_minutes"), DEFAULT_EXIT_GRACE_MINUTES, 0, 120),
        "min_accuracy_meters": _int(value.get("min_accuracy_meters"), DEFAULT_MIN_ACCURACY_METERS, 10, 1000),
        "geo_retention_days": _int(value.get("geo_retention_days"), DEFAULT_GEO_RETENTION_DAYS, 7, 730),
        "employer_disclaimer_ack": ack if isinstance(ack, dict) else None,
        "policy_version": POLICY_VERSION,
    }


def employer_ack_current(settings: dict[str, Any] | None) -> bool:
    ack = auto_settings(settings)["employer_disclaimer_ack"]
    return bool(ack and ack.get("policy_version") == POLICY_VERSION)


def device_config(settings: dict[str, Any] | None) -> dict[str, Any]:
    """What the native layer needs to know; decisions stay on the server."""
    values = auto_settings(settings)
    return {"mode": values["auto_geofence_mode"], "min_accuracy_meters": values["min_accuracy_meters"]}


def hash_credential(credential: str) -> str:
    return hashlib.sha256(credential.encode()).hexdigest()


# ── Rules (pure) ──────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ActiveEntry:
    entry_type: str  # work | break
    mode: str | None  # in_person | remote | None (break)


@dataclass(frozen=True, slots=True)
class Decision:
    # start | stop | none
    action: str
    result: str
    needs_review: bool = False
    # An arrival voids an exit that is still inside its grace period.
    cancel_pending: bool = False


def within_schedule(start: time | None, end: time | None, local_time: time) -> bool:
    if start is None or end is None:
        return True
    if start <= end:
        return start <= local_time <= end
    return local_time >= start or local_time <= end  # window crossing midnight


def decide(
    *,
    kind: str,
    mode: str,
    occurred_at: datetime,
    received_at: datetime,
    accuracy_meters: float | None,
    is_mock: bool,
    site_known: bool,
    in_schedule: bool,
    active: ActiveEntry | None,
    had_entry_today: bool,
    last_stop_was_auto: bool,
    min_accuracy_meters: int = DEFAULT_MIN_ACCURACY_METERS,
) -> Decision:
    """What one reported transition does to the employee's clock."""
    if mode not in {"shadow", "on"}:
        return Decision("none", "ignored:auto_off")
    if is_mock:
        return Decision("none", "ignored:mock_location", needs_review=True)
    if received_at - occurred_at > MAX_EVENT_DELAY:
        return Decision("none", "ignored:stale", needs_review=True)
    if not site_known:
        return Decision("none", "ignored:unknown_site")
    if accuracy_meters is not None and accuracy_meters > min_accuracy_meters:
        return Decision("none", "ignored:low_accuracy", needs_review=True)

    if kind in INSIDE_KINDS:
        if active is not None:
            if active.entry_type == "work" and active.mode == "remote":
                return Decision("none", "ignored:remote_session")
            reason = "on_break" if active.entry_type == "break" else "already_working"
            return Decision("none", f"ignored:{reason}", cancel_pending=True)
        if not in_schedule:
            return Decision("none", "ignored:outside_schedule")
        # A snapshot only repairs a missed arrival. It never restarts a clock
        # the employee stopped by hand while still in the office.
        if kind == "state_inside" and had_entry_today and not last_stop_was_auto:
            return Decision("none", "ignored:manual_stop")
        return _apply_mode(Decision("start", "started"), mode)

    if kind in OUTSIDE_KINDS:
        if active is None:
            return Decision("none", "ignored:not_working")
        if active.entry_type == "work" and active.mode == "remote":
            return Decision("none", "ignored:remote_session")
        return _apply_mode(Decision("stop", "pending_stop"), mode)

    return Decision("none", "ignored:unknown_kind")


def _apply_mode(decision: Decision, mode: str) -> Decision:
    if mode == "shadow":
        return Decision("none", f"shadow:{decision.action}")
    return decision


# ── Applying a decision ────────────────────────────────────────────────────
@dataclass(slots=True)
class GeoEventInput:
    client_event_id: uuid.UUID
    kind: str
    site_public_id: uuid.UUID | None
    occurred_at: datetime
    accuracy_meters: float | None = None
    is_mock: bool = False
    latitude: float | None = None
    longitude: float | None = None


def _actor(account: UserAccount) -> ActorContext:
    return ActorContext(
        account_id=account.id, organization_id=account.organization_id, employee_id=account.employee_id,
        email=account.email, locale=account.locale or "mn", roles=frozenset(), channel="mobile_geofence",
    )


async def _daily_report(db: AsyncSession, employee: Employee, local_day) -> WorkReport:
    report = await db.scalar(select(WorkReport).where(
        WorkReport.employee_id == employee.id, WorkReport.report_type == "daily",
        WorkReport.period_date == local_day, WorkReport.department_id.is_(None),
    ))
    if not report:
        report = WorkReport(employee_id=employee.id, report_type="daily", period_date=local_day, status="awaiting", title="")
        db.add(report)
        await db.flush()
    return report


async def _active_entry(db: AsyncSession, employee_id: int) -> WorkTimeEntry | None:
    return (await db.execute(
        select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee_id, WorkTimeEntry.ended_at.is_(None))
        .order_by(WorkTimeEntry.started_at.desc(), WorkTimeEntry.id.desc()).with_for_update()
    )).scalars().first()


async def _notify(db: AsyncSession, *, organization_id: int, account_id: int | None, event: WorktimeGeoEvent, started: bool, site_name: str | None) -> None:
    if account_id is None:
        return
    place = f" ({site_name})" if site_name else ""
    await create_notifications(
        db,
        organization_id=organization_id,
        kind="worktime_auto_started" if started else "worktime_auto_stopped",
        title="Ажлын цаг автоматаар эхэллээ" if started else "Ажлын цаг автоматаар зогслоо",
        body=f"Оффисын бүсэд орсон тул ажлын цаг эхэллээ{place}." if started else f"Оффисын бүсээс гарсан тул ажлын цаг зогслоо{place}.",
        dedup_key=f"worktime-auto:{event.id}:{'start' if started else 'stop'}",
        account_ids=[account_id],
        target_url="/worktime",
        payload={"geo_event_id": event.id},
        immediate=True,
        deliver_telegram=False,
    )


async def _finalize_stop(db: AsyncSession, event: WorktimeGeoEvent, *, account: UserAccount | None, employee: Employee | None, site_name: str | None = None) -> None:
    """Close the entry of a pending exit at the time the phone left the area."""
    entry = await db.get(WorkTimeEntry, event.time_entry_id, with_for_update=True) if event.time_entry_id else None
    if entry is None or entry.ended_at is not None:
        event.result = "ignored:already_stopped"
        return
    entry.ended_at = max(event.occurred_at, entry.started_at)
    entry.version += 1
    event.result = "stopped"
    await db.flush()
    if employee is not None:
        await sync_worktime_attendance(db, employee, entry.local_work_date, at=entry.ended_at)
    if account is not None:
        await record_change(
            db, actor=_actor(account), topic="clocks", aggregate_type="time_entry", aggregate_id=entry.id,
            operation="stopped", version=entry.version, channel="mobile_geofence",
            after={"id": entry.id, "ended_at": entry.ended_at, "source": SOURCE_CHANNEL, "geo_event_id": event.id},
        )
    await _notify(db, organization_id=event.organization_id, account_id=event.account_id, event=event, started=False, site_name=site_name)


async def _settle_pending(db: AsyncSession, *, employee: Employee, account: UserAccount, until: datetime, grace: timedelta, cancel: bool) -> None:
    """Resolve this employee's exits still in grace, as of ``until``.

    An exit whose grace ran out before ``until`` stops the clock at the exit
    time. With ``cancel`` (the employee is back) a younger one is voided.
    """
    pending = (await db.execute(
        select(WorktimeGeoEvent).where(WorktimeGeoEvent.employee_id == employee.id, WorktimeGeoEvent.result == "pending_stop")
        .order_by(WorktimeGeoEvent.occurred_at).with_for_update()
    )).scalars().all()
    for event in pending:
        if event.occurred_at + grace <= until:
            await _finalize_stop(db, event, account=account, employee=employee)
        elif cancel:
            event.result = "ignored:returned"
    await db.flush()


async def process_event(
    db: AsyncSession,
    *,
    organization: Organization,
    device: MobileDevice,
    account: UserAccount,
    employee: Employee,
    data: GeoEventInput,
    now: datetime | None = None,
) -> WorktimeGeoEvent:
    """Record one reported transition and apply the rules. Idempotent per
    ``(device, client_event_id)``."""
    now = now or datetime.now(timezone.utc)
    existing = await db.scalar(select(WorktimeGeoEvent).where(
        WorktimeGeoEvent.device_id == device.id, WorktimeGeoEvent.client_event_id == data.client_event_id))
    if existing:
        return existing

    values = auto_settings(organization.settings)
    grace = timedelta(minutes=values["exit_grace_minutes"])
    occurred = data.occurred_at if data.occurred_at.tzinfo else data.occurred_at.replace(tzinfo=timezone.utc)
    skewed = occurred - now > MAX_CLOCK_SKEW
    occurred = min(occurred, now)

    site = None
    if data.site_public_id is not None:
        site = await db.scalar(select(WorktimeSite).where(
            WorktimeSite.public_id == data.site_public_id, WorktimeSite.organization_id == organization.id))
    # Leaving a site that was switched off meanwhile must still stop the clock.
    site_known = site is not None and (site.is_active or data.kind in OUTSIDE_KINDS)

    # Serialize this employee's clock changes.
    await db.execute(select(Employee.id).where(Employee.id == employee.id).with_for_update())
    zone = ZoneInfo(employee.timezone)
    local = occurred.astimezone(zone)
    await _settle_pending(db, employee=employee, account=account, until=occurred, grace=grace, cancel=False)
    active = await _active_entry(db, employee.id)
    last_today = (await db.execute(
        select(WorkTimeEntry).where(WorkTimeEntry.employee_id == employee.id, WorkTimeEntry.local_work_date == local.date())
        .order_by(WorkTimeEntry.started_at.desc(), WorkTimeEntry.id.desc()).limit(1)
    )).scalars().first()
    last_stop_was_auto = bool(last_today and last_today.ended_at and await db.scalar(select(WorktimeGeoEvent.id).where(
        WorktimeGeoEvent.time_entry_id == last_today.id, WorktimeGeoEvent.result == "stopped").limit(1)))

    # A snapshot carries a position: a phone that says "inside" from far away
    # is not believed.
    is_mock = bool(data.is_mock)
    mismatch = False
    if site is not None and data.kind == "state_inside" and data.latitude is not None and data.longitude is not None:
        slack = (data.accuracy_meters or 0) + max(site.radius_meters, DEVICE_MIN_RADIUS_METERS)
        mismatch = distance_meters(data.latitude, data.longitude, site.latitude, site.longitude) > slack

    decision = decide(
        kind=data.kind, mode=values["auto_geofence_mode"], occurred_at=occurred, received_at=now,
        accuracy_meters=data.accuracy_meters, is_mock=is_mock, site_known=site_known,
        in_schedule=within_schedule(site.schedule_start, site.schedule_end, local.time()) if site else True,
        active=ActiveEntry(active.entry_type, active.mode) if active else None,
        had_entry_today=last_today is not None, last_stop_was_auto=last_stop_was_auto,
        min_accuracy_meters=values["min_accuracy_meters"],
    )
    if mismatch and decision.action == "start":
        decision = Decision("none", "ignored:position_mismatch", needs_review=True)

    event = WorktimeGeoEvent(
        organization_id=organization.id, device_id=device.id, account_id=account.id, employee_id=employee.id,
        site_id=site.id if site else None, client_event_id=data.client_event_id, kind=data.kind,
        occurred_at=occurred, received_at=now, accuracy_meters=data.accuracy_meters, is_mock=is_mock,
        result=decision.result, needs_review=decision.needs_review or skewed,
    )
    db.add(event)
    await db.flush()

    if decision.cancel_pending:
        await _settle_pending(db, employee=employee, account=account, until=occurred, grace=grace, cancel=True)

    if decision.action == "start":
        started_at = occurred
        if last_today and last_today.ended_at and last_today.ended_at > started_at:
            started_at = last_today.ended_at  # entries of one day never overlap
        local_day = started_at.astimezone(zone).date()
        report = await _daily_report(db, employee, local_day)
        entry = WorkTimeEntry(
            report_id=report.id, employee_id=employee.id, local_work_date=local_day, timezone=employee.timezone,
            entry_type="work", mode="in_person", started_at=started_at, source_channel=SOURCE_CHANNEL,
            work_location_id=str(site.public_id),
        )
        db.add(entry)
        await db.flush()
        event.time_entry_id = entry.id
        await sync_worktime_attendance(db, employee, local_day, at=started_at)
        await record_change(
            db, actor=_actor(account), topic="clocks", aggregate_type="time_entry", aggregate_id=entry.id,
            operation="started", channel="mobile_geofence",
            after={"id": entry.id, "started_at": started_at, "mode": "in_person", "source": SOURCE_CHANNEL, "geo_event_id": event.id},
        )
        await _notify(db, organization_id=organization.id, account_id=account.id, event=event, started=True, site_name=site.name)
    elif decision.action == "stop":
        event.time_entry_id = active.id
        if grace <= timedelta(0) or occurred + grace <= now:
            await _finalize_stop(db, event, account=account, employee=employee, site_name=site.name if site else None)

    if device.last_event_at is None or occurred > device.last_event_at:
        device.last_event_at = occurred
    if data.kind in {"state_inside", "state_outside"}:
        device.last_state_at = now
    await db.flush()
    return event


# ── Background reconciliation (worker, system context) ────────────────────
async def finalize_pending_exits(db: AsyncSession, now: datetime | None = None) -> int:
    """Stop the clock for exits whose grace period has run out."""
    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(WorktimeGeoEvent, Organization).join(Organization, Organization.id == WorktimeGeoEvent.organization_id)
        .where(WorktimeGeoEvent.result == "pending_stop", WorktimeGeoEvent.occurred_at <= now)
        .order_by(WorktimeGeoEvent.occurred_at).limit(200).with_for_update(of=WorktimeGeoEvent, skip_locked=True)
    )).all()
    done = 0
    for event, organization in rows:
        grace = timedelta(minutes=auto_settings(organization.settings)["exit_grace_minutes"])
        if event.occurred_at + grace > now:
            continue
        account = await db.get(UserAccount, event.account_id) if event.account_id else None
        employee = await db.get(Employee, event.employee_id) if event.employee_id else None
        site = await db.get(WorktimeSite, event.site_id) if event.site_id else None
        await _finalize_stop(db, event, account=account, employee=employee, site_name=site.name if site else None)
        done += 1
    return done


async def close_stale_entries(db: AsyncSession, now: datetime | None = None) -> int:
    """End-of-day sweeper: a clock started by a geofence must not run into the
    next day because the phone never reported the exit. The entry is closed
    at the last moment the phone was known to be inside and flagged for review."""
    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(WorkTimeEntry, Employee).join(Employee, Employee.id == WorkTimeEntry.employee_id)
        .where(WorkTimeEntry.source_channel == SOURCE_CHANNEL, WorkTimeEntry.ended_at.is_(None),
               WorkTimeEntry.started_at < now - timedelta(hours=1))
        .limit(200).with_for_update(of=WorkTimeEntry, skip_locked=True)
    )).all()
    closed = 0
    for entry, employee in rows:
        zone = ZoneInfo(employee.timezone)
        if entry.local_work_date >= now.astimezone(zone).date():
            continue
        day_end = datetime.combine(entry.local_work_date, time(23, 59, 59), tzinfo=zone).astimezone(timezone.utc)
        evidence = await db.scalar(
            select(WorktimeGeoEvent.occurred_at).where(
                WorktimeGeoEvent.employee_id == employee.id, WorktimeGeoEvent.kind.in_(tuple(INSIDE_KINDS)),
                WorktimeGeoEvent.occurred_at >= entry.started_at, WorktimeGeoEvent.occurred_at <= day_end,
            ).order_by(WorktimeGeoEvent.occurred_at.desc()).limit(1))
        entry.ended_at = max(entry.started_at, min(evidence or entry.started_at, day_end))
        entry.version += 1
        account_id = await db.scalar(select(UserAccount.id).where(UserAccount.employee_id == employee.id).limit(1))
        db.add(WorktimeGeoEvent(
            organization_id=employee.organization_id, account_id=account_id, employee_id=employee.id,
            client_event_id=uuid.uuid4(), kind="sweep", occurred_at=entry.ended_at, received_at=now,
            result="stopped", needs_review=True, time_entry_id=entry.id,
        ))
        await db.flush()
        await sync_worktime_attendance(db, employee, entry.local_work_date, at=entry.ended_at)
        closed += 1
    return closed


async def purge_geo_events(db: AsyncSession, now: datetime | None = None) -> None:
    """Delete location events older than each organization's retention."""
    now = now or datetime.now(timezone.utc)
    organization_ids = (await db.execute(select(WorktimeGeoEvent.organization_id).distinct())).scalars().all()
    for organization_id in organization_ids:
        organization = await db.get(Organization, organization_id)
        days = auto_settings(organization.settings if organization else None)["geo_retention_days"]
        await db.execute(delete(WorktimeGeoEvent).where(
            WorktimeGeoEvent.organization_id == organization_id,
            WorktimeGeoEvent.received_at < now - timedelta(days=days),
            WorktimeGeoEvent.result != "pending_stop",
        ))


# ── Consent and devices ────────────────────────────────────────────────────
async def current_consent(db: AsyncSession, account_id: int) -> WorktimeLocationConsent | None:
    """The account's valid acceptance of the current disclaimer, if any."""
    consent = (await db.execute(
        select(WorktimeLocationConsent).where(WorktimeLocationConsent.account_id == account_id)
        .order_by(WorktimeLocationConsent.accepted_at.desc(), WorktimeLocationConsent.id.desc()).limit(1)
    )).scalars().first()
    if consent is None or consent.revoked_at is not None or consent.policy_version != POLICY_VERSION:
        return None
    return consent


async def revoke_devices(db: AsyncSession, devices: Iterable[MobileDevice], now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    for device in devices:
        if device.revoked_at is None:
            device.revoked_at = now
            device.geofence_enabled = False


async def active_sites(db: AsyncSession, organization_id: int) -> list[WorktimeSite]:
    return list((await db.execute(
        select(WorktimeSite).where(WorktimeSite.organization_id == organization_id, WorktimeSite.is_active.is_(True))
        .order_by(WorktimeSite.id).limit(MAX_SITES_PER_DEVICE)
    )).scalars().all())


def site_out(site: WorktimeSite) -> dict[str, Any]:
    return {
        "id": str(site.public_id), "name": site.name, "latitude": site.latitude, "longitude": site.longitude,
        "radius_meters": site.radius_meters, "is_active": site.is_active,
        "schedule_start": site.schedule_start.strftime("%H:%M") if site.schedule_start else None,
        "schedule_end": site.schedule_end.strftime("%H:%M") if site.schedule_end else None,
    }


async def upsert_primary_site(db: AsyncSession, organization_id: int, latitude: float, longitude: float, radius_meters: int) -> WorktimeSite:
    """Facade for the legacy single-geofence endpoint: it edits the first site."""
    site = await db.scalar(select(WorktimeSite).where(
        WorktimeSite.organization_id == organization_id, WorktimeSite.is_active.is_(True)).order_by(WorktimeSite.id).limit(1))
    if site is None:
        site = WorktimeSite(organization_id=organization_id, name="Төв оффис", latitude=latitude, longitude=longitude, radius_meters=radius_meters)
        db.add(site)
    else:
        site.latitude, site.longitude, site.radius_meters = latitude, longitude, radius_meters
    await db.flush()
    return site


async def site_containing(db: AsyncSession, organization_id: int, latitude: float | None, longitude: float | None) -> WorktimeSite | None:
    """The active site this position is inside, if any (manual office start)."""
    if latitude is None or longitude is None:
        return None
    for site in await active_sites(db, organization_id):
        if distance_meters(latitude, longitude, site.latitude, site.longitude) <= site.radius_meters:
            return site
    return None
