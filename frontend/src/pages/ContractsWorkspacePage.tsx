import { lazy, Suspense, useEffect, useMemo, useState, type ComponentProps } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Archive,
  FileCheck2,
  FileText,
  FileSignature,
  LockKeyhole,
  MessageSquare,
  Paperclip,
  Printer,
  Save,
  Send,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { useTranslation } from "react-i18next";
import { isNativePlatform, requireWebCapability } from "../platform/runtime";
import {
  ContractDetail,
  ContractDocumentType,
  ContractStatus,
  useActor,
  useAddContractComment,
  useApproveContract,
  useConfirmContractFinal,
  useContractDetail,
  useContractList,
  useContractReviewerCandidates,
  useCreateContract,
  useDuplicateContract,
  useMarkContractPrinted,
  useRejectContract,
  useRequestContractChanges,
  useResubmitContract,
  useRecallContract,
  useSubmitContract,
  useUpdateContract,
  useUploadContractFile,
  useEnterpriseTasks,
  useProjects,
  useResolveContractComment,
  useContractRegistryOptions,
} from "../api/enterprise";
import { api } from "../api/client";
import {
  ContractGroupManager,
  ContractGroupSelect,
  ContractRegistryForm,
  ContractRegistryPanel,
  contractErrorMessage,
  formatContractMoney,
  registryDraftFrom,
  registryPayload,
} from "../components/ContractRegistryFields";
import { CreateButton } from "../components/CreateButton";
import { labelMap } from "../utils/labelMap";
import { intlLocale } from "../utils/locale";
const LazyRichContractEditor = lazy(() => import('../components/RichContractEditor').then((module) => ({ default: module.RichContractEditor })))
const LazyQRCodeSVG = lazy(() => import('qrcode.react').then((module) => ({ default: module.QRCodeSVG })))

function RichContractEditor(props: ComponentProps<typeof LazyRichContractEditor>) {
  const { t } = useTranslation();
  return <Suspense fallback={<div className="contract-editor-loading">{t('contracts.editorLoading')}</div>}><LazyRichContractEditor {...props} /></Suspense>
}

function ContractQrCode({ value }: { value: string }) {
  return <Suspense fallback={<span className="contract-qr-loading" aria-hidden="true" />}><LazyQRCodeSVG value={value} size={92} /></Suspense>
}

type ContractView =
  | "all"
  | "drafts"
  | "pending_my_approval"
  | "submitted_by_me"
  | "approved"
  | "signed"
  | "returned";
