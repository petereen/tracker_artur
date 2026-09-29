import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, Pencil, Plus, Trash2, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  ContractCustomField,
  ContractDetail,
  ContractGroup,
  ContractLink,
  ContractRegistryInput,
  ContractRegistryOptions,
  useContractPartyOptions,
  useCreateContractGroup,
  useDeleteContractGroup,
  useUpdateContractGroup,
  useUpdateContractRegistry,
} from "../api/enterprise";

/** Registry metadata of a contract (Dayansoft d028 «Гэрээ бүртгэх»), as edited in the form. */
export interface ContractRegistryDraft {
  code: string;
  contract_number: string;
  group_id: string;
  party_id: number | null;
  signed_on: string;
  quantity: string;
  unit_id: string;
  unit_price: string;
  amount: string;
  currency: string;
  penalty_pct: string;
  payment_term_id: string;
  note: string;
  links: ContractLink[];
  custom_fields: ContractCustomField[];
}

const CURRENCIES = ["MNT", "USD", "EUR", "CNY", "RUB", "KRW", "JPY"];
const LINK_KINDS: Record<ContractLink["kind"], string> = {
  online: "Online link",
  shared: "Shared link",
  path: "Файлын зам",
};

const text = (value: unknown) =>
  value === null || value === undefined ? "" : String(value);

export function registryDraftFrom(
  initial?: Partial<ContractDetail>,
): ContractRegistryDraft {
  return {
    code: text(initial?.code),
    contract_number: text(initial?.contract_number),
    group_id: text(initial?.group_id),
    party_id: initial?.party_id ?? null,
    signed_on: text(initial?.signed_on),
    quantity: text(initial?.quantity),
    unit_id: text(initial?.unit_id),
    unit_price: text(initial?.unit_price),
    amount: text(initial?.amount),
    currency: initial?.currency || "MNT",
    penalty_pct: text(initial?.penalty_pct),
    payment_term_id: text(initial?.payment_term_id),
    note: text(initial?.note),
    links: initial?.links ?? [],
    custom_fields: initial?.custom_fields ?? [],
  };
}

const idOrNull = (value: string) => (value ? Number(value) : null);
const numberOrNull = (value: string) => {
  const cleaned = value.replace(/[\s,]/g, "");
  return cleaned ? cleaned : null;
};

export function registryPayload(
  draft: ContractRegistryDraft,
): ContractRegistryInput {
  return {
    code: draft.code.trim() || null,
    contract_number: draft.contract_number.trim() || null,
    group_id: idOrNull(draft.group_id),
    party_id: draft.party_id,
    signed_on: draft.signed_on || null,
    quantity: numberOrNull(draft.quantity),
    unit_id: idOrNull(draft.unit_id),
    unit_price: numberOrNull(draft.unit_price),
    amount: numberOrNull(draft.amount),
    currency: draft.currency || "MNT",
    penalty_pct: numberOrNull(draft.penalty_pct),
    payment_term_id: idOrNull(draft.payment_term_id),
    note: draft.note.trim() || null,
    links: draft.links
      .map((link) => ({ ...link, label: link.label.trim(), url: link.url.trim() }))
      .filter((link) => link.url),
    custom_fields: draft.custom_fields
      .map((field) => ({ label: field.label.trim(), value: field.value.trim() }))
      .filter((field) => field.label),
  };
}

/** Readable message for string, `{code, message}` and pydantic 422 error details. */
export function contractErrorMessage(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = Array.isArray(first?.loc) ? first.loc.slice(1).join(".") : "";
    return [field, first?.msg].filter(Boolean).join(": ") || fallback;
  }
  return fallback;
}

export function formatContractMoney(
  value: number | null | undefined,
  currency = "MNT",
) {
  if (value === null || value === undefined) return "—";
  return `${new Intl.NumberFormat("mn-MN", { maximumFractionDigits: 2 }).format(value)} ${currency}`;
}

function groupLabel(group: ContractGroup, groups: ContractGroup[]) {
  let depth = 0;
  let parent = groups.find((row) => row.id === group.parent_id);
  while (parent && depth < 6) {
    depth += 1;
    parent = groups.find((row) => row.id === parent!.parent_id);
  }
  return `${"— ".repeat(depth)}${group.code} · ${group.name}`;
}

