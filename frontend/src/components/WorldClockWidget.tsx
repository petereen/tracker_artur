import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  ChevronDown,
  ChevronUp,
  Clock3,
  GripVertical,
  Plus,
  Search,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import {
  useUpdateWorldClockPreferences,
  useWorldClockPreferences,
  type WorldClockPreferences,
} from "../api/enterprise";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

const DEFAULT_PREFERENCES: WorldClockPreferences = {
  clocks: ["Asia/Ulaanbaatar"],
  display_mode: "digital",
  hour_format: "24",
};

const FALLBACK_TIMEZONES = [
  "Pacific/Honolulu",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Atlantic/Reykjavik",
  "Europe/London",
  "Europe/Paris",
  "Europe/Moscow",
  "Africa/Cairo",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Bangkok",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

const clonePreferences = (value: WorldClockPreferences): WorldClockPreferences => ({
  clocks: [...value.clocks],
  display_mode: value.display_mode,
  hour_format: value.hour_format,
});

function supportedTimezones() {
  const intl = Intl as typeof Intl & {
    supportedValuesOf?: (key: string) => string[];
  };
  const values = intl.supportedValuesOf?.("timeZone");
  return values?.length ? values : FALLBACK_TIMEZONES;
}

function timezoneLabel(timezone: string) {
  const pieces = timezone.split("/");
  const city = pieces[pieces.length - 1] || timezone;
  return city.replace(/_/g, " ");
}

function getTimeParts(timezone: string, date: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value || 0);
  return { hour: get("hour"), minute: get("minute"), second: get("second") };
}

function dateKey(timezone: string, date: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "00";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function timezoneOffsetMinutes(timezone: string, date: Date) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value || 0);
  const renderedAsUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((renderedAsUtc - date.getTime()) / 60000);
}

function formatOffset(minutes: number) {
  const sign = minutes < 0 ? "−" : "+";
  const absolute = Math.abs(minutes);
  const hours = Math.floor(absolute / 60);
  const remaining = absolute % 60;
  return `${sign}${hours}${remaining ? `:${String(remaining).padStart(2, "0")}` : ""} HRS`;
}

function dayDifference(fromTimezone: string, toTimezone: string, date: Date) {
  const from = dateKey(fromTimezone, date).split("-").map(Number);
  const to = dateKey(toTimezone, date).split("-").map(Number);
  return Math.round((Date.UTC(to[0], to[1] - 1, to[2]) - Date.UTC(from[0], from[1] - 1, from[2])) / 86400000);
}

function relativeDayLabel(delta: number) {
  if (delta === 0) return "Today";
  if (delta === 1) return "Tomorrow";
  if (delta === -1) return "Yesterday";
  return delta > 0 ? `In ${delta} days` : `${Math.abs(delta)} days ago`;
}

function DigitalClock({ timezone, hourFormat, now, localTimezone }: { timezone: string; hourFormat: "12" | "24"; now: Date; localTimezone: string }) {
  const parts = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
    hour12: hourFormat === "12",
  }).formatToParts(now);
  const part = (type: string) => parts.find((item) => item.type === type)?.value || "";
  const hour = part("hour");
  const minute = part("minute").padStart(2, "0");
  const dayPeriod = part("dayPeriod");
  const offset = timezoneOffsetMinutes(timezone, now) - timezoneOffsetMinutes(localTimezone, now);
  const day = relativeDayLabel(dayDifference(localTimezone, timezone, now));
  return (
    <div className="world-clock-digital-time" aria-label={`${timezoneLabel(timezone)} ${hour}:${minute}${dayPeriod ? ` ${dayPeriod}` : ""}, ${day}, ${formatOffset(offset)}`}>
      <div className="world-clock-digital-number"><strong>{hour}:{minute}</strong>{dayPeriod && <span className="world-clock-period">{dayPeriod}</span>}</div>
      <div className="world-clock-tile-meta"><strong>{formatOffset(offset)}</strong><span>{day}</span></div>
    </div>
  );
}

function AnalogClock({ timezone, hourFormat, now, localTimezone }: { timezone: string; hourFormat: "12" | "24"; now: Date; localTimezone: string }) {
  const initialSecond = useRef((Date.now() % 60000) / 1000);
  const time = getTimeParts(timezone, now);
  const hourAngle = ((time.hour % 12) + time.minute / 60) * 30;
  const minuteAngle = (time.minute + time.second / 60) * 6;
  const offset = timezoneOffsetMinutes(timezone, now) - timezoneOffsetMinutes(localTimezone, now);
  const day = relativeDayLabel(dayDifference(localTimezone, timezone, now));
  const label = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: hourFormat === "12",
  }).format(now);
  return (
    <div className="world-clock-analog-wrap">
      <div
        className="world-clock-face"
        aria-label={`${timezoneLabel(timezone)} ${label}, ${day}, ${formatOffset(offset)}`}
        style={{ "--world-hour": `${hourAngle}deg`, "--world-minute": `${minuteAngle}deg`, "--world-second": `${initialSecond.current * 6}deg`, "--world-second-delay": `-${initialSecond.current}s` } as CSSProperties}
      >
        <span className="world-clock-tick tick-12" /><span className="world-clock-tick tick-3" /><span className="world-clock-tick tick-6" /><span className="world-clock-tick tick-9" />
        <i className="world-clock-hand hour" /><i className="world-clock-hand minute" /><i className="world-clock-hand second" />
        <b />
      </div>
      <strong>{timezoneLabel(timezone)}</strong>
      <small>{day} · {formatOffset(offset)}</small>
    </div>
  );
}