const EMPTY_BODY = { type: "doc", content: [{ type: "paragraph" }] };
const VIEW_KEYS: ContractView[] = ["all", "drafts", "pending_my_approval", "submitted_by_me", "approved", "returned"];
const typeLabels = labelMap<ContractDocumentType>("contracts.type", ["contract", "agreement", "official_letter", "other"]);
const statusLabels = labelMap<ContractStatus>("contracts.status", ["DRAFT", "PENDING_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "SIGNED_AND_STAMPED"]);

function ContractSectionTabs({ active }: { active: "drafts" | "archive" }) {
  const { t } = useTranslation();
  return (
    <nav className="page-tabs" aria-label={t("contracts.nav.aria")}><div className="page-tabs-list"><a href="/contracts" className={active === "drafts" ? "active" : undefined} aria-current={active === "drafts" ? "page" : undefined}><FileText size={15} />{t("contracts.nav.drafts")}</a><a href="/contracts/archive"><Archive size={15} />{t("contracts.nav.archive")}</a></div></nav>
  );
}

function formatDate(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat(intlLocale(), { dateStyle: "medium" }).format(
        new Date(value),
      )
    : "—";
}
function statusClass(status: ContractStatus) {
  return `contract-status status-${status.toLowerCase()}`;
}

function ContractComposer({
  initial,
  onDone,
  onCancel,
}: {
  initial?: ContractDetail;
  onDone: (id: string) => void;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const candidates = useContractReviewerCandidates();
  const projects = useProjects();
  const create = useCreateContract();
  const update = useUpdateContract();
  const upload = useUploadContractFile();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [type, setType] = useState<ContractDocumentType>(
    initial?.document_type ?? "contract",
  );
  const [body, setBody] = useState<Record<string, unknown>>(
    initial?.body_json ?? EMPTY_BODY,
  );
  const [reviewers, setReviewers] = useState<number[]>(
    initial?.reviewer_account_ids ?? [],
  );
  const [projectId, setProjectId] = useState(
    initial?.project_id ? String(initial.project_id) : "",
  );
  const [taskId, setTaskId] = useState(
    initial?.task_id ? String(initial.task_id) : "",
  );
  const [start, setStart] = useState(initial?.effective_start_on ?? "");
  const [end, setEnd] = useState(initial?.effective_end_on ?? "");
  const [expiryReminderDays, setExpiryReminderDays] = useState<number[]>(initial?.expiry_reminder_days ?? []);
  const [supportingFiles, setSupportingFiles] = useState<File[]>([]);
  const registryOptions = useContractRegistryOptions();
  const [registry, setRegistry] = useState(() => registryDraftFrom(initial));
  const [groupManagerOpen, setGroupManagerOpen] = useState(false);
  const editable =
    !initial ||
    initial.status === "DRAFT" ||
    initial.status === "CHANGES_REQUESTED";
  const tasks = useEnterpriseTasks(projectId ? Number(projectId) : undefined);
  const projectOptions = Array.isArray(projects.data) ? projects.data : [];
  const taskOptions = Array.isArray(tasks.data) ? tasks.data : [];
  const reviewerOptions = Array.isArray(candidates.data) ? candidates.data : [];
  const save = async () => {
    if (!title.trim()) return toast.error(t("contracts.composer.titleRequired"));
    if (!end) return toast.error(t("contracts.composer.endRequired"));
    try {
      const result = initial
        ? await update.mutateAsync({
            publicId: initial.public_id,
            version: initial.version,
            title,
            document_type: type,
            body_json: body,
            reviewer_account_ids: reviewers,
            project_id: projectId ? Number(projectId) : null,
            task_id: taskId ? Number(taskId) : null,
            effective_start_on: start || null,
            effective_end_on: end || null,
            expiry_reminder_days: expiryReminderDays,
            ...registryPayload(registry),
          })
        : await create.mutateAsync({
            title,
            document_type: type,
            body_json: body,
            reviewer_account_ids: reviewers,
            project_id: projectId ? Number(projectId) : null,
            task_id: taskId ? Number(taskId) : null,
            effective_start_on: start || null,
            effective_end_on: end || null,
            expiry_reminder_days: expiryReminderDays,
            ...registryPayload(registry),
          });
      if (!initial && supportingFiles.length) {
        let failedUploads = 0;
        for (const file of supportingFiles) {
          try {
            await upload.mutateAsync({
              publicId: result.public_id,
              purpose: "supporting",
              file,
            });
          } catch {
            failedUploads += 1;
          }
        }
        if (failedUploads)
          toast.error(t("contracts.composer.uploadsFailed", { n: failedUploads }));
      }
      toast.success(t("contracts.composer.saved"));
      onDone(result.public_id);
    } catch (error: any) {
      toast.error(contractErrorMessage(error, t("contracts.composer.saveFailed")));
    }
  };
  const addSupportingFiles = (fileList: FileList | null) => {
    const files = Array.from(fileList || []);
    if (!files.length || !editable) return;
    if (initial) {
      files.forEach((file) =>
        upload.mutate(
          { publicId: initial.public_id, purpose: "supporting", file },
          {
            onSuccess: () => toast.success(t("contracts.composer.attachmentAdded")),
            onError: (error: any) =>
              toast.error(error.response?.data?.detail || t("contracts.composer.attachmentFailed")),
          },
        ),
      );
    } else setSupportingFiles((current) => [...current, ...files]);
  };
  return (
    <section className="contract-composer">
      <header className="contract-panel-header">
        <div>
          <span className="eyebrow">
            {initial ? t("contracts.composer.eyebrowEdit") : t("contracts.composer.eyebrowNew")}
          </span>
          <h2>{initial ? t("contracts.composer.headingEdit") : t("contracts.composer.headingNew")}</h2>
        </div>
        {onCancel && (
          <button
            type="button"
            className="contract-icon-button contract-icon-button-danger"
            onClick={onCancel}
            aria-label={t("contracts.cancel")}
            title={t("contracts.cancel")}
          >
            <X size={19} />
          </button>
        )}
      </header>
      {!editable && (
        <div className="contract-lock-note">
          <LockKeyhole size={16} /> {t("contracts.composer.lockNote")}
        </div>
      )}
      <div className="contract-form-grid">
        <label>
          {t("contracts.composer.title")}
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={!editable}
            placeholder={t("contracts.composer.titlePlaceholder")}
          />
        </label>
        <label>
          {t("contracts.composer.docType")}
          <select
            value={type}
            onChange={(event) =>
              setType(event.target.value as ContractDocumentType)
            }
            disabled={!editable}
          >
            {Object.entries(typeLabels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("contracts.composer.project")}
          <select
            value={projectId}
            onChange={(event) => {
              setProjectId(event.target.value);
              setTaskId("");
            }}
            disabled={!editable}
          >
            <option value="">{t("contracts.composer.noProject")}</option>
            {projectOptions.map((project) => (
              <option key={project.id} value={project.id}>
                {project.code} · {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("contracts.composer.task")}
          <select
            value={taskId}
            onChange={(event) => setTaskId(event.target.value)}
            disabled={!editable || !projectId}
          >
            <option value="">{t("contracts.composer.noTask")}</option>
            {taskOptions.map((task) => (
              <option key={task.id} value={task.id}>
                {task.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("contracts.composer.start")}
          <input
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            disabled={!editable}
          />
        </label>
        <label>
          {t("contracts.composer.end")}
          <input
            type="date"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            disabled={!editable}
            required
          />
        </label>
        <fieldset className="contract-expiry-reminders" disabled={!editable}>
          <legend>{t("contracts.composer.reminders")}</legend>
          {[1, 3, 7, 14, 30, 60, 90].map((days) => (
            <label key={days}>
              <input type="checkbox" checked={expiryReminderDays.includes(days)} onChange={(event) => setExpiryReminderDays((current) => event.target.checked ? [...current, days].sort((a, b) => a - b) : current.filter((value) => value !== days))} />
              {t("contracts.daysBefore", { n: days })}
            </label>
          ))}
        </fieldset>
      </div>
      <ContractRegistryForm
        draft={registry}
        onChange={setRegistry}
        options={registryOptions.data}
        disabled={!editable}
        partyLabel={initial?.party ? `${initial.party.code} · ${initial.party.name}` : undefined}
        onManageGroups={registryOptions.data?.can_manage_groups ? () => setGroupManagerOpen(true) : undefined}
      />
      {groupManagerOpen && (
        <ContractGroupManager
          groups={registryOptions.data?.groups ?? []}
          onClose={() => setGroupManagerOpen(false)}
        />
      )}
      <label className="contract-editor-label">{t("contracts.composer.content")}</label>
      <RichContractEditor value={body} editable={editable} onChange={setBody} />
      <div className="contract-form-section">
        <div className="section-label">{t("contracts.composer.reviewers")}</div>
        <details className="reviewer-dropdown">
          <summary>
            {reviewers.length
              ? t("contracts.composer.reviewersCount", { n: reviewers.length })
              : t("contracts.composer.pickReviewers")}
          </summary>
          <div className="reviewer-picker">
            {reviewerOptions.map((candidate) => (
              <label key={candidate.account_id} className="reviewer-option">
                <input
                  type="checkbox"
                  checked={reviewers.includes(candidate.account_id)}
                  onChange={() =>
                    setReviewers((current) =>
                      current.includes(candidate.account_id)
                        ? current.filter((id) => id !== candidate.account_id)
                        : [...current, candidate.account_id],
                    )
                  }
                  disabled={!editable}
                />
                <span>
                  <strong>{candidate.name}</strong>
                  <small>{candidate.job_title || t("contracts.composer.employee")}</small>
                </span>
              </label>
            ))}
          </div>
        </details>
        <small className="field-help">
          {t("contracts.composer.reviewersHint")}
        </small>
      </div>
      <div className="contract-form-section">
        <div className="section-label">{t("contracts.composer.attachments")}</div>
        <div className="contract-upload-inline">
          <label
            className="contract-icon-button contract-icon-button-attachment"
            title={t("contracts.composer.attach")}
          >
            <Paperclip size={18} />
            <input
              aria-label={t("contracts.composer.attach")}
              type="file"
              hidden
              multiple
              accept=".pdf,.docx,image/jpeg,image/png,image/tiff"
              onChange={(event) => {
                addSupportingFiles(event.target.files);
                event.currentTarget.value = "";
              }}
              disabled={!editable || upload.isPending}
            />
          </label>
          <span>{t("contracts.composer.attachFormats")}</span>
        </div>
        <div className="contract-file-list">
          {initial?.files
            .filter((file) => file.purpose === "supporting")
            .map((file) => (
              <span key={file.id}>{file.filename}</span>
            ))}
          {supportingFiles.map((file, index) => (
            <span key={`${file.name}-${index}`}>{file.name}</span>
          ))}
        </div>
      </div>
      <footer className="contract-composer-actions">
        <button
          type="button"
          className="contract-icon-button contract-icon-button-danger"
          onClick={onCancel}
          aria-label={t("contracts.cancel")}
          title={t("contracts.cancel")}
        >
          <X size={19} />
        </button>
        <button
          type="button"
          className="contract-icon-button contract-icon-button-save"
          onClick={save}
          disabled={
            !editable ||
            create.isPending ||
            update.isPending ||
            upload.isPending
          }
          aria-label={t("contracts.composer.saveDraft")}
          title={t("contracts.composer.saveDraft")}
        >
          <Save size={19} />
        </button>
      </footer>
    </section>
  );
}

function ContractDetailView({
  detail,
  onBack,
}: {
  detail: ContractDetail;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const actor = useActor();
  const navigate = useNavigate();
  const submit = useSubmitContract();
  const resubmit = useResubmitContract();
  const recall = useRecallContract();
  const approve = useApproveContract();
  const changes = useRequestContractChanges();
  const reject = useRejectContract();
  const duplicate = useDuplicateContract();
  const confirmFinal = useConfirmContractFinal();
  const upload = useUploadContractFile();
  const print = useMarkContractPrinted();
  const addComment = useAddContractComment();
  const resolveComment = useResolveContractComment();
  const [editing, setEditing] = useState(false);
  const [remark, setRemark] = useState("");
  const [approvalExpiry, setApprovalExpiry] = useState(detail.effective_end_on ?? "");
  const [approvalReminderDays, setApprovalReminderDays] = useState<number[]>(detail.expiry_reminder_days ?? []);
  const [comment, setComment] = useState("");
  const [anchor, setAnchor] = useState<{
    from: number;
    to: number;
    quote: string;
  } | null>(null);
  const [approvedModal, setApprovedModal] = useState(false);
  const editable =
    detail.author_account_id === actor.data?.id &&
    (detail.status === "DRAFT" || detail.status === "CHANGES_REQUESTED");
  const myReview = detail.reviews.find(
    (row) =>
      row.round_number === detail.submission_round &&
      row.reviewer_account_id === actor.data?.id,
  );
  const canReview =
    detail.status === "PENDING_REVIEW" && myReview?.decision === "pending";
  const canExecute =
    detail.status === "APPROVED" &&
    (detail.author_account_id === actor.data?.id ||
      detail.reviews.some((row) => row.reviewer_account_id === actor.data?.id));
  useEffect(() => {
    if (
      new URLSearchParams(window.location.search).get("approved") === "1" &&
      detail.status === "APPROVED"
    )
      setApprovedModal(true);
  }, [detail.status]);
  if (editing)
    return (
      <ContractComposer
        initial={detail}
        onDone={(id) => {
          setEditing(false);
          navigate(`/contracts/${id}`);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  const run = (mutation: any, path = "") =>
    mutation.mutate(
      { publicId: detail.public_id, remark: remark.trim() || undefined },
      {
        onSuccess: () => {
          setRemark("");
          toast.success(path || t("contracts.done"));
        },
        onError: (error: any) =>
          toast.error(
            error.response?.data?.detail || t("contracts.failed"),
          ),
      },
    );
  const openPrint = () => {
    if (isNativePlatform()) {
      toast.error(t("contracts.detail.printWebOnly"));
      return;
    }
    print.mutate(detail.public_id);
    window.open(
      `/contracts/${detail.public_id}/print`,
      "_blank",
      "noopener,noreferrer",
    );
  };
  const finalFile = detail.files.find(
    (file) => file.purpose === "signed_final" && !file.confirmed_at,
  );
  return (
    <section className="contract-detail">
      <ContractSectionTabs active="drafts" />
      <div className="workspace-toolbar contract-detail-toolbar">
        <button className="back-link" onClick={onBack}>
          {t("contracts.detail.back")}
        </button>
        <span className={statusClass(detail.status)}>
          {statusLabels[detail.status]}
        </span>
      </div>
      <div className="contract-detail-layout">
        <article className="contract-document-card">
          <header className="contract-document-header">
            <div>
              <span className="eyebrow">
                {typeLabels[detail.document_type]} ·{" "}
                {detail.code || `ID ${detail.public_id.slice(0, 8).toUpperCase()}`}
                {detail.contract_number ? ` · №${detail.contract_number}` : ""}
              </span>
              <h2>{detail.title}</h2>
              <p>
                {t("contracts.detail.validity", { from: formatDate(detail.effective_start_on), to: formatDate(detail.effective_end_on) })}
                {detail.party ? ` · ${detail.party.name}` : ""}
              </p>
            </div>
            {editable && (
              <button
                className="button button-secondary"
                onClick={() => setEditing(true)}
              >
                {t("contracts.detail.edit")}
              </button>
            )}
          </header>
          {detail.status === "APPROVED" && (
            <div className="contract-approved-banner">
              <ShieldCheck size={21} />
              <div>
                <strong>{t("contracts.detail.approvedBanner")}</strong>
                <span>{t("contracts.detail.approvedSteps")}</span>
              </div>
            </div>
          )}
          <RichContractEditor
            value={
              (detail.status === "APPROVED" ||
                detail.status === "SIGNED_AND_STAMPED") &&
              detail.approved_body_json
                ? detail.approved_body_json
                : (detail.body_json ?? EMPTY_BODY)
            }
            editable={false}
            onSelection={setAnchor}
          />
          <div className="contract-document-footer">
            <span>{t("contracts.detail.published", { date: formatDate(detail.created_at) })}</span>
            <span>{t("contracts.detail.lastVersion", { n: detail.version })}</span>
          </div>
        </article>
        <aside className="contract-detail-rail">
          <ContractRegistryPanel
            key={`${detail.public_id}-${detail.version}`}
            detail={detail}
            canManage={
              detail.author_account_id === actor.data?.id ||
              Boolean(actor.data?.roles?.some((role) => role === "admin" || role === "legal_counsel"))
            }
          />
          <div className="contract-rail-card">
            <div className="section-label">{t("contracts.detail.actions")}</div>
            {detail.status === "DRAFT" && editable && (
              <button
                className="button button-primary button-wide"
                onClick={() => run(submit, t("contracts.detail.submitted"))}
              >
                <Send size={16} /> {t("contracts.detail.submit")}
              </button>
            )}
            {detail.status === "CHANGES_REQUESTED" && editable && (
              <button
                className="button button-primary button-wide"
                onClick={() => run(resubmit, t("contracts.detail.resubmitted"))}
              >
                <Send size={16} /> {t("contracts.detail.resubmit")}
              </button>
            )}
            {detail.status === "PENDING_REVIEW" &&
              editable &&
              detail.reviews.filter(
                (row) =>
                  row.round_number === detail.submission_round &&
                  row.decision !== "pending",
              ).length === 0 && (
                <button
                  className="button button-secondary button-wide"
                  onClick={() => run(recall, t("contracts.detail.recalled"))}
                >
                  {t("contracts.detail.recall")}
                </button>
              )}
            {detail.status === "REJECTED" && (
              <button
                className="button button-secondary button-wide"
                onClick={() =>
                  duplicate.mutate(detail.public_id, {
                    onSuccess: (value) =>
                      navigate(`/contracts/${value.public_id}`),
                  })
                }
              >
                {t("contracts.detail.duplicate")}
              </button>
            )}
            {canExecute && (
              <>
                <button
                  className="button button-primary button-wide"
                  onClick={openPrint}
                >
                  <Printer size={16} /> {t("contracts.detail.print")}
                </button>
                <div className="execution-card">
                  <strong>{t("contracts.detail.steps")}</strong>
                  <div className="execution-step done">
                    <b>1</b>
                    <span>{t("contracts.detail.step1")}</span>
                  </div>
                  <div className="execution-step">
                    <b>2</b>
                    <span>{t("contracts.detail.step2")}</span>
                  </div>
                  <div className="execution-step">
                    <b>3</b>
                    <label>
                      <Upload size={15} /> {t("contracts.detail.step3")}
                      <input
                        type="file"
                        hidden
                        accept=".pdf,image/jpeg,image/png,image/tiff"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file)
                            upload.mutate(
                              {
                                publicId: detail.public_id,
                                purpose: "signed_final",
                                file,
                              },
                              {
                                onSuccess: () =>
                                  toast.success(t("contracts.detail.finalAttached")),
                              },
                            );
                        }}
                      />
                    </label>
                  </div>
                  {finalFile && (
                    <button
                      className="button button-primary button-wide"
                      onClick={() =>
                        confirmFinal.mutate(detail.public_id, {
                          onSuccess: () => toast.success(t("contracts.detail.archived")),
                          onError: (error: any) =>
                            toast.error(
                              error.response?.data?.detail ||
                                t("contracts.detail.archiveFailed"),
                            ),
                        })
                      }
                    >
                      {t("contracts.detail.confirmFinal")}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
            {canReview && (
            <div className="contract-rail-card review-action-card">
              <div className="section-label">{t("contracts.detail.yourReview")}</div>
              <textarea
                value={remark}
                onChange={(event) => setRemark(event.target.value)}
                placeholder={t("contracts.detail.remarkPlaceholder")}
              />
              <label className="contract-approval-expiry">
                {t("contracts.detail.confirmExpiry")}
                <input type="date" value={approvalExpiry} onChange={(event) => setApprovalExpiry(event.target.value)} />
              </label>
              <fieldset className="contract-expiry-reminders" >
                <legend>{t("contracts.detail.reminderDays")}</legend>
                {[1, 3, 7, 14, 30, 60, 90].map((days) => (
                  <label key={days}>
                    <input type="checkbox" checked={approvalReminderDays.includes(days)} onChange={(event) => setApprovalReminderDays((current) => event.target.checked ? [...current, days].sort((a, b) => a - b) : current.filter((value) => value !== days))} />
                    {t("contracts.daysBefore", { n: days })}
                  </label>
                ))}
              </fieldset>
              <div className="review-actions">
                <button
                  className="button button-primary"
                  onClick={() => approvalExpiry ? approve.mutate({ publicId: detail.public_id, remark: remark.trim() || undefined, effective_end_on: approvalExpiry, expiry_reminder_days: approvalReminderDays }, { onSuccess: () => toast.success(t("contracts.detail.approvalRecorded")), onError: (error: any) => toast.error(error.response?.data?.detail || t("contracts.detail.approvalFailed")) }) : toast.error(t("contracts.detail.expiryRequired"))}
                >
                  {t("contracts.detail.approve")}
                </button>
                <button
                  className="button button-warning"
                  onClick={() =>
                    remark.trim()
                      ? run(changes, t("contracts.detail.changesSent"))
                      : toast.error(t("contracts.detail.changesRequired"))
                  }
                >
                  {t("contracts.detail.requestChanges")}
                </button>
                <button
                  className="button button-danger"
                  onClick={() =>
                    remark.trim()
                      ? run(reject, t("contracts.detail.rejected"))
                      : toast.error(t("contracts.detail.rejectRequired"))
                  }
                >
                  {t("contracts.detail.reject")}
                </button>
              </div>
            </div>
          )}
          <div className="contract-rail-card">
            <div className="section-label">{t("contracts.detail.reviewers")}</div>
            {detail.reviews
              .filter((row) => row.round_number === detail.submission_round)
              .map((row) => (
                <div className="review-row" key={row.id}>
                  <span className={`review-dot decision-${row.decision}`} />
                  <span>
                    <strong>{row.reviewer_name}</strong>
                    <small>
                      {t(`contracts.detail.decision.${row.decision}`)}
                    </small>
                  </span>
                </div>
              ))}
          </div>
          <div className="contract-rail-card">
            <div className="section-label">{t("contracts.detail.files")}</div>
            {detail.files.map((file) => (
              <button
                className="contract-file-row"
                key={file.id}
                onClick={async () => {
                  try {
                    requireWebCapability("File downloads");
                    const response = await api.get(
                      `/v1/contracts/${detail.public_id}/files/${file.id}/download`,
                      { responseType: "blob" },
                    );
                    const url = URL.createObjectURL(response.data);
                    const link = document.createElement("a");
                    link.href = url;
                    link.download = file.filename;
                    link.click();
                    URL.revokeObjectURL(url);
                  } catch (error: any) {
                    toast.error(error.message || t("contracts.detail.downloadFailed"));
                  }
                }}
              >
                <Paperclip size={15} />
                <span>{file.filename}</span>
              </button>
            ))}
          </div>
        </aside>
      </div>
      <section className="contract-comments-card">
        <div className="contract-section-heading">
          <div>
            <span className="eyebrow">{t("contracts.detail.commentsEyebrow")}</span>
            <h3>{t("contracts.detail.comments")}</h3>
          </div>
          <MessageSquare size={19} />
        </div>
        {detail.comments.map((item) => (
          <article
            key={item.id}
            className={
              item.is_resolved
                ? "contract-comment is-resolved"
                : "contract-comment"
            }
          >
            {item.anchor?.quote && (
              <blockquote>“{item.anchor.quote}”</blockquote>
            )}
            <p>{item.body}</p>
            <div className="contract-comment-footer">
              <small>{formatDate(item.created_at)}</small>
              {(detail.status === "PENDING_REVIEW" ||
                detail.status === "CHANGES_REQUESTED") && (
                <button
                  className="text-button"
                  onClick={() =>
                    resolveComment.mutate({
                      publicId: detail.public_id,
                      id: item.id,
                      is_resolved: !item.is_resolved,
                    })
                  }
                >
                  {item.is_resolved ? t("contracts.detail.reopen") : t("contracts.detail.resolved")}
                </button>
              )}
            </div>
          </article>
        ))}
        {(detail.status === "PENDING_REVIEW" ||
          detail.status === "CHANGES_REQUESTED") && (
          <div className="comment-composer">
            {anchor && <div className="comment-anchor">“{anchor.quote}”</div>}
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder={t("contracts.detail.commentPlaceholder")}
            />
            <button
              className="button button-secondary"
              disabled={!comment.trim()}
              onClick={() =>
                addComment.mutate(
                  {
                    publicId: detail.public_id,
                    revision_id: detail.current_revision_id || 0,
                    body: comment.trim(),
                    anchor,
                  },
                  {
                    onSuccess: () => {
                      setComment("");
                      setAnchor(null);
                    },
                  },
                )
              }
            >
              {t("contracts.detail.addComment")}
            </button>
          </div>
        )}
      </section>
      {approvedModal && createPortal(
        <div className="contract-modal-backdrop">
          <div className="contract-modal">
            <button
              className="icon-button"
              onClick={() => setApprovedModal(false)}
            >
              <X size={18} />
            </button>
            <ShieldCheck size={42} className="modal-success-icon" />
            <h3>{t("contracts.detail.approvedTitle")}</h3>
            <p>{t("contracts.detail.approvedText")}</p>
            <button
              className="button button-primary button-wide"
              onClick={() => {
                setApprovedModal(false);
                openPrint();
              }}
            >
              {t("contracts.detail.print")}
            </button>
          </div>
        </div>,
        document.body
      )}
    </section>
  );
}

export function ContractsWorkspacePage() {
  const { t } = useTranslation();
  const { publicId } = useParams<{ publicId?: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<ContractView>(
    (params.get("view") as ContractView) || "all",
  );
  const [createMode, setCreateMode] = useState(params.get("create") === "1");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState<"" | "true" | "false">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  const partyFilter = Number(params.get("party")) || undefined;
  const filters = useMemo(
    () => ({
      ...(debouncedSearch ? { search: debouncedSearch } : {}),
      ...(partyFilter ? { party_id: partyFilter } : {}),
      ...(groupFilter ? { group_id: Number(groupFilter) } : {}),
      ...(activeFilter ? { active: activeFilter === "true" } : {}),
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
    }),
    [debouncedSearch, partyFilter, groupFilter, activeFilter, dateFrom, dateTo],
  );
  // A CRM deep link (?party=) should show the counterparty's contracts in every status.
  const effectiveView: ContractView | "registry" = partyFilter && view === "all" ? "registry" : view;
  const list = useContractList(effectiveView, filters);
  const registryOptions = useContractRegistryOptions();
  const detail = useContractDetail(publicId);
  const partyName = list.data?.items.find((item) => item.party_id === partyFilter)?.party?.name;
  useEffect(() => {
    setCreateMode(params.get("create") === "1");
  }, [params]);
  if (publicId && detail.data)
    return (
      <ContractDetailView
        detail={detail.data}
        onBack={() => navigate("/contracts")}
      />
    );
  return (
    <section className="contracts-workspace">
      <ContractSectionTabs active="drafts" />
      <div className="workspace-toolbar contracts-toolbar">
        <div className="toolbar-start">
          <div className="contract-tabs" role="tablist">
            {VIEW_KEYS.map((key) => (
              <button
                key={key}
                role="tab"
                aria-selected={view === key}
                className={view === key ? "active" : ""}
                onClick={() => setView(key)}
              >
                {t(`contracts.view.${key}`)}
                <span>{list.data?.counts?.[key] ?? 0}</span>
              </button>
            ))}
          </div>
        </div>
        <CreateButton
          label={t("contracts.list.new")}
          onClick={() => {
            setCreateMode(true);
            setParams({ create: "1" });
          }}
        />
      </div>
      {createMode && (
        <ContractComposer
          onDone={(id) => {
            setCreateMode(false);
            setParams({});
            navigate(`/contracts/${id}`);
          }}
          onCancel={() => {
            setCreateMode(false);
            setParams({});
          }}
        />
      )}
      {!createMode && (
        <div className="contract-filters" role="search">
          <input
            type="search"
            aria-label={t("contracts.list.searchAria")}
            placeholder={t("contracts.list.searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <ContractGroupSelect
            aria-label={t("contracts.list.byGroup")}
            value={groupFilter}
            onChange={setGroupFilter}
            groups={registryOptions.data?.groups ?? []}
            emptyLabel={t("contracts.list.allGroups")}
            includeInactive
          />
          <select
            aria-label={t("contracts.list.byActive")}
            value={activeFilter}
            onChange={(event) => setActiveFilter(event.target.value as "" | "true" | "false")}
          >
            <option value="">{t("contracts.list.activeAny")}</option>
            <option value="true">{t("contracts.list.active")}</option>
            <option value="false">{t("contracts.list.inactive")}</option>
          </select>
          <input type="date" aria-label={t("contracts.list.dateFromAria")} title={t("contracts.list.dateFromTitle")} value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" aria-label={t("contracts.list.dateToAria")} title={t("contracts.list.dateToTitle")} value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
        </div>
      )}
      {!createMode && partyFilter && (
        <span className="contract-filter-chip">
          {t("contracts.list.party", { name: partyName || `#${partyFilter}` })}
          <button
            type="button"
            aria-label={t("contracts.list.clearParty")}
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("party");
              setParams(next);
            }}
          >
            <X size={13} />
          </button>
        </span>
      )}
      {!createMode && (
        <div className="contract-list-card">
          {list.isLoading ? (
            <div className="contract-empty">{t("contracts.list.loading")}</div>
          ) : list.data?.items.length ? (
            list.data.items.map((item) => (
              <button
                className={`contract-list-row${item.is_active === false ? " is-inactive" : ""}`}
                key={item.public_id}
                onClick={() => navigate(`/contracts/${item.public_id}`)}
              >
                <div className="contract-list-icon">
                  <FileSignature size={18} />
                </div>
                <div className="contract-list-main">
                  <strong>
                    {item.code ? `${item.code} · ` : ""}
                    {item.title}
                  </strong>
                  <span>
                    {[
                      typeLabels[item.document_type],
                      item.party?.name,
                      item.amount !== null && item.amount !== undefined
                        ? formatContractMoney(item.amount, item.currency)
                        : null,
                      item.overdue_days ? t("contracts.list.overdue", { n: item.overdue_days }) : null,
                      item.is_active === false ? t("contracts.list.inactive") : null,
                      item.excerpt || t("contracts.list.noExcerpt"),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
                <span className={statusClass(item.status)}>
                  {statusLabels[item.status]}
                </span>
                <time>{formatDate(item.updated_at)}</time>
              </button>
            ))
          ) : (
            <div className="contract-empty">
              <FileCheck2 size={32} />
              <h3>{t("contracts.list.empty")}</h3>
              <CreateButton
                label={t("contracts.list.new")}
                onClick={() => setCreateMode(true)}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function ContractPrintPage() {
  const { t } = useTranslation();
  const { publicId } = useParams<{ publicId: string }>();
  const detail = useContractDetail(publicId);
  const editorValue =
    detail.data?.approved_body_json || detail.data?.body_json || EMPTY_BODY;
  useEffect(() => {
    if (detail.data && !isNativePlatform()) window.setTimeout(() => window.print(), 350);
  }, [detail.data]);
  if (!detail.data)
    return (
      <div className="contract-print-loading">{t("contracts.print.preparing")}</div>
    );
  return (
    <main className="contract-print-page">
      <div className="contract-print-header">
        <div>
          <span className="eyebrow">{t("contracts.print.eyebrow")}</span>
          <h1>{detail.data.title}</h1>
          <p>
            {[
              typeLabels[detail.data.document_type],
              detail.data.code,
              detail.data.contract_number ? `№${detail.data.contract_number}` : null,
              detail.data.party?.name,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <ContractQrCode value={`${window.location.origin}/contracts/${detail.data.public_id}`} />
      </div>
      <RichContractEditor value={editorValue} editable={false} />
      <footer className="contract-print-footer">
        <span>{t("contracts.print.docId", { id: detail.data.public_id })}</span>
        <span>{t("contracts.print.approvedOn", { date: formatDate(detail.data.approved_at) })}</span>
        <span>{t("contracts.print.version", { n: detail.data.version })}</span>
        <span>{t("contracts.print.qrNote")}</span>
      </footer>
    </main>
  );
}