/** Groups ordered as a tree (parents followed by their children). */
function orderedGroups(groups: ContractGroup[]) {
  const output: ContractGroup[] = [];
  const visit = (parentId: number | null, depth: number) => {
    if (depth > 6) return;
    groups
      .filter((row) => row.parent_id === parentId)
      .forEach((row) => {
        output.push(row);
        visit(row.id, depth + 1);
      });
  };
  visit(null, 0);
  groups.forEach((row) => {
    if (!output.includes(row)) output.push(row);
  });
  return output;
}

export function ContractGroupSelect({
  value,
  onChange,
  groups,
  disabled,
  emptyLabel = "Бүлэггүй",
  includeInactive = false,
  ...rest
}: {
  value: string;
  onChange: (value: string) => void;
  groups: ContractGroup[];
  disabled?: boolean;
  emptyLabel?: string;
  includeInactive?: boolean;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  const options = orderedGroups(groups).filter(
    (row) => includeInactive || row.is_active || String(row.id) === value,
  );
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      {...rest}
    >
      <option value="">{emptyLabel}</option>
      {options.map((group) => (
        <option key={group.id} value={group.id}>
          {groupLabel(group, groups)}
          {group.is_active ? "" : " (идэвхгүй)"}
        </option>
      ))}
    </select>
  );
}

