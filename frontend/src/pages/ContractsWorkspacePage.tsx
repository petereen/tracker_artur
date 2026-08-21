import { useEffect, useMemo, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Underline from "@tiptap/extension-underline";
import {
  Table,
  TableCell,
  TableHeader,
  TableRow,
} from "@tiptap/extension-table";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  FileCheck2,
  FilePlus2,
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
} from "../api/enterprise";
import { api } from "../api/client";

type ContractView =
  | "all"
  | "drafts"
  | "pending_my_approval"
  | "submitted_by_me"
  | "approved"
  | "signed"
  | "returned";
const EMPTY_BODY = { type: "doc", content: [{ type: "paragraph" }] };
const tabs: Array<{ key: ContractView; label: string }> = [
  { key: "all", label: "Бүгд" },
  { key: "drafts", label: "Ноорог" },
  { key: "pending_my_approval", label: "Хянагдаж буй" },
  { key: "submitted_by_me", label: "Илгээсэн" },
  { key: "approved", label: "Баталгаажсан" },
  { key: "signed", label: "Гарын үсэг зурсан" },
  { key: "returned", label: "Буцаагдсан" },
];
const typeLabels: Record<ContractDocumentType, string> = {
  contract: "Гэрээ",
  agreement: "Хэлэлцээр",
  official_letter: "Албан бичиг",
  other: "Бусад",
};
const statusLabels: Record<ContractStatus, string> = {
  DRAFT: "Ноорог",
  PENDING_REVIEW: "Хянагдаж байна",
  CHANGES_REQUESTED: "Засвар шаардлагатай",
  APPROVED: "Баталгаажсан",
  REJECTED: "Буцаагдсан",
  SIGNED_AND_STAMPED: "Гарын үсэг зурсан",
};

function formatDate(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("mn-MN", { dateStyle: "medium" }).format(
        new Date(value),
      )
    : "—";
}
function statusClass(status: ContractStatus) {
  return `contract-status status-${status.toLowerCase()}`;
}

