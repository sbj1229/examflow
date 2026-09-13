const $ = (id) => document.getElementById(id);
const states = {
  queued: "요청 접수",
  checking: "준비 확인 중",
  scheduling: "일정 조정 중",
  needs_input: "추가 확인 필요",
  no_slots: "가능한 시간 없음",
  awaiting_approval: "담당자 승인 대기",
  confirming: "예약 확정 중",
  confirmation_unknown: "확정 결과 재확인 필요",
  confirmed: "데모 예약 완료",
  conflict: "예약 충돌",
  failed: "처리 실패",
  cancelled: "요청 취소",
};
const terminals = new Set([
  "needs_input",
  "no_slots",
  "awaiting_approval",
  "confirmation_unknown",
  "confirmed",
  "conflict",
  "failed",
  "cancelled",
]);
let current = null,
  timer = null,
  renderedCount = 0,
  generation = 0,
  changing = false;
function syncControls() {
  $("submit").disabled =
    changing || !!(current && !terminals.has(current.state));
  $("approve").disabled = changing;
  $("cancel").disabled = changing;
}
function text(tag, value, className) {
  const el = document.createElement(tag);
  el.textContent = value;
  if (className) el.className = className;
  return el;
}
async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "요청을 처리하지 못했습니다. 입력과 연결을 확인하세요.",
    );
  return data;
}
function error(err) {
  $("error").textContent = err.message;
}
function render(run) {
  current = run;
  $("status").textContent = states[run.state] || run.state;
  syncControls();
  $("approve").hidden = !["awaiting_approval", "confirmation_unknown"].includes(
    run.state,
  );
  $("approve").textContent =
    run.state === "confirmation_unknown"
      ? "확정 결과 재확인"
      : "이 시간으로 데모 예약 확정";
  $("cancel").hidden = ![
    "queued",
    "checking",
    "scheduling",
    "awaiting_approval",
  ].includes(run.state);
  $("download").disabled = false;
  for (const [step, active, done] of [
    ["readiness", ["checking"], !!run.readiness],
    ["scheduling", ["scheduling"], !!run.schedule],
    [
      "approval",
      ["confirming", "awaiting_approval"],
      run.state === "confirmed",
    ],
  ])
    $("step-" + step).className = done
      ? "done"
      : active.includes(run.state)
        ? "active"
        : "";
  const r = $("result");
  r.replaceChildren();
  if (run.state === "checking" || run.state === "queued") {
    r.append(
      text("h3", "의뢰와 행정 접수 규칙을 확인하고 있습니다."),
      text("p", "확인된 근거는 아래 실행 기록에 표시됩니다.", "summary"),
    );
  }
  if (run.readiness) {
    r.append(
      text("h3", run.readiness.order.alias + " · " + run.readiness.order.exam),
      text("p", run.readiness.decision.explanation, "summary"),
    );
    if (run.readiness.missing_labels.length) {
      const list = document.createElement("ul");
      for (const label of run.readiness.missing_labels)
        list.append(text("li", label + " 필요"));
      r.append(
        list,
        text(
          "p",
          "담당자가 원본 접수 정보를 보완한 뒤 다시 요청해야 합니다. 데모에서는 준비 완료 사례를 선택해 다음 단계를 볼 수 있습니다.",
          "hint",
        ),
      );
    }
    r.append(
      text("p", "확인 근거 · " + run.readiness.sources.join(" / "), "source"),
    );
  }
  if (run.state === "scheduling")
    r.append(
      text(
        "p",
        "가능한 시간을 조회하고 요청 조건과 대조하고 있습니다.",
        "summary",
      ),
    );
  if (run.schedule) {
    r.append(text("p", run.schedule.decision.explanation, "summary"));
    const slot = run.schedule.selected;
    if (slot) {
      const b = text("div", "", "booking"),
        left = text("div", "");
      left.append(
        text(
          "span",
          run.state === "confirmed"
            ? "데모 예약 확정"
            : "제안 시간 · 아직 확정되지 않음",
          "booking-label",
        ),
        text("div", slot.time, "booking-time"),
      );
      const right = text("div", "");
      right.append(
        text("strong", slot.room),
        text(
          "p",
          slot.day + " · " + (slot.period === "afternoon" ? "오후" : "오전"),
        ),
      );
      b.append(left, right);
      r.append(b);
    }
  }
  if (run.reservation) {
    r.append(
      text(
        "p",
        run.state === "confirmed"
          ? "합성 데이터에 예약을 기록했습니다. 실제 병원 예약이나 연락은 발생하지 않습니다."
          : run.reservation.reason,
        "summary",
      ),
    );
  }
  if (run.error) r.append(text("p", run.error, "summary"));
  if (run.state === "cancelled")
    r.append(
      text(
        "p",
        "요청을 취소했습니다. 진행 중인 조회는 종료될 수 있으나 이후 단계와 예약 확정은 진행하지 않습니다.",
        "summary",
      ),
    );
  const trace = $("trace");
  if (renderedCount === 0) trace.replaceChildren();
  for (const e of run.events.slice(renderedCount)) {
    const d = document.createElement("details"),
      s = document.createElement("summary");
    s.append(
      text("span", (e.at_ms / 1000).toFixed(2) + "s", "trace-time"),
      text("span", e.kind, "trace-kind"),
      text("span", e.label),
      text("span", e.agent, "trace-agent"),
    );
    d.append(s, text("pre", JSON.stringify(e.data, null, 2)));
    trace.append(d);
  }
  renderedCount = run.events.length;
}
async function poll() {
  if (!current) return;
  const expectedGeneration = generation,
    runId = current.id;
  try {
    const run = await api("/api/runs/" + runId);
    if (expectedGeneration !== generation || current?.id !== runId) return;
    render(run);
    if (!terminals.has(current.state)) timer = setTimeout(poll, 700);
  } catch (err) {
    if (expectedGeneration !== generation || current?.id !== runId) return;
    error(err);
    $("submit").disabled = false;
    $("cancel").hidden = true;
  }
}
$("request-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (changing || $("submit").disabled) return;
  generation++;
  changing = true;
  clearTimeout(timer);
  $("error").textContent = "";
  syncControls();
  try {
    const run = await api("/api/runs", {
      order_id: $("order").value,
      request: $("request").value,
    });
    renderedCount = 0;
    render(run);
    poll();
  } catch (err) {
    error(err);
  } finally {
    changing = false;
    syncControls();
  }
});
async function changeRun(action) {
  if (!current || changing) return;
  const runId = current.id;
  const expectedGeneration = ++generation;
  changing = true;
  clearTimeout(timer);
  syncControls();
  $("error").textContent = "";
  try {
    const run = await api(
      "/api/runs/" + runId + "/" + action,
      action === "approve" ? { version: current.version } : {},
    );
    if (expectedGeneration === generation && current?.id === runId) render(run);
  } catch (err) {
    error(err);
    // 응답이 유실돼도 같은 실행을 조회해 확정 상태를 복구한다.
    poll();
  } finally {
    changing = false;
    syncControls();
  }
}
$("approve").addEventListener("click", () => changeRun("approve"));
$("cancel").addEventListener("click", () => changeRun("cancel"));
document.querySelectorAll("[data-example]").forEach((button) =>
  button.addEventListener("click", () => {
    const ex = button.dataset.example;
    $("order").value =
      ex === "missing" ? "EX-1002" : ex === "empty" ? "EX-1003" : "EX-1001";
    $("request").value =
      ex === "normal"
        ? "오후에 가능한 검사 예약 시간을 찾아주세요."
        : "가능한 검사 예약 시간을 찾아주세요.";
    $("request").focus();
  }),
);
$("download").addEventListener("click", () => {
  if (!current) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(current, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "examflow-" + current.id + ".json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
api("/api/health")
  .then((h) => {
    $("mode").textContent =
      h.model_mode === "gemini"
        ? "Gemini 실제 모델 모드"
        : "규칙 기반 테스트 모드 · LLM 미호출";
  })
  .catch(() => {
    $("mode").textContent = "서버 연결 실패";
  });
