import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { Timer } from "lucide-react";
import { Panel, SectionHeader } from "../Primitives";
import { fixed, pct } from "../../lib/format";
import {
  cellSummaryText,
  fractionText,
  fullTimeoutsText,
  intervalText,
  shortDigest,
} from "../../lib/benchmarkDisplay";
import type {
  BenchmarkRelease,
  ReleaseModel,
  ReleaseTaskPackEntry,
  ReleaseTaskResult,
} from "../../lib/benchmarkReleases";

type Selection = { taskId: string; modelId: string };
type Position = { row: number; col: number };

/** "1.0.1" or, when the task changed since the record, "1.0.1 → 1.0.2 (changed)". */
export function recordedVersionText(task: ReleaseTaskPackEntry): string {
  return task.version_changed_since_pre_phase0 && task.current_version
    ? `${task.task_version} → ${task.current_version} (changed)`
    : task.task_version;
}

function cellFor(
  model: ReleaseModel,
  taskId: string,
): ReleaseTaskResult | undefined {
  return model.tasks.find((result) => result.task_id === taskId);
}

function countText(result: ReleaseTaskResult | undefined): string {
  if (!result || !result.evidence) return "no evidence";
  if (result.passes === undefined || result.runs === undefined) return "—";
  return `${result.passes}/${result.runs}`;
}

function CellDetail({
  release,
  task,
  model,
  result,
}: {
  release: BenchmarkRelease;
  task: ReleaseTaskPackEntry;
  model: ReleaseModel;
  result: ReleaseTaskResult | undefined;
}) {
  const campaign = release.ranked;
  return (
    <dl className="kv cell-detail">
      <dt>task</dt>
      <dd>
        {task.task_id}{" "}
        {campaign ? task.task_version : recordedVersionText(task)}
        {task.task_digest && (
          <span className="detail-sub" title={task.task_digest}>
            digest {shortDigest(task.task_digest)}
          </span>
        )}
      </dd>
      <dt>model</dt>
      <dd>
        {model.display_name}{" "}
        <span className="detail-sub-inline">({model.id})</span>
      </dd>
      {!result || !result.evidence ? (
        <>
          <dt>result</dt>
          <dd>{result?.note ?? "no evidence for this cell"}</dd>
        </>
      ) : (
        <>
          <dt>passes / runs</dt>
          <dd>{fractionText(result.passes ?? 0, result.runs ?? 0)}</dd>
          {campaign && (
            <>
              <dt>pass rate</dt>
              <dd>
                {result.pass_rate !== undefined
                  ? pct(result.pass_rate, 1)
                  : "not recorded"}
              </dd>
              <dt>Wilson 95%</dt>
              <dd>
                {result.wilson_low !== undefined &&
                result.wilson_high !== undefined
                  ? intervalText(result.wilson_low, result.wilson_high)
                  : "not recorded"}
              </dd>
            </>
          )}
          <dt>timeouts</dt>
          <dd>
            {result.timeouts ?? "not recorded"}
            {result.request_timeout_hits !== undefined &&
              ` (${fullTimeoutsText(result.request_timeout_hits)})`}
          </dd>
          {!campaign && (
            <>
              <dt>voided</dt>
              <dd>{result.voided ?? "not recorded"}</dd>
            </>
          )}
          <dt>mean final score</dt>
          <dd>
            {result.mean_final_score !== undefined
              ? fixed(result.mean_final_score, 3)
              : campaign
                ? "not recorded"
                : "not included in this dataset"}
          </dd>
          <dt>evaluation id</dt>
          <dd>
            {result.evaluation_id ??
              (campaign
                ? "not recorded"
                : "not recorded (runs are not linked to evaluation jobs)")}
          </dd>
        </>
      )}
    </dl>
  );
}

function taskLabel(release: BenchmarkRelease, task: ReleaseTaskPackEntry) {
  return `${task.task_id} ${release.ranked ? task.task_version : recordedVersionText(task)}`;
}

/** Every task × model cell as passes/runs text. Cells are toggle buttons in
 * one roving tab stop (arrow keys move, Home/End go to the row's ends,
 * Enter/Space select, Escape closes); the selected cell's details open as a
 * row directly under its task. Heat comes from the served cell pass rate only;
 * a release without one gets no shading. */