function SortableClockRow({ timezone, index, total, onMove, onEdit, onRemove }: { timezone: string; index: number; total: number; onMove: (from: number, to: number) => void; onEdit: () => void; onRemove: () => void }) {
  const sortable = useSortable({ id: timezone });
  const style = { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition };
  return (
    <li ref={sortable.setNodeRef} style={style} className="world-clock-setting-row">
      <button type="button" className="world-clock-drag" ref={sortable.setActivatorNodeRef} {...sortable.listeners} {...sortable.attributes} aria-label={`${timezoneLabel(timezone)}-г шилжүүлэх`}><GripVertical size={15} /></button>
      <span><strong>{timezoneLabel(timezone)}</strong><small>{timezone}</small></span>
      <div>
        <button type="button" onClick={() => onMove(index, index - 1)} disabled={index === 0} aria-label="Дээш зөөх"><ChevronUp size={15} /></button>
        <button type="button" onClick={() => onMove(index, index + 1)} disabled={index === total - 1} aria-label="Доош зөөх"><ChevronDown size={15} /></button>
        <button type="button" onClick={onEdit} aria-label={`${timezoneLabel(timezone)} засах`}><Settings2 size={15} /></button>
        <button type="button" onClick={onRemove} aria-label={`${timezoneLabel(timezone)} устгах`}><Trash2 size={15} /></button>
      </div>
    </li>
  );
}

function WorldClockEditor({ draft, onChange, onClose, onSave, saving }: { draft: WorldClockPreferences; onChange: (value: WorldClockPreferences) => void; onClose: () => void; onSave: () => void; saving: boolean }) {
  const [query, setQuery] = useState("");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const timezones = useMemo(() => supportedTimezones(), []);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return timezones.filter((timezone) => {
      if (draft.clocks.includes(timezone) && editingIndex === null) return false;
      if (!needle) return true;
      return `${timezone} ${timezoneLabel(timezone)}`.toLowerCase().includes(needle);
    }).slice(0, 10);
  }, [draft.clocks, editingIndex, query, timezones]);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const chooseTimezone = (timezone: string) => {
    const clocks = [...draft.clocks];
    if (editingIndex === null) clocks.push(timezone);
    else clocks[editingIndex] = timezone;
    onChange({ ...draft, clocks: [...new Set(clocks)] });
    setEditingIndex(null);
    setQuery("");
    setSearchOpen(false);
  };
  const move = (from: number, to: number) => {
    if (to < 0 || to >= draft.clocks.length) return;
    onChange({ ...draft, clocks: arrayMove(draft.clocks, from, to) });
  };
  const dragEnd = (event: DragEndEvent) => {
    if (!event.over || event.active.id === event.over.id) return;
    const from = draft.clocks.indexOf(String(event.active.id));
    const to = draft.clocks.indexOf(String(event.over.id));
    if (from >= 0 && to >= 0) move(from, to);
  };
  useEffect(() => { panelRef.current?.querySelector<HTMLElement>("input")?.focus(); }, []);
  return (
    <section ref={panelRef} className="world-clock-settings" role="dialog" aria-modal="true" aria-labelledby="world-clock-settings-title" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span className="eyebrow">World clock</span><h3 id="world-clock-settings-title">Цагийн тохиргоо</h3></div><button type="button" onClick={onClose} aria-label="Хаах"><X size={17} /></button></header>
      <div className="world-clock-setting-toggles">
        <fieldset><legend>Дэлгэц</legend><button type="button" className={draft.display_mode === "digital" ? "active" : ""} onClick={() => onChange({ ...draft, display_mode: "digital" })}>Digital</button><button type="button" className={draft.display_mode === "analog" ? "active" : ""} onClick={() => onChange({ ...draft, display_mode: "analog" })}>Analog</button></fieldset>
        <fieldset><legend>Формат</legend><button type="button" className={draft.hour_format === "24" ? "active" : ""} onClick={() => onChange({ ...draft, hour_format: "24" })}>24h</button><button type="button" className={draft.hour_format === "12" ? "active" : ""} onClick={() => onChange({ ...draft, hour_format: "12" })}>12h</button></fieldset>
      </div>
      <div className="world-clock-setting-search"><Search size={15} /><input value={query} onFocus={() => setSearchOpen(true)} onChange={(event) => { setQuery(event.target.value); setSearchOpen(true); }} placeholder={editingIndex === null ? "Search time zones" : "Replace time zone"} aria-label="Цагийн бүс хайх" />{query && <button type="button" onClick={() => setQuery("")} aria-label="Хайлтыг цэвэрлэх"><X size={14} /></button>}</div>
      {searchOpen && <div className="world-clock-zone-results" role="listbox">{filtered.map((timezone) => <button type="button" key={timezone} onClick={() => chooseTimezone(timezone)} role="option"><strong>{timezoneLabel(timezone)}</strong><small>{timezone}</small></button>)}{filtered.length === 0 && <p>Цагийн бүс олдсонгүй.</p>}</div>}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dragEnd}><SortableContext items={draft.clocks} strategy={verticalListSortingStrategy}><ul className="world-clock-setting-list">{draft.clocks.map((timezone, index) => <SortableClockRow key={timezone} timezone={timezone} index={index} total={draft.clocks.length} onMove={move} onEdit={() => { setEditingIndex(index); setQuery(""); setSearchOpen(true); }} onRemove={() => onChange({ ...draft, clocks: draft.clocks.filter((item) => item !== timezone) })} />)}</ul></SortableContext></DndContext>
      {draft.clocks.length < 6 && <button type="button" className="world-clock-add" onClick={() => { setEditingIndex(null); setQuery(""); setSearchOpen(true); panelRef.current?.querySelector<HTMLInputElement>("input")?.focus(); }}><Plus size={15} />Цаг нэмэх</button>}
      {draft.clocks.length === 6 && <p className="world-clock-limit">Хамгийн ихдээ 6 цаг нэмэх боломжтой.</p>}
      <footer><button type="button" className="secondary-action compact" onClick={onClose}>Цуцлах</button><button type="button" className="primary-action compact" onClick={onSave} disabled={saving}>{saving ? "Хадгалж байна…" : "Хадгалах"}</button></footer>
    </section>
  );
}

