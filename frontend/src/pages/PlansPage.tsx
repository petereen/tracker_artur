import { useMemo, useState } from "react";
import {
  Badge,
  Btn,
  Card,
  Input,
  Modal,
  Select,
} from "../components/ui";
import {
  CompanyPlanItem,
  PlanHorizon,
  useCompanyPlan,
  useCreatePlanIdea,
  useDeleteCompanyPlanItem,
  useDeletePlanIdea,
  useMergePlanIdeas,
  usePlanIdeas,
  useReorderCompanyPlan,
  useUpdateCompanyPlanItem,
  useUpdatePlanIdea,
} from "../api/hooks";
import { EMPTY_ROLES, useAuthStore } from "../store/auth";

const HORIZONS: {
  id: PlanHorizon;
  label: string;
  color: "yellow" | "blue" | "green";
}[] = [
  { id: "long_term", label: "Урт хугацааны", color: "yellow" },
  { id: "mid_term", label: "Дунд хугацааны", color: "blue" },
  { id: "short_term", label: "Богино хугацааны", color: "green" },
];
const currentMonth = () => new Date().toISOString().slice(0, 7);
const monthDate = (value: string) => `${value}-01`;

export function PlansPage() {
  const [tab, setTab] = useState<"ideas" | "company">("ideas");
  const [month, setMonth] = useState(currentMonth);
  const [selected, setSelected] = useState<number[]>([]);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const roles = useAuthStore((state) => state.actor?.roles ?? EMPTY_ROLES);
  const canReview = roles.some((role) =>
    ["admin", "manager", "team_lead"].includes(role),
  );
  const ideas = usePlanIdeas(monthDate(month));
  const companyPlan = useCompanyPlan(monthDate(month));
  const reorder = useReorderCompanyPlan();
  const updateIdea = useUpdatePlanIdea();
  const deleteIdea = useDeletePlanIdea();
  const updateItem = useUpdateCompanyPlanItem();
  const deleteItem = useDeleteCompanyPlanItem();
  const columns = useMemo(
    () =>
      HORIZONS.reduce(
        (result, horizon) => ({
          ...result,
          [horizon.id]: (companyPlan.data || [])
            .filter((item) => item.horizon === horizon.id)
            .sort((a, b) => a.position - b.position),
        }),
        {} as Record<PlanHorizon, CompanyPlanItem[]>,
      ),
    [companyPlan.data],
  );
  const pending = (ideas.data || []).filter(
    (idea) => idea.status === "pending",
  );
  const moveItem = (target: PlanHorizon, targetIndex?: number) => {
    if (draggedId === null || !companyPlan.data) return;
    const all = HORIZONS.reduce(
      (result, horizon) => ({
        ...result,
        [horizon.id]: [...columns[horizon.id]],
      }),
      {} as Record<PlanHorizon, CompanyPlanItem[]>,
    );
    let moved: CompanyPlanItem | undefined;
    for (const horizon of HORIZONS) {
      const index = all[horizon.id].findIndex((item) => item.id === draggedId);
      if (index >= 0) moved = all[horizon.id].splice(index, 1)[0];
    }
    if (!moved) return;
    all[target].splice(targetIndex ?? all[target].length, 0, moved);
    reorder.mutate({
      plan_month: monthDate(month),
      columns: HORIZONS.reduce(
        (result, horizon) => ({
          ...result,
          [horizon.id]: all[horizon.id].map((item) => item.id),
        }),
        {} as Record<PlanHorizon, number[]>,
      ),
    });
    setDraggedId(null);
  };
  const editPlan = (item: CompanyPlanItem) => {
    const title = window.prompt("Төлөвлөгөөний гарчиг", item.title);
    if (title?.trim()) updateItem.mutate({ id: item.id, title: title.trim() });
  };

  return (
    <div className="plans-workspace">
      <div className="workspace-toolbar plan-toolbar">
        <div className="segmented-control">
          <button
            onClick={() => setTab("ideas")}
            className={tab === "ideas" ? "active" : ""}
          >
            Санал, санаа
          </button>
          <button
            onClick={() => setTab("company")}
            className={tab === "company" ? "active" : ""}
          >
            Компаний төлөвлөгөө
          </button>
        </div>
        <input
          type="month"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
        />
      </div>
      {tab === "ideas" && (
        <>
          <IdeaComposer month={monthDate(month)} />
          <Card className="plan-idea-list">
            {canReview && selected.length > 1 && (
              <div className="plan-selection">
                <strong>{selected.length} санаа сонгосон</strong>
                <Btn variant="primary" onClick={() => setMergeOpen(true)}>
                  Нэгтгэх
                </Btn>
              </div>
            )}
            {(ideas.data || []).map((idea) => (
              <article key={idea.id} className={`plan-idea ${idea.status}`}>
                {canReview && idea.status === "pending" && (
                  <input
                    aria-label={`${idea.title} сонгох`}
                    type="checkbox"
                    checked={selected.includes(idea.id)}
                    onChange={() =>
                      setSelected((ids) =>
                        ids.includes(idea.id)
                          ? ids.filter((id) => id !== idea.id)
                          : [...ids, idea.id],
                      )
                    }
                  />
                )}
                <div>
                  <div className="plan-idea-meta">
                    <strong>{idea.title}</strong>
                    <Badge
                      color={
                        idea.status === "pending"
                          ? "blue"
                          : idea.status === "merged"
                            ? "purple"
                            : "green"
                      }
                    >
                      {idea.status}
                    </Badge>
                  </div>
                  <p>{idea.content || "Дэлгэрэнгүйгүй"}</p>
                  <small>
                    {idea.submitted_by_name || "Гишүүн"}
                    {idea.suggested_due_date
                      ? ` · санал болгосон хугацаа ${idea.suggested_due_date}`
                      : ""}
                  </small>
                </div>
                {canReview && idea.status === "pending" && (
                  <div className="plan-actions">
                    <Btn
                      onClick={() => {
                        const title = window.prompt(
                          "Санааны гарчиг",
                          idea.title,
                        );
                        if (title?.trim())
                          updateIdea.mutate({
                            id: idea.id,
                            title: title.trim(),
                          });
                      }}
                    >
                      Засах
                    </Btn>
                    <Btn
                      variant="primary"
                      onClick={() => {
                        setSelected([idea.id]);
                        setMergeOpen(true);
                      }}
                    >
                      Батлах
                    </Btn>
                    <Btn
                      variant="danger"
                      onClick={() => deleteIdea.mutate(idea.id)}
                    >
                      Устгах
                    </Btn>
                  </div>
                )}
              </article>
            ))}
            {!ideas.isLoading && !ideas.data?.length && (
              <div className="empty-state">
                <h3>Энэ сарын санаа алга</h3>
                <p>Багийн гишүүд эндээс төлөвлөгөөний саналаа илгээнэ.</p>
              </div>
            )}
          </Card>
        </>
      )}
      {tab === "company" && (
        <div className="plan-board">
          {HORIZONS.map((horizon) => (
            <section
              key={horizon.id}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => moveItem(horizon.id)}
            >
              <header>
                <Badge color={horizon.color}>{horizon.label}</Badge>
                <span>{columns[horizon.id].length}</span>
              </header>
              {columns[horizon.id].map((item, index) => (
                <article
                  key={item.id}
                  draggable={canReview}
                  onDragStart={() => setDraggedId(item.id)}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.stopPropagation();
                    moveItem(horizon.id, index);
                  }}
                >
                  <strong>{item.title}</strong>
                  {item.content && <p>{item.content}</p>}
                  <small>
                    {item.due_date ? `Хугацаа ${item.due_date}` : "Хугацаагүй"}
                    {item.source_idea_ids.length
                      ? ` · ${item.source_idea_ids.length} санааг нэгтгэсэн`
                      : ""}
                  </small>
                  {canReview && (
                    <div className="plan-actions">
                      <Btn onClick={() => editPlan(item)}>Засах</Btn>
                      <Btn
                        variant="danger"
                        onClick={() =>
                          window.confirm(
                            "Төлөвлөгөөний зүйлийг архивлах уу?",
                          ) && deleteItem.mutate(item.id)
                        }
                      >
                        Устгах
                      </Btn>
                    </div>
                  )}
                </article>
              ))}
            </section>
          ))}
        </div>
      )}
      {mergeOpen && (
        <MergeIdeasModal
          ids={selected}
          month={monthDate(month)}
          defaultContent={pending
            .filter((idea) => selected.includes(idea.id))
            .map((idea) => `${idea.title}\n${idea.content || ""}`)
            .join("\n\n")}
          onClose={() => {
            setMergeOpen(false);
            setSelected([]);
          }}
        />
      )}
    </div>
  );
}