function PartyPicker({
  value,
  initialLabel,
  disabled,
  onChange,
}: {
  value: number | null;
  initialLabel?: string;
  disabled: boolean;
  onChange: (party: { id: number; payment_term_id: number | null; currency: string } | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);
  const parties = useContractPartyOptions(debounced, value);
  const rows = Array.isArray(parties.data) ? parties.data : [];
  const selected = rows.find((row) => row.id === value);
  return (
    <div className="contract-party-picker">
      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Харилцагч хайх (нэр, код, ТТД)"
        aria-label="Харилцагч хайх"
        disabled={disabled}
      />
      <select
        aria-label="Харилцагч"
        value={value ? String(value) : ""}
        disabled={disabled}
        onChange={(event) => {
          const party = rows.find((row) => String(row.id) === event.target.value);
          onChange(party ? { id: party.id, payment_term_id: party.payment_term_id, currency: party.currency } : null);
        }}
      >
        <option value="">Харилцагч сонгохгүй</option>
        {value && !selected && initialLabel && (
          <option value={value}>{initialLabel}</option>
        )}
        {rows.map((party) => (
          <option key={party.id} value={party.id}>
            {party.code} · {party.name}
          </option>
        ))}
      </select>
      <small className="field-help">
        Толгой харилцагч:{" "}
        {selected?.head_party
          ? `${selected.head_party.code} · ${selected.head_party.name}`
          : "—"}
      </small>
    </div>
  );
}

export function LinksEditor({
  links,
  onChange,
  disabled,
}: {
  links: ContractLink[];
  onChange: (links: ContractLink[]) => void;
  disabled?: boolean;
}) {
  const update = (index: number, patch: Partial<ContractLink>) =>
    onChange(links.map((link, i) => (i === index ? { ...link, ...patch } : link)));
  return (
    <div className="contract-repeat-list">
      {links.map((link, index) => (
        <div className="contract-repeat-row" key={index}>
          <select
            aria-label="Линкийн төрөл"
            value={link.kind}
            onChange={(event) => update(index, { kind: event.target.value as ContractLink["kind"] })}
            disabled={disabled}
          >
            {Object.entries(LINK_KINDS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <input
            aria-label="Линкийн нэр"
            value={link.label}
            placeholder="Нэр (жишээ: Скан хувь)"
            onChange={(event) => update(index, { label: event.target.value })}
            disabled={disabled}
          />
          <input
            aria-label="Холбоос"
            value={link.url}
            placeholder={link.kind === "path" ? "\\\\server\\share\\гэрээ.pdf" : "https://"}
            onChange={(event) => update(index, { url: event.target.value })}
            disabled={disabled}
          />
          <button
            type="button"
            className="contract-icon-button contract-icon-button-small"
            aria-label="Линк хасах"
            onClick={() => onChange(links.filter((_, i) => i !== index))}
            disabled={disabled}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {!disabled && links.length < 20 && (
        <button
          type="button"
          className="contract-add-row"
          onClick={() => onChange([...links, { kind: "online", label: "", url: "" }])}
        >
          <Plus size={14} /> Линк нэмэх
        </button>
      )}
    </div>
  );
}

export function CustomFieldsEditor({
  fields,
  onChange,
  disabled,
}: {
  fields: ContractCustomField[];
  onChange: (fields: ContractCustomField[]) => void;
  disabled?: boolean;
}) {
  const update = (index: number, patch: Partial<ContractCustomField>) =>
    onChange(fields.map((field, i) => (i === index ? { ...field, ...patch } : field)));
  return (
    <div className="contract-repeat-list">
      {fields.map((field, index) => (
        <div className="contract-repeat-row contract-repeat-row-meta" key={index}>
          <input
            aria-label="Мета талбарын нэр"
            value={field.label}
            placeholder="Талбар"
            onChange={(event) => update(index, { label: event.target.value })}
            disabled={disabled}
          />
          <input
            aria-label="Мета утга"
            value={field.value}
            placeholder="Утга"
            onChange={(event) => update(index, { value: event.target.value })}
            disabled={disabled}
          />
          <button
            type="button"
            className="contract-icon-button contract-icon-button-small"
            aria-label="Мета хасах"
            onClick={() => onChange(fields.filter((_, i) => i !== index))}
            disabled={disabled}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {!disabled && fields.length < 30 && (
        <button
          type="button"
          className="contract-add-row"
          onClick={() => onChange([...fields, { label: "", value: "" }])}
        >
          <Plus size={14} /> Мета нэмэх
        </button>
      )}
    </div>
  );
}

/** Registry fields of the contract composer (d028 §3–§5, §9–§10). */
export function ContractRegistryForm({
  draft,
  onChange,
  options,
  disabled,
  partyLabel,
  onManageGroups,
}: {
  draft: ContractRegistryDraft;
  onChange: (draft: ContractRegistryDraft) => void;
  options?: ContractRegistryOptions;
  disabled: boolean;
  partyLabel?: string;
  onManageGroups?: () => void;
}) {
  const [amountTouched, setAmountTouched] = useState(Boolean(draft.amount));
  const set = (patch: Partial<ContractRegistryDraft>) => onChange({ ...draft, ...patch });
  const setQuantityOrPrice = (patch: Partial<ContractRegistryDraft>) => {
    const next = { ...draft, ...patch };
    const quantity = Number(next.quantity.replace(/[\s,]/g, ""));
    const price = Number(next.unit_price.replace(/[\s,]/g, ""));
    if (!amountTouched && next.quantity && next.unit_price && Number.isFinite(quantity) && Number.isFinite(price))
      next.amount = String(Math.round(quantity * price * 100) / 100);
    onChange(next);
  };
  const groups = options?.groups ?? [];
  return (
    <div className="contract-registry">
      <div className="section-label">Гэрээний бүртгэл</div>
      <div className="contract-form-grid contract-registry-grid">
        <label>
          Код
          <input
            value={draft.code}
            onChange={(event) => set({ code: event.target.value })}
            placeholder={options?.next_code ? `Автомат: ${options.next_code}` : "Автоматаар олгоно"}
            maxLength={64}
            disabled={disabled}
          />
        </label>
        <label>
          Гэрээний дугаар
          <input
            value={draft.contract_number}
            onChange={(event) => set({ contract_number: event.target.value })}
            placeholder="Албан ёсны дугаар"
            maxLength={120}
            disabled={disabled}
          />
        </label>
        <div className="contract-field">
          <span className="contract-label-row">
            <span id="contract-group-label">Гэрээний бүлэг</span>
            {onManageGroups && (
              <button type="button" className="contract-inline-link" onClick={onManageGroups}>
                Бүлэг тохируулах
              </button>
            )}
          </span>
          <ContractGroupSelect
            value={draft.group_id}
            onChange={(group_id) => set({ group_id })}
            groups={groups}
            disabled={disabled}
            aria-labelledby="contract-group-label"
          />
        </div>
        <label>
          Гэрээ байгуулсан огноо
          <input
            type="date"
            value={draft.signed_on}
            onChange={(event) => set({ signed_on: event.target.value })}
            disabled={disabled}
          />
        </label>
        <div className="contract-field contract-registry-wide">
          <span>Харилцагч (CRM)</span>
          <PartyPicker
            value={draft.party_id}
            initialLabel={partyLabel}
            disabled={disabled}
            onChange={(party) =>
              onChange({
                ...draft,
                party_id: party?.id ?? null,
                payment_term_id:
                  draft.payment_term_id || (party?.payment_term_id ? String(party.payment_term_id) : ""),
                currency: draft.currency === "MNT" && party?.currency ? party.currency : draft.currency,
              })
            }
          />
        </div>
        <label>
          Тоо хэмжээ
          <input
            inputMode="decimal"
            value={draft.quantity}
            onChange={(event) => setQuantityOrPrice({ quantity: event.target.value })}
            disabled={disabled}
          />
        </label>
        <label>
          Хэмжих нэгж
          <select value={draft.unit_id} onChange={(event) => set({ unit_id: event.target.value })} disabled={disabled}>
            <option value="">Сонгохгүй</option>
            {(options?.units ?? []).map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name}{unit.symbol ? ` (${unit.symbol})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          Нэгж үнэ
          <input
            inputMode="decimal"
            value={draft.unit_price}
            onChange={(event) => setQuantityOrPrice({ unit_price: event.target.value })}
            disabled={disabled}
          />
        </label>
        <label>
          Гэрээний дүн
          <span className="contract-amount-input">
            <input
              inputMode="decimal"
              aria-label="Гэрээний дүн"
              value={draft.amount}
              onChange={(event) => {
                setAmountTouched(true);
                set({ amount: event.target.value });
              }}
              disabled={disabled}
            />
            <select
              aria-label="Валют"
              value={draft.currency}
              onChange={(event) => set({ currency: event.target.value })}
              disabled={disabled}
            >
              {[...new Set([draft.currency, ...CURRENCIES])].map((code) => (
                <option key={code} value={code}>{code}</option>
              ))}
            </select>
          </span>
        </label>
        <label>
          Алданги %
          <input
            inputMode="decimal"
            value={draft.penalty_pct}
            onChange={(event) => set({ penalty_pct: event.target.value })}
            placeholder="0.5"
            disabled={disabled}
          />
        </label>
        <label>
          Төлбөрийн нөхцөл
          <select
            value={draft.payment_term_id}
            onChange={(event) => set({ payment_term_id: event.target.value })}
            disabled={disabled}
          >
            <option value="">Сонгохгүй</option>
            {(options?.payment_terms ?? []).map((term) => (
              <option key={term.id} value={term.id}>{term.code} · {term.name}</option>
            ))}
          </select>
        </label>
        <label className="contract-registry-wide">
          Тайлбар
          <textarea
            value={draft.note}
            onChange={(event) => set({ note: event.target.value })}
            rows={2}
            maxLength={5000}
            placeholder="Нэмэлт нөхцөл, тэмдэглэл"
            disabled={disabled}
          />
        </label>
      </div>
      <div className="contract-form-section">
        <div className="section-label">Файлын холбоос (online / shared / зам)</div>
        <LinksEditor links={draft.links} onChange={(links) => set({ links })} disabled={disabled} />
      </div>
      <div className="contract-form-section">
        <div className="section-label">Мета — нэмэлт мэдээлэл</div>
        <CustomFieldsEditor
          fields={draft.custom_fields}
          onChange={(custom_fields) => set({ custom_fields })}
          disabled={disabled}
        />
      </div>
    </div>
  );
}

function LinkItem({ link }: { link: ContractLink }) {
  const safe = link.kind !== "path" && /^https?:\/\//i.test(link.url);
  const label = link.label || LINK_KINDS[link.kind];
  return (
    <li>
      <small>{LINK_KINDS[link.kind]}</small>
      {safe ? (
        <a href={link.url} target="_blank" rel="noreferrer noopener">
          {label} <ExternalLink size={12} />
        </a>
      ) : (
        <span>
          {label}: <code>{link.url}</code>
        </span>
      )}
    </li>
  );
}

/** Read view of the registry plus the post-approval editable part (number, active, links, meta, note). */
export function ContractRegistryPanel({
  detail,
  canManage,
}: {
  detail: ContractDetail;
  canManage: boolean;
}) {
  const update = useUpdateContractRegistry();
  const [editing, setEditing] = useState(false);
  const [number, setNumber] = useState(detail.contract_number ?? "");
  const [note, setNote] = useState(detail.note ?? "");
  const [links, setLinks] = useState<ContractLink[]>(detail.links ?? []);
  const [fields, setFields] = useState<ContractCustomField[]>(detail.custom_fields ?? []);
  const reset = () => {
    setNumber(detail.contract_number ?? "");
    setNote(detail.note ?? "");
    setLinks(detail.links ?? []);
    setFields(detail.custom_fields ?? []);
  };
  const submit = (input: Parameters<typeof update.mutate>[0], success: string) =>
    update.mutate(input, {
      onSuccess: () => {
        toast.success(success);
        setEditing(false);
      },
      onError: (error) => toast.error(contractErrorMessage(error, "Хадгалж чадсангүй")),
    });
  const save = () => {
    const payload = registryPayload({ ...registryDraftFrom(detail), contract_number: number, note, links, custom_fields: fields });
    submit(
      { publicId: detail.public_id, contract_number: payload.contract_number, note: payload.note, links: payload.links, custom_fields: payload.custom_fields },
      "Гэрээний бүртгэл шинэчлэгдлээ",
    );
  };
  const isActive = detail.is_active ?? true;
  const quantity =
    detail.quantity !== null && detail.quantity !== undefined
      ? `${new Intl.NumberFormat("mn-MN").format(detail.quantity)} ${detail.unit?.symbol || detail.unit?.name || ""}`.trim()
      : "—";
  return (
    <div className="contract-rail-card contract-registry-card">
      <div className="contract-registry-card-header">
        <div className="section-label">Гэрээний бүртгэл</div>
        <span className={`contract-active-pill ${isActive ? "is-active" : "is-inactive"}`}>
          {isActive ? "Идэвхтэй" : "Идэвхгүй"}
        </span>
      </div>
      <dl className="contract-registry-list">
        <dt>Код</dt><dd>{detail.code || "—"}</dd>
        <dt>Дугаар</dt><dd>{detail.contract_number || "—"}</dd>
        <dt>Бүлэг</dt><dd>{detail.group ? `${detail.group.code} · ${detail.group.name}` : "—"}</dd>
        <dt>Харилцагч</dt><dd>{detail.party ? `${detail.party.code} · ${detail.party.name}` : "—"}</dd>
        <dt>Толгой харилцагч</dt><dd>{detail.head_party ? `${detail.head_party.code} · ${detail.head_party.name}` : "—"}</dd>
        <dt>Огноо</dt><dd>{detail.signed_on || "—"}</dd>
        <dt>Дуусах</dt><dd>{detail.effective_end_on || "—"}</dd>
        <dt>Хэтэрсэн хоног</dt><dd className={detail.overdue_days ? "contract-overdue" : ""}>{detail.overdue_days ?? 0}</dd>
        <dt>Тоо хэмжээ</dt><dd>{quantity}</dd>
        <dt>Нэгж үнэ</dt><dd>{formatContractMoney(detail.unit_price, detail.currency)}</dd>
        <dt>Гэрээний дүн</dt><dd><strong>{formatContractMoney(detail.amount, detail.currency)}</strong></dd>
        <dt>Алданги</dt><dd>{detail.penalty_pct !== null && detail.penalty_pct !== undefined ? `${detail.penalty_pct}%` : "—"}</dd>
        <dt>Төлбөрийн нөхцөл</dt><dd>{detail.payment_term ? detail.payment_term.name : "—"}</dd>
        <dt>Файлын тоо</dt><dd>{detail.file_count ?? detail.files.length}</dd>
      </dl>
      {editing ? (
        <div className="contract-registry-edit">
          <label>
            Гэрээний дугаар
            <input value={number} maxLength={120} onChange={(event) => setNumber(event.target.value)} />
          </label>
          <label>
            Тайлбар
            <textarea value={note} rows={2} maxLength={5000} onChange={(event) => setNote(event.target.value)} />
          </label>
          <div className="section-label">Линк</div>
          <LinksEditor links={links} onChange={setLinks} />
          <div className="section-label">Мета</div>
          <CustomFieldsEditor fields={fields} onChange={setFields} />
          <div className="contract-registry-actions">
            <button type="button" className="button button-secondary" onClick={() => { reset(); setEditing(false); }}>
              Болих
            </button>
            <button type="button" className="button button-primary" onClick={save} disabled={update.isPending}>
              Хадгалах
            </button>
          </div>
        </div>
      ) : (
        <>
          {detail.note && <p className="contract-registry-note">{detail.note}</p>}
          {!!detail.links?.length && (
            <ul className="contract-registry-links">
              {detail.links.map((link, index) => <LinkItem key={index} link={link} />)}
            </ul>
          )}
          {!!detail.custom_fields?.length && (
            <dl className="contract-registry-list">
              {detail.custom_fields.map((field, index) => (
                <FragmentRow key={index} label={field.label} value={field.value} />
              ))}
            </dl>
          )}
          {canManage && (
            <div className="contract-registry-actions">
              <button type="button" className="button button-secondary" onClick={() => { reset(); setEditing(true); }}>
                <Pencil size={14} /> Бүртгэл засах
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={update.isPending}
                onClick={() => {
                  if (isActive && !window.confirm("Гэрээг идэвхгүй болгох уу? Хугацааны сануулга зогсоно.")) return;
                  submit({ publicId: detail.public_id, is_active: !isActive }, isActive ? "Гэрээ идэвхгүй боллоо" : "Гэрээ идэвхжлээ");
                }}
              >
                {isActive ? "Идэвхгүй болгох" : "Идэвхжүүлэх"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value || "—"}</dd>
    </>
  );
}

/** Admin / legal counsel: manage the hierarchical contract groups (d028 §8). */
export function ContractGroupManager({
  groups,
  onClose,
}: {
  groups: ContractGroup[];
  onClose: () => void;
}) {
  const create = useCreateContractGroup();
  const updateGroup = useUpdateContractGroup();
  const remove = useDeleteContractGroup();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const ordered = useMemo(() => orderedGroups(groups), [groups]);
  const resetForm = () => {
    setCode("");
    setName("");
    setParentId("");
    setEditingId(null);
  };
  const onError = (error: unknown) => toast.error(contractErrorMessage(error, "Бүлэг хадгалж чадсангүй"));
  const save = () => {
    if (!code.trim() || !name.trim()) return toast.error("Код, нэр оруулна уу");
    const input = { code: code.trim(), name: name.trim(), parent_id: parentId ? Number(parentId) : null };
    if (editingId)
      updateGroup.mutate({ id: editingId, ...input }, { onSuccess: () => { toast.success("Бүлэг шинэчлэгдлээ"); resetForm(); }, onError });
    else create.mutate(input, { onSuccess: () => { toast.success("Бүлэг нэмэгдлээ"); resetForm(); }, onError });
  };
  return createPortal(
    <div className="contract-modal-backdrop" onClick={onClose}>
      <div className="contract-group-modal" role="dialog" aria-label="Гэрээний бүлэг" onClick={(event) => event.stopPropagation()}>
        <header className="contract-panel-header">
          <div>
            <span className="eyebrow">ГЭРЭЭ / БҮЛЭГ</span>
            <h2>Гэрээний бүлэг</h2>
          </div>
          <button type="button" className="contract-icon-button" aria-label="Хаах" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="contract-form-grid">
          <label>
            Код
            <input value={code} maxLength={40} onChange={(event) => setCode(event.target.value)} placeholder="SALES" />
          </label>
          <label>
            Нэр
            <input value={name} maxLength={240} onChange={(event) => setName(event.target.value)} placeholder="Борлуулалтын гэрээ" />
          </label>
          <label>
            Харьяа ангилал
            <ContractGroupSelect
              value={parentId}
              onChange={setParentId}
              groups={groups.filter((row) => row.id !== editingId)}
              emptyLabel="Дээд түвшин"
              aria-label="Харьяа ангилал"
            />
          </label>
          <div className="contract-registry-actions">
            {editingId && (
              <button type="button" className="button button-secondary" onClick={resetForm}>Болих</button>
            )}
            <button type="button" className="button button-primary" onClick={save} disabled={create.isPending || updateGroup.isPending}>
              {editingId ? "Хадгалах" : "Нэмэх"}
            </button>
          </div>
        </div>
        <ul className="contract-group-list">
          {ordered.map((group) => (
            <li key={group.id} className={group.is_active ? "" : "is-inactive"}>
              <span>
                <strong>{groupLabel(group, groups)}</strong>
                <small>{group.contract_count} гэрээ{group.is_active ? "" : " · идэвхгүй"}</small>
              </span>
              <span className="contract-group-actions">
                <button
                  type="button"
                  className="contract-inline-link"
                  onClick={() => {
                    setEditingId(group.id);
                    setCode(group.code);
                    setName(group.name);
                    setParentId(group.parent_id ? String(group.parent_id) : "");
                  }}
                >
                  Засах
                </button>
                <button
                  type="button"
                  className="contract-inline-link"
                  onClick={() => updateGroup.mutate({ id: group.id, is_active: !group.is_active }, { onError })}
                >
                  {group.is_active ? "Идэвхгүй болгох" : "Идэвхжүүлэх"}
                </button>
                {!group.contract_count && (
                  <button
                    type="button"
                    className="contract-inline-link contract-inline-danger"
                    onClick={() => {
                      if (window.confirm(`${group.name} бүлгийг устгах уу?`))
                        remove.mutate(group.id, { onSuccess: () => toast.success("Бүлэг устгагдлаа"), onError });
                    }}
                  >
                    Устгах
                  </button>
                )}
              </span>
            </li>
          ))}
          {!ordered.length && <li className="contract-empty-inline">Бүлэг бүртгээгүй байна</li>}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
