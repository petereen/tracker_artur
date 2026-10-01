import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, Pencil, Plus, Trash2, X } from "lucide-react";
import toast from "react-hot-toast";
import { useTranslation } from "react-i18next";
import {
  ContractCustomField,
  ContractDetail,
  ContractGroup,
  ContractLink,
  ContractRegistry,
  ContractRegistryInput,
  ContractRegistryOptions,
  useContractPartyOptions,
  useCreateContractGroup,
  useDeleteContractGroup,
  useUpdateContractGroup,
  useUpdateContractRegistry,
} from "../api/enterprise";
import { labelMap } from "../utils/labelMap";
import { intlLocale } from "../utils/locale";

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
const LINK_KINDS = labelMap<ContractLink["kind"]>("contracts.registry.linkKind", ["online", "shared", "path"]);

const text = (value: unknown) =>
  value === null || value === undefined ? "" : String(value);

export function registryDraftFrom(
  initial?: Partial<ContractRegistry>,
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
  return `${new Intl.NumberFormat(intlLocale(), { maximumFractionDigits: 2 }).format(value)} ${currency}`;
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
  emptyLabel,
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
  const { t } = useTranslation();
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
      <option value="">{emptyLabel ?? t("contracts.registry.noGroup")}</option>
      {options.map((group) => (
        <option key={group.id} value={group.id}>
          {groupLabel(group, groups)}
          {group.is_active ? "" : ` ${t("contracts.registry.inactiveParen")}`}
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
  const { t } = useTranslation();
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
        placeholder={t("contracts.registry.partySearchPlaceholder")}
        aria-label={t("contracts.registry.partySearchAria")}
        disabled={disabled}
      />
      <select
        aria-label={t("contracts.registry.partyAria")}
        value={value ? String(value) : ""}
        disabled={disabled}
        onChange={(event) => {
          const party = rows.find((row) => String(row.id) === event.target.value);
          onChange(party ? { id: party.id, payment_term_id: party.payment_term_id, currency: party.currency } : null);
        }}
      >
        <option value="">{t("contracts.registry.noParty")}</option>
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
        {t("contracts.registry.headParty")}{" "}
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
  const { t } = useTranslation();
  const update = (index: number, patch: Partial<ContractLink>) =>
    onChange(links.map((link, i) => (i === index ? { ...link, ...patch } : link)));
  return (
    <div className="contract-repeat-list">
      {links.map((link, index) => (
        <div className="contract-repeat-row" key={index}>
          <select
            aria-label={t("contracts.registry.linkKindAria")}
            value={link.kind}
            onChange={(event) => update(index, { kind: event.target.value as ContractLink["kind"] })}
            disabled={disabled}
          >
            {Object.entries(LINK_KINDS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <input
            aria-label={t("contracts.registry.linkLabelAria")}
            value={link.label}
            placeholder={t("contracts.registry.linkLabelPlaceholder")}
            onChange={(event) => update(index, { label: event.target.value })}
            disabled={disabled}
          />
          <input
            aria-label={t("contracts.registry.linkUrlAria")}
            value={link.url}
            placeholder={link.kind === "path" ? t("contracts.registry.pathPlaceholder") : "https://"}
            onChange={(event) => update(index, { url: event.target.value })}
            disabled={disabled}
          />
          <button
            type="button"
            className="contract-icon-button contract-icon-button-small"
            aria-label={t("contracts.registry.removeLink")}
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
          <Plus size={14} /> {t("contracts.registry.addLink")}
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
  const { t } = useTranslation();
  const update = (index: number, patch: Partial<ContractCustomField>) =>
    onChange(fields.map((field, i) => (i === index ? { ...field, ...patch } : field)));
  return (
    <div className="contract-repeat-list">
      {fields.map((field, index) => (
        <div className="contract-repeat-row contract-repeat-row-meta" key={index}>
          <input
            aria-label={t("contracts.registry.metaNameAria")}
            value={field.label}
            placeholder={t("contracts.registry.metaFieldPlaceholder")}
            onChange={(event) => update(index, { label: event.target.value })}
            disabled={disabled}
          />
          <input
            aria-label={t("contracts.registry.metaValueAria")}
            value={field.value}
            placeholder={t("contracts.registry.metaValuePlaceholder")}
            onChange={(event) => update(index, { value: event.target.value })}
            disabled={disabled}
          />
          <button
            type="button"
            className="contract-icon-button contract-icon-button-small"
            aria-label={t("contracts.registry.removeMeta")}
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
          <Plus size={14} /> {t("contracts.registry.addMeta")}
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
  const { t } = useTranslation();
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
      <div className="section-label">{t("contracts.registry.heading")}</div>
      <div className="contract-form-grid contract-registry-grid">
        <label>
          {t("contracts.registry.code")}
          <input
            value={draft.code}
            onChange={(event) => set({ code: event.target.value })}
            placeholder={options?.next_code ? t("contracts.registry.codeAuto", { code: options.next_code }) : t("contracts.registry.codeAutoDefault")}
            maxLength={64}
            disabled={disabled}
          />
        </label>
        <label>
          {t("contracts.registry.number")}
          <input
            value={draft.contract_number}
            onChange={(event) => set({ contract_number: event.target.value })}
            placeholder={t("contracts.registry.numberPlaceholder")}
            maxLength={120}
            disabled={disabled}
          />
        </label>
        <div className="contract-field">
          <span className="contract-label-row">
            <span id="contract-group-label">{t("contracts.registry.group")}</span>
            {onManageGroups && (
              <button type="button" className="contract-inline-link" onClick={onManageGroups}>
                {t("contracts.registry.manageGroups")}
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
          {t("contracts.registry.signedOn")}
          <input
            type="date"
            value={draft.signed_on}
            onChange={(event) => set({ signed_on: event.target.value })}
            disabled={disabled}
          />
        </label>
        <div className="contract-field contract-registry-wide">
          <span>{t("contracts.registry.partyCrm")}</span>
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
          {t("contracts.registry.quantity")}
          <input
            inputMode="decimal"
            value={draft.quantity}
            onChange={(event) => setQuantityOrPrice({ quantity: event.target.value })}
            disabled={disabled}
          />
        </label>
        <label>
          {t("contracts.registry.unit")}
          <select value={draft.unit_id} onChange={(event) => set({ unit_id: event.target.value })} disabled={disabled}>
            <option value="">{t("contracts.registry.none")}</option>
            {(options?.units ?? []).map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name}{unit.symbol ? ` (${unit.symbol})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("contracts.registry.unitPrice")}
          <input
            inputMode="decimal"
            value={draft.unit_price}
            onChange={(event) => setQuantityOrPrice({ unit_price: event.target.value })}
            disabled={disabled}
          />
        </label>
        <label>
          {t("contracts.registry.amount")}
          <span className="contract-amount-input">
            <input
              inputMode="decimal"
              aria-label={t("contracts.registry.amount")}
              value={draft.amount}
              onChange={(event) => {
                setAmountTouched(true);
                set({ amount: event.target.value });
              }}
              disabled={disabled}
            />
            <select
              aria-label={t("contracts.registry.currency")}
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
          {t("contracts.registry.penalty")}
          <input
            inputMode="decimal"
            value={draft.penalty_pct}
            onChange={(event) => set({ penalty_pct: event.target.value })}
            placeholder="0.5"
            disabled={disabled}
          />
        </label>
        <label>
          {t("contracts.registry.paymentTerm")}
          <select
            value={draft.payment_term_id}
            onChange={(event) => set({ payment_term_id: event.target.value })}
            disabled={disabled}
          >
            <option value="">{t("contracts.registry.none")}</option>
            {(options?.payment_terms ?? []).map((term) => (
              <option key={term.id} value={term.id}>{term.code} · {term.name}</option>
            ))}
          </select>
        </label>
        <label className="contract-registry-wide">
          {t("contracts.registry.note")}
          <textarea
            value={draft.note}
            onChange={(event) => set({ note: event.target.value })}
            rows={2}
            maxLength={5000}
            placeholder={t("contracts.registry.notePlaceholder")}
            disabled={disabled}
          />
        </label>
      </div>
      <div className="contract-form-section">
        <div className="section-label">{t("contracts.registry.linksHeading")}</div>
        <LinksEditor links={draft.links} onChange={(links) => set({ links })} disabled={disabled} />
      </div>
      <div className="contract-form-section">
        <div className="section-label">{t("contracts.registry.metaHeading")}</div>
        <CustomFieldsEditor
          fields={draft.custom_fields}
          onChange={(custom_fields) => set({ custom_fields })}
          disabled={disabled}
        />
      </div>
    </div>
  );
}

export function LinkItem({ link }: { link: ContractLink }) {
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
  const { t } = useTranslation();
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
      onError: (error) => toast.error(contractErrorMessage(error, t("contracts.registry.saveFailed"))),
    });
  const save = () => {
    const payload = registryPayload({ ...registryDraftFrom(detail), contract_number: number, note, links, custom_fields: fields });
    submit(
      { publicId: detail.public_id, contract_number: payload.contract_number, note: payload.note, links: payload.links, custom_fields: payload.custom_fields },
      t("contracts.registry.updated"),
    );
  };
  const isActive = detail.is_active ?? true;
  const quantity =
    detail.quantity !== null && detail.quantity !== undefined
      ? `${new Intl.NumberFormat(intlLocale()).format(detail.quantity)} ${detail.unit?.symbol || detail.unit?.name || ""}`.trim()
      : "—";
  return (
    <div className="contract-rail-card contract-registry-card">
      <div className="contract-registry-card-header">
        <div className="section-label">{t("contracts.registry.heading")}</div>
        <span className={`contract-active-pill ${isActive ? "is-active" : "is-inactive"}`}>
          {isActive ? t("contracts.registry.active") : t("contracts.registry.inactive")}
        </span>
      </div>
      <dl className="contract-registry-list">
        <dt>{t("contracts.registry.code")}</dt><dd>{detail.code || "—"}</dd>
        <dt>{t("contracts.registry.dtNumber")}</dt><dd>{detail.contract_number || "—"}</dd>
        <dt>{t("crm.common.group")}</dt><dd>{detail.group ? `${detail.group.code} · ${detail.group.name}` : "—"}</dd>
        <dt>{t("contracts.registry.dtParty")}</dt><dd>{detail.party ? `${detail.party.code} · ${detail.party.name}` : "—"}</dd>
        <dt>{t("crm.party.parent")}</dt><dd>{detail.head_party ? `${detail.head_party.code} · ${detail.head_party.name}` : "—"}</dd>
        <dt>{t("contracts.registry.dtDate")}</dt><dd>{detail.signed_on || "—"}</dd>
        <dt>{t("contracts.registry.dtEnds")}</dt><dd>{detail.effective_end_on || "—"}</dd>
        <dt>{t("contracts.registry.dtOverdue")}</dt><dd className={detail.overdue_days ? "contract-overdue" : ""}>{detail.overdue_days ?? 0}</dd>
        <dt>{t("contracts.registry.quantity")}</dt><dd>{quantity}</dd>
        <dt>{t("contracts.registry.unitPrice")}</dt><dd>{formatContractMoney(detail.unit_price, detail.currency)}</dd>
        <dt>{t("contracts.registry.amount")}</dt><dd><strong>{formatContractMoney(detail.amount, detail.currency)}</strong></dd>
        <dt>{t("contracts.registry.dtPenalty")}</dt><dd>{detail.penalty_pct !== null && detail.penalty_pct !== undefined ? `${detail.penalty_pct}%` : "—"}</dd>
        <dt>{t("contracts.registry.paymentTerm")}</dt><dd>{detail.payment_term ? detail.payment_term.name : "—"}</dd>
        <dt>{t("contracts.registry.dtFiles")}</dt><dd>{detail.file_count ?? detail.files.length}</dd>
      </dl>
      {editing ? (
        <div className="contract-registry-edit">
          <label>
            {t("contracts.registry.number")}
            <input value={number} maxLength={120} onChange={(event) => setNumber(event.target.value)} />
          </label>
          <label>
            {t("contracts.registry.note")}
            <textarea value={note} rows={2} maxLength={5000} onChange={(event) => setNote(event.target.value)} />
          </label>
          <div className="section-label">{t("contracts.registry.dtLink")}</div>
          <LinksEditor links={links} onChange={setLinks} />
          <div className="section-label">{t("contracts.registry.dtMeta")}</div>
          <CustomFieldsEditor fields={fields} onChange={setFields} />
          <div className="contract-registry-actions">
            <button type="button" className="button button-secondary" onClick={() => { reset(); setEditing(false); }}>
              {t("contracts.registry.cancel")}
            </button>
            <button type="button" className="button button-primary" onClick={save} disabled={update.isPending}>
              {t("contracts.registry.save")}
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
                <Pencil size={14} /> {t("contracts.registry.edit")}
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={update.isPending}
                onClick={() => {
                  if (isActive && !window.confirm(t("contracts.registry.confirmDeactivate"))) return;
                  submit({ publicId: detail.public_id, is_active: !isActive }, isActive ? t("contracts.registry.deactivated") : t("contracts.registry.activated"));
                }}
              >
                {isActive ? t("contracts.registry.deactivate") : t("contracts.registry.activate")}
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
  const { t } = useTranslation();
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
  const onError = (error: unknown) => toast.error(contractErrorMessage(error, t("contracts.registry.groups.saveFailed")));
  const save = () => {
    if (!code.trim() || !name.trim()) return toast.error(t("contracts.registry.groups.required"));
    const input = { code: code.trim(), name: name.trim(), parent_id: parentId ? Number(parentId) : null };
    if (editingId)
      updateGroup.mutate({ id: editingId, ...input }, { onSuccess: () => { toast.success(t("contracts.registry.groups.updated")); resetForm(); }, onError });
    else create.mutate(input, { onSuccess: () => { toast.success(t("contracts.registry.groups.added")); resetForm(); }, onError });
  };
  return createPortal(
    <div className="contract-modal-backdrop" onClick={onClose}>
      <div className="contract-group-modal" role="dialog" aria-label={t("contracts.registry.groups.title")} onClick={(event) => event.stopPropagation()}>
        <header className="contract-panel-header">
          <div>
            <span className="eyebrow">{t("contracts.registry.groups.eyebrow")}</span>
            <h2>{t("contracts.registry.groups.title")}</h2>
          </div>
          <button type="button" className="contract-icon-button" aria-label={t("contracts.registry.groups.close")} onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="contract-form-grid">
          <label>
            {t("contracts.registry.code")}
            <input value={code} maxLength={40} onChange={(event) => setCode(event.target.value)} placeholder="SALES" />
          </label>
          <label>
            {t("contracts.registry.groups.name")}
            <input value={name} maxLength={240} onChange={(event) => setName(event.target.value)} placeholder={t("contracts.registry.groups.namePlaceholder")} />
          </label>
          <label>
            {t("contracts.registry.groups.parent")}
            <ContractGroupSelect
              value={parentId}
              onChange={setParentId}
              groups={groups.filter((row) => row.id !== editingId)}
              emptyLabel={t("contracts.registry.groups.top")}
              aria-label={t("contracts.registry.groups.parent")}
            />
          </label>
          <div className="contract-registry-actions">
            {editingId && (
              <button type="button" className="button button-secondary" onClick={resetForm}>{t("contracts.registry.cancel")}</button>
            )}
            <button type="button" className="button button-primary" onClick={save} disabled={create.isPending || updateGroup.isPending}>
              {editingId ? t("contracts.registry.save") : t("crm.common.add")}
            </button>
          </div>
        </div>
        <ul className="contract-group-list">
          {ordered.map((group) => (
            <li key={group.id} className={group.is_active ? "" : "is-inactive"}>
              <span>
                <strong>{groupLabel(group, groups)}</strong>
                <small>{t("contracts.registry.groups.count", { n: group.contract_count })}{group.is_active ? "" : ` · ${t("contracts.registry.inactive")}`}</small>
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
                  {t("contracts.registry.groups.edit")}
                </button>
                <button
                  type="button"
                  className="contract-inline-link"
                  onClick={() => updateGroup.mutate({ id: group.id, is_active: !group.is_active }, { onError })}
                >
                  {group.is_active ? t("contracts.registry.deactivate") : t("contracts.registry.activate")}
                </button>
                {!group.contract_count && (
                  <button
                    type="button"
                    className="contract-inline-link contract-inline-danger"
                    onClick={() => {
                      if (window.confirm(t("contracts.registry.groups.confirmDelete", { name: group.name })))
                        remove.mutate(group.id, { onSuccess: () => toast.success(t("contracts.registry.groups.deleted")), onError });
                    }}
                  >
                    {t("contracts.registry.groups.delete")}
                  </button>
                )}
              </span>
            </li>
          ))}
          {!ordered.length && <li className="contract-empty-inline">{t("contracts.registry.groups.empty")}</li>}
        </ul>
      </div>
    </div>,
    document.body,
  );
}