function RichContractEditor({
  value,
  editable,
  onChange,
  onSelection,
}: {
  value: Record<string, unknown>;
  editable: boolean;
  onChange?: (value: Record<string, unknown>) => void;
  onSelection?: (
    anchor: { from: number; to: number; quote: string } | null,
  ) => void;
}) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3, 4] },
        link: false,
        underline: false,
      }),
      Link.configure({ openOnClick: false }),
      Underline,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: value,
    editable,
    onUpdate: ({ editor: instance }) =>
      onChange?.(instance.getJSON() as Record<string, unknown>),
    onSelectionUpdate: ({ editor: instance }) => {
      const { from, to } = instance.state.selection;
      onSelection?.(
        from === to
          ? null
          : { from, to, quote: instance.state.doc.textBetween(from, to, " ") },
      );
    },
  });
  useEffect(() => {
    if (editor) editor.setEditable(editable);
  }, [editable, editor]);
  useEffect(() => {
    if (!editor) return;
    const current = JSON.stringify(editor.getJSON());
    if (current !== JSON.stringify(value)) editor.commands.setContent(value);
  }, [editor, value]);
  if (!editor)
    return (
      <div className="contract-editor-loading">Редактор ачаалж байна…</div>
    );
  return (
    <div className={`contract-editor ${editable ? "" : "is-locked"}`}>
      {editable && (
        <div
          className="contract-editor-toolbar"
          role="toolbar"
          aria-label="Баримтын формат"
        >
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleBold().run()}
            className={editor.isActive("bold") ? "is-active" : ""}
          >
            B
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleItalic().run()}
            className={editor.isActive("italic") ? "is-active" : ""}
          >
            <em>I</em>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleUnderline().run()}
            className={editor.isActive("underline") ? "is-active" : ""}
          >
            <u>U</u>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleBulletList().run()}
          >
            • жагсаалт
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
          >
            1. жагсаалт
          </button>
          <button
            type="button"
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            Гарчиг
          </button>
          <button
            type="button"
            onClick={() =>
              editor
                .chain()
                .focus()
                .insertTable({ rows: 2, cols: 2, withHeaderRow: true })
                .run()
            }
          >
            Хүснэгт
          </button>
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  );
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
  const [supportingFiles, setSupportingFiles] = useState<File[]>([]);
  const editable =
    !initial ||
    initial.status === "DRAFT" ||
    initial.status === "CHANGES_REQUESTED";
  const tasks = useEnterpriseTasks(projectId ? Number(projectId) : undefined);
  const projectOptions = Array.isArray(projects.data) ? projects.data : [];
  const taskOptions = Array.isArray(tasks.data) ? tasks.data : [];
  const reviewerOptions = Array.isArray(candidates.data) ? candidates.data : [];
  const save = async () => {
    if (!title.trim()) return toast.error("Гарчиг оруулна уу");
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
          toast.error(`${failedUploads} хавсралтыг байршуулж чадсангүй`);
      }
      toast.success("Ноорог хадгалагдлаа");
      onDone(result.public_id);
    } catch (error: any) {
      toast.error(error.response?.data?.detail || "Ноорог хадгалсангүй");
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
            onSuccess: () => toast.success("Хавсралт нэмэгдлээ"),
            onError: (error: any) =>
              toast.error(error.response?.data?.detail || "Файл нэмэгдсэнгүй"),
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
            ГЭРЭЭ / {initial ? "ЗАСАХ" : "ШИНЭ НООРОГ"}
          </span>
          <h2>{initial ? "Баримтыг засах" : "Шинэ гэрээ, баримт бичиг"}</h2>
        </div>
        {onCancel && (
          <button
            type="button"
            className="contract-icon-button contract-icon-button-danger"
            onClick={onCancel}
            aria-label="Болих"
            title="Болих"
          >
            <X size={19} />
          </button>
        )}
      </header>
      {!editable && (
        <div className="contract-lock-note">
          <LockKeyhole size={16} /> Энэ хувилбар баталгаажсан тул засварлах
          боломжгүй.
        </div>
      )}
      <div className="contract-form-grid">
        <label>
          Гарчиг / сэдэв
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={!editable}
            placeholder="Жишээ: Үйлчилгээ үзүүлэх гэрээ"
          />
        </label>
        <label>
          Баримтын төрөл
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
          Төсөл (сонголтоор)
          <select
            value={projectId}
            onChange={(event) => {
              setProjectId(event.target.value);
              setTaskId("");
            }}
            disabled={!editable}
          >
            <option value="">Төсөл сонгохгүй</option>
            {projectOptions.map((project) => (
              <option key={project.id} value={project.id}>
                {project.code} · {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Даалгавар (сонголтоор)
          <select
            value={taskId}
            onChange={(event) => setTaskId(event.target.value)}
            disabled={!editable || !projectId}
          >
            <option value="">Даалгавар сонгохгүй</option>
            {taskOptions.map((task) => (
              <option key={task.id} value={task.id}>
                {task.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Хүчин төгөлдөр эхлэх огноо
          <input
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            disabled={!editable}
          />
        </label>
        <label>
          Хүчин төгөлдөр дуусах огноо
          <input
            type="date"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            disabled={!editable}
          />
        </label>
      </div>
      <label className="contract-editor-label">Агуулга / нөхцөл</label>
      <RichContractEditor value={body} editable={editable} onChange={setBody} />
      <div className="contract-form-section">
        <div className="section-label">Хянагч, ахлагч сонгох</div>
        <details className="reviewer-dropdown">
          <summary>
            {reviewers.length
              ? `${reviewers.length} хянагч сонгосон`
              : "Хянагч сонгох"}
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
                  <small>{candidate.job_title || "Ажилтан"}</small>
                </span>
              </label>
            ))}
          </div>
        </details>
        <small className="field-help">
          Сонгосон бүх хянагч баталсны дараа баримт баталгаажна.
        </small>
      </div>
      <div className="contract-form-section">
        <div className="section-label">Хавсралт</div>
        <div className="contract-upload-inline">
          <label
            className="contract-icon-button contract-icon-button-attachment"
            title="Файл хавсаргах"
          >
            <Paperclip size={18} />
            <input
              aria-label="Файл хавсаргах"
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
          <span>PDF, DOCX, зураг</span>
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
          aria-label="Болих"
          title="Болих"
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
          aria-label="Ноорог хадгалах"
          title="Ноорог хадгалах"
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
          toast.success(path || "Үйлдэл амжилттай");
        },
        onError: (error: any) =>
          toast.error(
            error.response?.data?.detail || "Үйлдэл амжилтгүй боллоо",
          ),
      },
    );
  const openPrint = () => {
    if (isNativePlatform()) {
      toast.error("Хэвлэх үйлдлийг одоогоор вэб хувилбараас ашиглана уу");
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
      <div className="workspace-toolbar contract-detail-toolbar">
        <button className="back-link" onClick={onBack}>
          ← Гэрээний жагсаалт
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
                {typeLabels[detail.document_type]} · ID{" "}
                {detail.public_id.slice(0, 8).toUpperCase()}
              </span>
              <h2>{detail.title}</h2>
              <p>
                Хүчинтэй хугацаа: {formatDate(detail.effective_start_on)} —{" "}
                {formatDate(detail.effective_end_on)}
              </p>
            </div>
            {editable && (
              <button
                className="button button-secondary"
                onClick={() => setEditing(true)}
              >
                Засах
              </button>
            )}
          </header>
          {detail.status === "APPROVED" && (
            <div className="contract-approved-banner">
              <ShieldCheck size={21} />
              <div>
                <strong>Гэрээ батлагдлаа.</strong>
                <span>
                  Хэвлэх → гарын үсэг зурах → тамга дарах → эцсийн хувийг
                  хавсаргах.
                </span>
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
            <span>Нийтэлсэн: {formatDate(detail.created_at)}</span>
            <span>Сүүлийн хувилбар: v{detail.version}</span>
          </div>
        </article>
        <aside className="contract-detail-rail">
          <div className="contract-rail-card">
            <div className="section-label">Үйлдэл</div>
            {detail.status === "DRAFT" && editable && (
              <button
                className="button button-primary button-wide"
                onClick={() => run(submit, "Хянагчдад илгээгдлээ")}
              >
                <Send size={16} /> Хянагчдад илгээх
              </button>
            )}
            {detail.status === "CHANGES_REQUESTED" && editable && (
              <button
                className="button button-primary button-wide"
                onClick={() => run(resubmit, "Дахин илгээгдлээ")}
              >
                <Send size={16} /> Дахин илгээх
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
                  onClick={() => run(recall, "Илгээлт буцаагдлаа")}
                >
                  Буцаах
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
                Ноорог болгон хувилах
              </button>
            )}
            {canExecute && (
              <>
                <button
                  className="button button-primary button-wide"
                  onClick={openPrint}
                >
                  <Printer size={16} /> Хэвлэх / PDF татах
                </button>
                <div className="execution-card">
                  <strong>Гүйцэтгэлийн алхмууд</strong>
                  <div className="execution-step done">
                    <b>1</b>
                    <span>Хэвлэх</span>
                  </div>
                  <div className="execution-step">
                    <b>2</b>
                    <span>Талууд гарын үсэг зурж, тамга дарна</span>
                  </div>
                  <div className="execution-step">
                    <b>3</b>
                    <label>
                      <Upload size={15} /> Тамгатай, гарын үсэгтэй эцсийн хувийг
                      хуулах
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
                                  toast.success("Эцсийн хувилбар хавсаргалаа"),
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
                          onSuccess: () => toast.success("Гэрээ архивлагдлаа"),
                          onError: (error: any) =>
                            toast.error(
                              error.response?.data?.detail ||
                                "Архивлаж чадсангүй",
                            ),
                        })
                      }
                    >
                      Эцсийн хувийг баталгаажуулах
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
          {canReview && (
            <div className="contract-rail-card review-action-card">
              <div className="section-label">Таны хяналт</div>
              <textarea
                value={remark}
                onChange={(event) => setRemark(event.target.value)}
                placeholder="Тайлбар / санал (засвар, буцаалтад заавал)"
              />
              <div className="review-actions">
                <button
                  className="button button-primary"
                  onClick={() => run(approve, "Зөвшөөрөл бүртгэгдлээ")}
                >
                  Зөвшөөрөх
                </button>
                <button
                  className="button button-warning"
                  onClick={() =>
                    remark.trim()
                      ? run(changes, "Засварын санал илгээгдлээ")
                      : toast.error("Засварын тайлбар оруулна уу")
                  }
                >
                  Засвар хүсэх
                </button>
                <button
                  className="button button-danger"
                  onClick={() =>
                    remark.trim()
                      ? run(reject, "Баримт буцаагдлаа")
                      : toast.error("Буцаалтын шалтгаан оруулна уу")
                  }
                >
                  Буцаах
                </button>
              </div>
            </div>
          )}
          <div className="contract-rail-card">
            <div className="section-label">Хянагчид</div>
            {detail.reviews
              .filter((row) => row.round_number === detail.submission_round)
              .map((row) => (
                <div className="review-row" key={row.id}>
                  <span className={`review-dot decision-${row.decision}`} />
                  <span>
                    <strong>{row.reviewer_name}</strong>
                    <small>
                      {row.decision === "pending"
                        ? "Хүлээж байна"
                        : row.decision === "approved"
                          ? "Зөвшөөрсөн"
                          : row.decision === "changes_requested"
                            ? "Засвар хүссэн"
                            : "Буцаасан"}
                    </small>
                  </span>
                </div>
              ))}
          </div>
          <div className="contract-rail-card">
            <div className="section-label">Хавсралтууд</div>
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
                    toast.error(error.message || "Файл татаж чадсангүй");
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
            <span className="eyebrow">INLINE REVIEW</span>
            <h3>Санал, тайлбар</h3>
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
                  {item.is_resolved ? "Дахин нээх" : "Шийдсэн"}
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
              placeholder="Сонгосон хэсэгт тайлбар үлдээх…"
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
              Сэтгэгдэл нэмэх
            </button>
          </div>
        )}
      </section>
      {approvedModal && (
        <div className="contract-modal-backdrop">
          <div className="contract-modal">
            <button
              className="icon-button"
              onClick={() => setApprovedModal(false)}
            >
              <X size={18} />
            </button>
            <ShieldCheck size={42} className="modal-success-icon" />
            <h3>Гэрээ батлагдлаа</h3>
            <p>
              Хэвлэж, гарын үсэг зурж, тамга дараад эцсийн хувийг системд
              хавсаргана уу.
            </p>
            <button
              className="button button-primary button-wide"
              onClick={() => {
                setApprovedModal(false);
                openPrint();
              }}
            >
              Хэвлэх / PDF татах
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export function ContractsWorkspacePage() {
  const { publicId } = useParams<{ publicId?: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<ContractView>(
    (params.get("view") as ContractView) || "all",
  );
  const [createMode, setCreateMode] = useState(params.get("create") === "1");
  const list = useContractList(view);
  const detail = useContractDetail(publicId);
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
      <div className="workspace-toolbar contracts-toolbar">
        <div className="toolbar-start">
          <div className="contract-tabs" role="tablist">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={view === tab.key}
                className={view === tab.key ? "active" : ""}
                onClick={() => setView(tab.key)}
              >
                {tab.label}
                <span>{list.data?.counts?.[tab.key] ?? 0}</span>
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          className="contract-icon-button contract-new-document-button"
          onClick={() => {
            setCreateMode(true);
            setParams({ create: "1" });
          }}
          aria-label="Шинэ баримт бичиг"
          title="Шинэ баримт бичиг"
        >
          <FilePlus2 size={19} />
        </button>
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
        <div className="contract-list-card">
          {list.isLoading ? (
            <div className="contract-empty">Гэрээнүүдийг ачаалж байна…</div>
          ) : list.data?.items.length ? (
            list.data.items.map((item) => (
              <button
                className="contract-list-row"
                key={item.public_id}
                onClick={() => navigate(`/contracts/${item.public_id}`)}
              >
                <div className="contract-list-icon">
                  <FileSignature size={18} />
                </div>
                <div className="contract-list-main">
                  <strong>{item.title}</strong>
                  <span>
                    {typeLabels[item.document_type]} ·{" "}
                    {item.excerpt || "Агуулгагүй"}
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
              <h3>Одоогоор ямар нэг үүсгэсэн баримт бичиг алга</h3>
              <button
                type="button"
                className="contract-icon-button contract-new-document-button"
                onClick={() => setCreateMode(true)}
                aria-label="Шинэ баримт бичиг"
                title="Шинэ баримт бичиг"
              >
                <FilePlus2 size={19} />
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function ContractPrintPage() {
  const { publicId } = useParams<{ publicId: string }>();
  const detail = useContractDetail(publicId);
  const editorValue =
    detail.data?.approved_body_json || detail.data?.body_json || EMPTY_BODY;
  useEffect(() => {
    if (detail.data && !isNativePlatform()) window.setTimeout(() => window.print(), 350);
  }, [detail.data]);
  if (!detail.data)
    return (
      <div className="contract-print-loading">Баримтыг бэлтгэж байна…</div>
    );
  return (
    <main className="contract-print-page">
      <div className="contract-print-header">
        <div>
          <span className="eyebrow">OYUNS / ГЭРЭЭ</span>
          <h1>{detail.data.title}</h1>
          <p>
            {typeLabels[detail.data.document_type]} · {detail.data.public_id}
          </p>
        </div>
        <QRCodeSVG
          value={`${window.location.origin}/contracts/${detail.data.public_id}`}
          size={92}
        />
      </div>
      <RichContractEditor value={editorValue} editable={false} />
      <footer className="contract-print-footer">
        <span>Баримтын ID: {detail.data.public_id}</span>
        <span>Баталсан: {formatDate(detail.data.approved_at)}</span>
        <span>Хувилбар: v{detail.data.version}</span>
        <span>Эцсийн хувийн QR нь нэвтэрсэн хэрэглэгчдэд харагдана.</span>
      </footer>
    </main>
  );
}