export function TaskMatrix({ release }: { release: BenchmarkRelease }) {
  const [selected, setSelected] = useState<Selection | null>(null);
  const [active, setActive] = useState<Position>({ row: 0, col: 0 });
  const [visibleWidth, setVisibleWidth] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const detailId = `task-matrix-detail-${release.id}`;
  const headingId = "release-matrix-heading";
  const rows = release.task_pack.length;
  const cols = release.models.length;

  const selectedTask = selected
    ? release.task_pack.find((task) => task.task_id === selected.taskId)
    : undefined;
  const selectedModel = selected
    ? release.models.find((model) => model.id === selected.modelId)
    : undefined;
  const summary =
    selectedTask && selectedModel
      ? cellSummaryText(
          taskLabel(release, selectedTask),
          selectedModel.display_name,
          cellFor(selectedModel, selectedTask.task_id),
        )
      : "";

  // The inline detail is pinned to the visible strip of the scroller, so it
  // needs the scroller's visible width.
  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const measure = () => setVisibleWidth(element.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Bring a newly opened detail into view without moving focus off the cell.
  useEffect(() => {
    if (selected)
      detailRef.current?.scrollIntoView?.({
        block: "nearest",
        inline: "nearest",
      });
  }, [selected]);

  // Scroll the matrix so a focused cell sits clear of the sticky task column
  // and header row (scroll-padding alone does not cover every browser).
  const revealCell = (button: HTMLElement) => {
    const scroller = scrollRef.current;
    const cell = button.closest("td");
    if (!scroller || !cell) return;
    const box = scroller.getBoundingClientRect();
    const rect = cell.getBoundingClientRect();
    const sticky = cell.parentElement?.querySelector("th.sticky-col");
    // the sticky header cell, not <thead> (whose box scrolls away)
    const head = scroller.querySelector("thead th");
    const left = sticky ? sticky.getBoundingClientRect().right : box.left;
    const top = head ? head.getBoundingClientRect().bottom : box.top;
    const right = box.left + scroller.clientWidth;
    const bottom = box.top + scroller.clientHeight;
    if (rect.left < left) scroller.scrollLeft -= left - rect.left;
    else if (rect.right > right)
      scroller.scrollLeft += Math.min(rect.right - right, rect.left - left);
    if (rect.top < top) scroller.scrollTop -= top - rect.top;
    else if (rect.bottom > bottom) scroller.scrollTop += rect.bottom - bottom;
    button.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  const focusCell = (row: number, col: number) => {
    const next = {
      row: Math.max(0, Math.min(rows - 1, row)),
      col: Math.max(0, Math.min(cols - 1, col)),
    };
    setActive(next);
    const button = buttons.current.get(`${next.row}:${next.col}`);
    if (!button) return;
    button.focus({ preventScroll: true });
    revealCell(button);
  };

  const close = () => {
    setSelected(null);
    buttons.current.get(`${active.row}:${active.col}`)?.focus();
  };

  const onCellKey = (event: KeyboardEvent, row: number, col: number) => {
    const lastRow = rows - 1;
    const lastCol = cols - 1;
    switch (event.key) {
      case "ArrowRight":
        focusCell(row, col + 1);
        break;
      case "ArrowLeft":
        focusCell(row, col - 1);
        break;
      case "ArrowDown":
        focusCell(row + 1, col);
        break;
      case "ArrowUp":
        focusCell(row - 1, col);
        break;
      case "Home":
        focusCell(event.ctrlKey ? 0 : row, 0);
        break;
      case "End":
        focusCell(event.ctrlKey ? lastRow : row, lastCol);
        break;
      case "Escape":
        if (!selected) return;
        setSelected(null);
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  return (
    <Panel>
      <SectionHeader
        id={headingId}
        title="Task matrix"
        description={
          release.ranked
            ? `Passes out of runs for every task and model (${release.counts.repetitions} repetitions each), at the pinned task version. Shading follows the served cell pass rate; the numbers carry the result. Select a cell to show its details under that row; the arrow keys move between cells and Escape closes the details.`
            : `Passes out of runs for every task and model as recorded, at the task version each run used. Select a cell to show its details under that row; the arrow keys move between cells and Escape closes the details.`
        }
      />
      <div
        ref={scrollRef}
        className="table-scroll matrix-scroll"
        role="region"
        aria-labelledby={headingId}
        style={
          visibleWidth !== null
            ? ({ "--matrix-visible": `${visibleWidth}px` } as CSSProperties)
            : undefined
        }
      >
        <table className="data matrix task-matrix" aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col" className="sticky-col">
                task · version
              </th>
              {release.models.map((model) => (
                <th
                  scope="col"
                  key={model.id}
                  title={model.id}
                  aria-label={`${model.display_name} (${model.id})`}
                >
                  {model.display_name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {release.task_pack.map((task, row) => (
              <Fragment key={task.task_id}>
                <tr>
                  <th scope="row" className="sticky-col task-head">
                    <span className="mono">{task.task_id}</span>
                    <span className="sub-cell mono">
                      {release.ranked
                        ? task.task_version
                        : recordedVersionText(task)}
                    </span>
                  </th>
                  {release.models.map((model, col) => {
                    const result = cellFor(model, task.task_id);
                    const heat =
                      result?.evidence && result.pass_rate !== undefined
                        ? result.pass_rate
                        : null;
                    const isSelected =
                      selected?.taskId === task.task_id &&
                      selected.modelId === model.id;
                    const isActive = active.row === row && active.col === col;
                    const timeouts = result?.timeouts ?? 0;
                    return (
                      <td
                        key={model.id}
                        className={`cell task-cell ${heat !== null ? "matrix-heat" : ""}`}
                        style={
                          heat !== null
                            ? ({ "--heat": heat } as CSSProperties)
                            : undefined
                        }
                      >
                        <button
                          type="button"
                          ref={(element) => {
                            const key = `${row}:${col}`;
                            if (element) buttons.current.set(key, element);
                            else buttons.current.delete(key);
                          }}
                          className="matrix-cell-button"
                          tabIndex={isActive ? 0 : -1}
                          aria-pressed={isSelected}
                          aria-controls={isSelected ? detailId : undefined}
                          data-task={task.task_id}
                          data-model={model.id}
                          onFocus={(event) => {
                            if (!isActive) setActive({ row, col });
                            // Keyboard focus only: moving the content
                            // under a pointer mid-click would retarget it.
                            if (event.currentTarget.matches(":focus-visible"))
                              revealCell(event.currentTarget);
                          }}
                          onKeyDown={(event) => onCellKey(event, row, col)}
                          onClick={() => {
                            setActive({ row, col });
                            setSelected(
                              isSelected
                                ? null
                                : { taskId: task.task_id, modelId: model.id },
                            );
                          }}
                        >
                          <span className="sr-only">
                            {task.task_id}, {model.display_name}:{" "}
                          </span>
                          <span className="cell-count">
                            {countText(result)}
                          </span>
                          {result?.evidence && (
                            <span className="sr-only"> passed</span>
                          )}
                          {timeouts > 0 && (
                            <span className="cell-timeouts">
                              <Timer size={11} aria-hidden="true" />
                              {timeouts}
                              <span className="sr-only">
                                {" "}
                                timeout{timeouts === 1 ? "" : "s"}
                              </span>
                            </span>
                          )}
                        </button>
                      </td>
                    );
                  })}
                </tr>
                {selected?.taskId === task.task_id &&
                  selectedTask &&
                  selectedModel && (
                    <tr className="matrix-detail-row">
                      <td colSpan={cols + 1}>
                        <div
                          ref={detailRef}
                          id={detailId}
                          className="matrix-detail matrix-detail-inline"
                          role="region"
                          aria-label="Selected task result"
                          onKeyDown={(event) => {
                            if (event.key === "Escape") {
                              event.preventDefault();
                              close();
                            }
                          }}
                        >
                          <CellDetail
                            release={release}
                            task={selectedTask}
                            model={selectedModel}
                            result={cellFor(
                              selectedModel,
                              selectedTask.task_id,
                            )}
                          />
                          <button
                            type="button"
                            className="btn btn-small btn-secondary matrix-detail-close"
                            onClick={close}
                          >
                            Close details
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div
        className="sr-only matrix-live"
        aria-live="polite"
        aria-atomic="true"
      >
        {summary}
      </div>
      <p className="note muted matrix-legend">
        <Timer size={12} aria-hidden="true" /> n = runs in the cell classified
        as timeouts.
      </p>
    </Panel>
  );
}