function IdeaComposer({ month }: { month: string }) {
  const create = useCreatePlanIdea();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [due, setDue] = useState("");
  return (
    <form
      className="plan-composer panel"
      onSubmit={async (event) => {
        event.preventDefault();
        await create.mutateAsync({
          plan_month: month,
          title,
          content,
          suggested_due_date: due || null,
        });
        setTitle("");
        setContent("");
        setDue("");
      }}
    >
      <Input
        label="Дараа сарын төлөвлөгөө"
        value={title}
        onChange={setTitle}
        placeholder="Төлөвлөгөөний товч гарчиг"
        fullWidth
      />
      <Input
        label="Тайлбар"
        value={content}
        onChange={setContent}
        placeholder="Ямар үр дүнд, ямар арга замаар хүрэх вэ?"
        fullWidth
      />
      <label>
        Төлөвлөсөн хугацаа
        <input
          type="date"
          value={due}
          onChange={(event) => setDue(event.target.value)}
        />
      </label>
      <Btn
        type="submit"
        variant="primary"
        size="sm"
        disabled={!title.trim() || create.isPending}
      >
        Төлөвлөгөө нэмэх
      </Btn>
    </form>
  );
}

function MergeIdeasModal({
  ids,
  month,
  defaultContent,
  onClose,
}: {
  ids: number[];
  month: string;
  defaultContent: string;
  onClose: () => void;
}) {
  const merge = useMergePlanIdeas();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState(defaultContent);
  const [due, setDue] = useState("");
  const [horizon, setHorizon] = useState<PlanHorizon>("short_term");
  return (
    <Modal
      title={ids.length > 1 ? "Санаануудыг нэгтгэх" : "Санааг батлах"}
      onClose={onClose}
      className="max-w-2xl"
    >
      <div className="plan-merge-form">
        <Input
          label="Нэгдсэн төлөвлөгөө"
          value={title}
          onChange={setTitle}
          fullWidth
        />
        <textarea
          rows={7}
          value={content}
          onChange={(event) => setContent(event.target.value)}
        />
        <label>
          Дуусах хугацаа
          <input
            type="date"
            value={due}
            onChange={(event) => setDue(event.target.value)}
          />
        </label>
        <Select
          label="Хугацааны түвшин"
          value={horizon}
          onChange={(value) => setHorizon(value as PlanHorizon)}
          options={HORIZONS.map((item) => ({
            value: item.id,
            label: item.label,
          }))}
          fullWidth
        />
        <Btn
          variant="primary"
          size="lg"
          disabled={!title.trim() || merge.isPending}
          onClick={async () => {
            await merge.mutateAsync({
              idea_ids: ids,
              plan_month: month,
              title: title.trim(),
              content,
              horizon,
              due_date: due || null,
            });
            onClose();
          }}
        >
          Төлөвлөгөөнд оруулах
        </Btn>
      </div>
    </Modal>
  );
}