export function WorldClockWidget() {
  const preferences = useWorldClockPreferences();
  const update = useUpdateWorldClockPreferences();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<WorldClockPreferences | null>(null);
  const [now, setNow] = useState(() => new Date());
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const saved = preferences.data || DEFAULT_PREFERENCES;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => { if (preferences.data && !open) setDraft(clonePreferences(preferences.data)); }, [open, preferences.data]);
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    const outside = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target?.closest(".world-clock-settings") && target !== triggerRef.current) setOpen(false);
    };
    document.addEventListener("keydown", escape);
    document.addEventListener("mousedown", outside);
    return () => { document.removeEventListener("keydown", escape); document.removeEventListener("mousedown", outside); };
  }, [open]);
  useEffect(() => { if (!open) triggerRef.current?.focus(); }, [open]);
  const openEditor = () => { setDraft(clonePreferences(saved)); setOpen(true); };
  const save = async () => { if (!draft) return; await update.mutateAsync(draft); setOpen(false); };
  if (preferences.isLoading) return <section className="world-clock-panel panel" aria-label="World clock"><div className="panel-heading"><div><span className="eyebrow">WORLD CLOCK</span><h2>Дэлхийн цаг</h2></div><span className="skeleton world-clock-skeleton-icon" /></div><div className="world-clock-loading"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></div></section>;
  if (preferences.isError) return <section className="world-clock-panel panel" aria-label="World clock"><div className="panel-heading"><div><span className="eyebrow">WORLD CLOCK</span><h2>Дэлхийн цаг</h2></div></div><p className="world-clock-error">Цагийн тохиргоо ачаалагдсангүй.</p><button type="button" className="secondary-action compact" onClick={() => preferences.refetch()}>Дахин оролдох</button></section>;
  return (
    <section className={`world-clock-panel panel ${open ? "settings-open" : ""}`} aria-label="World clock">
      <div className="panel-heading"><div><span className="eyebrow">WORLD CLOCK</span><h2>Дэлхийн цаг</h2></div><button ref={triggerRef} type="button" className="world-clock-settings-trigger" onClick={openEditor} aria-expanded={open} aria-label="Цагийн тохиргоо"><Settings2 size={17} /></button></div>
      {saved.clocks.length ? <div className={`world-clock-list ${saved.display_mode} count-${saved.clocks.length}`}>
        {saved.clocks.map((timezone) => saved.display_mode === "analog" ? <AnalogClock key={timezone} timezone={timezone} hourFormat={saved.hour_format} now={now} localTimezone={localTimezone} /> : <article className="world-clock-tile" key={timezone}><div className="world-clock-tile-city"><Clock3 size={14} /><span><strong>{timezoneLabel(timezone)}</strong><small>{timezone}</small></span></div><DigitalClock timezone={timezone} hourFormat={saved.hour_format} now={now} localTimezone={localTimezone} /></article>)}
      </div> : <div className="world-clock-empty"><Clock3 size={25} /><strong>Цаг нэмээгүй байна</strong><span>Ажлынхаа хотуудын цагийг нэг дор хараарай.</span><button type="button" className="secondary-action compact" onClick={openEditor}><Plus size={14} />Цаг нэмэх</button></div>}
      {open && <div className="world-clock-settings-layer" onMouseDown={() => setOpen(false)}><WorldClockEditor draft={draft || clonePreferences(saved)} onChange={setDraft} onClose={() => setOpen(false)} onSave={save} saving={update.isPending} /></div>}
    </section>
  );
}
