(() => {
  const byId = (id) => document.getElementById(id);
  const node = (tag, value, cls) => {
    const el = document.createElement(tag);
    el.textContent = value;
    if (cls) el.className = cls;
    return el;
  };
  let data = null,
    editing = null,
    cancelling = null,
    busy = false;
  let lastRun = null,
    selected = "readiness",
    refreshedRun = "";
  function navigate() {
    document.body.dataset.view =
      location.hash === "#management"
        ? "management"
        : location.hash === "#trace-heading"
          ? "collaboration"
          : "workflow";
    document
      .querySelectorAll(".workspace-nav a")
      .forEach((link) =>
        link.setAttribute(
          "aria-current",
          link.hash === location.hash ? "page" : "false",
        ),
      );
  }
  window.addEventListener("hashchange", navigate);
  navigate();
  const labels = {
    available: "예약 가능",
    booked: "예약됨",
    closed: "접수 중지",
    confirmed: "확정",
    cancelled: "취소",
  };
  const message = (text, bad = false) => {
    byId("workspace-message").textContent = text;
    byId("workspace-message").className = bad
      ? "message-error"
      : "message-success";
  };
  async function request(url, body, method = "POST") {
    const response = await fetch(
      url,
      body === undefined
        ? {}
        : {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
    );
    const result = await response.json();
    if (!response.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "입력 항목을 확인하세요.",
      );
    return result;
  }
  function button(text, callback, disabled = false) {
    const b = node("button", text, "secondary");
    b.type = "button";
    b.disabled = disabled || busy;
    b.addEventListener("click", callback);
    return b;
  }
  function table(headers, rows) {
    const table = node("table", ""),
      head = node("thead", ""),
      row = node("tr", "");
    headers.forEach((h) => {
      const cell = node("th", h);
      cell.scope = "col";
      row.append(cell);
    });
    head.append(row);
    table.append(head);
    const body = node("tbody", "");
    rows.forEach((cells) => {
      const tr = node("tr", "");
      cells.forEach((value) => {
        const td = node("td", "");
        if (typeof value === "string") td.textContent = value;
        else td.append(value);
        tr.append(td);
      });
      body.append(tr);
    });
    table.append(body);
    return table;
  }
  function showData(next) {
    data = next;
    byId("workspace-counts").replaceChildren();
    for (const [title, count] of [
      [
        "확정 예약",
        data.reservations.filter((r) => r.status === "confirmed").length,
      ],
      ["예약 가능", data.slots.filter((s) => s.status === "available").length],
      ["접수 중지", data.slots.filter((s) => s.status === "closed").length],
    ]) {
      const tile = node("div", "", "count-tile");
      tile.append(node("span", title), node("strong", String(count)));
      byId("workspace-counts").append(tile);
    }
    const reservations = data.reservations.map((r) => [
      r.order_id + " · " + r.alias,
      r.slot.exam,
      r.slot.day + " " + r.slot.time,
      r.slot.room,
      node("span", labels[r.status], "badge " + r.status),
      r.status === "confirmed"
        ? button("예약 취소", () => {
            cancelling = r;
            byId("cancel-reservation-summary").textContent =
              `${r.order_id} · ${r.slot.day} ${r.slot.time} · ${r.slot.room} 예약을 취소할까요? 취소한 시간은 다시 예약할 수 있습니다.`;
            byId("cancel-reservation-panel").hidden = false;
            byId("confirm-cancel-reservation").focus();
          })
        : node("span", "취소 완료", "hint"),
    ]);
    byId("reservation-list").replaceChildren(
      reservations.length
        ? table(
            ["의뢰", "검사", "예약 일시", "검사실", "상태", "관리"],
            reservations,
          )
        : node(
            "p",
            "확정된 예약이 없습니다. 예약안을 승인하면 이곳에 표시됩니다.",
            "empty-list",
          ),
    );
    const slots = [...data.slots]
      .sort(
        (a, b) => a.day.localeCompare(b.day) || a.time.localeCompare(b.time),
      )
      .map((s) => {
        const actions = node("div", "", "table-actions");
        actions.append(
          button("수정", () => openEditor(s), s.status === "booked"),
          button(
            s.enabled ? "접수 중지" : "접수 재개",
            () =>
              mutate(
                "/api/slots/" + s.id,
                {
                  exam: s.exam,
                  day: s.day,
                  time: s.time,
                  room: s.room,
                  enabled: !s.enabled,
                  version: s.version,
                },
                "PUT",
              ),
            s.status === "booked",
          ),
        );
        return [
          s.exam,
          s.day,
          s.time,
          s.room,
          node("span", labels[s.status], "badge " + s.status),
          actions,
        ];
      });
    byId("slot-list").replaceChildren(
      table(["검사", "운영일", "시간", "검사실", "상태", "관리"], slots),
    );
  }
  async function refresh() {
    if (busy) return;
    try {
      showData(await request("/api/workspace"));
    } catch (e) {
      message(e.message, true);
    }
  }
  function openEditor(slot) {
    editing = slot;
    byId("slot-form-title").textContent = slot ? "시간 수정" : "시간 추가";
    byId("slot-exam").value = slot?.exam || "CT";
    byId("slot-day").value = slot?.day || "다음 운영일";
    byId("slot-time").value = slot?.time || "09:00";
    byId("slot-room").value = slot?.room || "";
    byId("slot-enabled").checked = slot?.enabled ?? true;
    byId("slot-form").hidden = false;
    byId("slot-room").focus();
  }
  async function mutate(url, body, method = "POST") {
    if (busy) return;
    busy = true;
    byId("save-slot").disabled = true;
    byId("confirm-cancel-reservation").disabled = true;
    byId("add-slot").disabled = true;
    byId("close-slot-form").disabled = true;
    if (data) showData(data);
    try {
      const updated = await request(url, body, method);
      byId("slot-form").hidden = true;
      byId("cancel-reservation-panel").hidden = true;
      data = updated;
      message("변경 사항을 저장했습니다. 다음 일정 조회에 반영됩니다.");
      if (lastRun)
        window.dispatchEvent(new CustomEvent("examflow:workspace-updated"));
    } catch (e) {
      message(e.message, true);
    } finally {
      busy = false;
      byId("save-slot").disabled = false;
      byId("confirm-cancel-reservation").disabled = false;
      byId("add-slot").disabled = false;
      byId("close-slot-form").disabled = false;
      if (data) showData(data);
    }
  }
  byId("slot-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const body = {
      exam: byId("slot-exam").value,
      day: byId("slot-day").value.trim(),
      time: byId("slot-time").value,
      room: byId("slot-room").value.trim(),
      enabled: byId("slot-enabled").checked,
    };
    if (editing) body.version = editing.version;
    mutate(
      editing ? "/api/slots/" + editing.id : "/api/slots",
      body,
      editing ? "PUT" : "POST",
    );
  });
  byId("add-slot").addEventListener("click", () => openEditor(null));
  byId("close-slot-form").addEventListener("click", () => {
    byId("slot-form").hidden = true;
  });
  byId("refresh-workspace").addEventListener("click", refresh);
  byId("dismiss-cancel-reservation").addEventListener("click", () => {
    byId("cancel-reservation-panel").hidden = true;
  });
  byId("confirm-cancel-reservation").addEventListener("click", () => {
    if (cancelling)
      mutate("/api/reservations/" + cancelling.id + "/cancel", {});
  });

  const components = {
    orchestrator: ["작업 조정기", "요청 접수 · 두 에이전트 호출 · 승인 처리"],
    readiness: ["준비 확인 에이전트", "의뢰·규칙 조회 → 시간 선호와 준비 상태"],
    scheduling: [
      "일정 조정 에이전트",
      "현재 시간표 조회 → 조건에 맞는 시간 선택",
    ],
    tools: ["예약 MCP 서버", "의뢰 조회 · 시간 조회 · 승인된 예약 기록"],
  };
  const toolNames = {
    get_order: "검사 의뢰 조회",
    get_preparation_policy: "행정 규칙 조회",
    find_slots: "가용 시간 조회",
    reserve_demo_slot: "예약 기록",
  };
  function componentEvents(id) {
    return (lastRun?.events || []).filter((e) =>
      id === "tools"
        ? e.kind.startsWith("mcp.")
        : id === "orchestrator"
          ? ["orchestrator", "approval", "user"].includes(e.agent)
          : e.agent === id,
    );
  }
  function card(id) {
    const events = componentEvents(id),
      item = node(
        "button",
        "",
        "component-card" + (selected === id ? " selected" : ""),
      );
    item.type = "button";
    item.setAttribute("aria-pressed", String(selected === id));
    const calls = events.filter(
      (e) => e.kind.endsWith(".call") || e.kind === "a2a.send",
    ).length;
    const failures = events.some(
      (e) =>
        e.kind.endsWith(".failed") ||
        e.kind === "mcp.error" ||
        e.kind === "guard.rejected",
    );
    const done =
      (id === "orchestrator" &&
        lastRun &&
        [
          "confirmed",
          "cancelled",
          "needs_input",
          "no_slots",
          "conflict",
        ].includes(lastRun.state)) ||
      events.some((e) => e.kind === "agent.finished") ||
      (id === "tools" && events.some((e) => e.kind === "mcp.result"));
    item.classList.add(
      failures ? "failed" : done ? "done" : events.length ? "active" : "idle",
    );
    item.append(
      node(
        "span",
        id === "tools"
          ? "MCP / stdio"
          : id === "orchestrator"
            ? "HTTP / JSON-RPC"
            : "A2A / Gemini",
        "component-type",
      ),
      node("strong", components[id][0]),
      node("span", components[id][1], "component-description"),
      node(
        "small",
        events.length
          ? `${events.length}개 기록 · ${calls}회 호출${failures ? " · 오류 확인 필요" : ""}`
          : "요청 대기",
      ),
    );
    item.addEventListener("click", () => {
      selected = id;
      drawGraph();
    });
    return item;
  }
  function edge(label, cls = "") {
    return node("div", label, "connection " + cls);
  }
  function drawGraph() {
    const map = byId("collaboration-map");
    map.replaceChildren();
    const hub = node("div", "", "graph-hub");
    hub.append(card("orchestrator"));
    map.append(hub);
    const branches = node("div", "", "graph-branches");
    for (const id of ["readiness", "scheduling"]) {
      const branch = node("div", "", "graph-branch");
      const calls = (lastRun?.events || []).filter(
        (e) => e.kind === "a2a.send" && e.label === id,
      ).length;
      branch.append(
        edge(`↕ A2A HTTP · message/send${calls ? " · " + calls + "회" : ""}`),
        card(id),
        edge("↕ MCP stdio · tools/call", "mcp"),
      );
      branches.append(branch);
    }
    map.append(branches);
    map.append(
      node(
        "div",
        "담당자 승인 → 작업 조정기 → MCP 예약 기록 (stdio)",
        "approval-route",
      ),
    );
    const tools = node("div", "", "graph-hub");
    tools.append(card("tools"));
    map.append(
      tools,
      edge("↕ 조회 / 트랜잭션", "database"),
      node(
        "div",
        "검사 의뢰 · 행정 규칙 · 편집 가능한 시간표 · 예약 현황",
        "data-store",
      ),
    );
    const panel = byId("component-detail");
    panel.replaceChildren(node("h3", components[selected][0] + " · 실행 근거"));
    const decision =
      selected === "readiness"
        ? lastRun?.readiness?.decision
        : selected === "scheduling"
          ? lastRun?.schedule?.decision
          : null;
    if (decision) panel.append(node("p", decision.explanation, "summary"));
    if (selected === "readiness" && lastRun?.readiness)
      panel.append(
        node("p", "근거: " + lastRun.readiness.sources.join(" / "), "source"),
      );
    if (selected === "scheduling" && lastRun?.schedule)
      panel.append(
        node(
          "p",
          `조회 후보 ${lastRun.schedule.candidates.length}개 · 선택 ${lastRun.schedule.selected?.time || "없음"}`,
          "source",
        ),
      );
    const events = componentEvents(selected);
    if (!events.length)
      panel.append(
        node(
          "p",
          "아직 호출되지 않았습니다. 요청을 실행하면 호출 방향과 결과를 확인할 수 있습니다.",
          "hint",
        ),
      );
    for (const e of events) {
      const row = node("details", "", "evidence-row");
      let title =
        e.kind === "mcp.call"
          ? `${e.agent === "approval" ? "담당자 승인" : e.agent === "readiness" ? "준비 확인" : "일정 조정"} → MCP · ${toolNames[e.label] || e.label}`
          : e.kind === "mcp.result"
            ? `MCP → 호출자 · ${toolNames[e.label] || e.label} 결과`
            : e.kind === "a2a.send"
              ? `조정기 → ${components[e.label]?.[0] || e.label}`
              : e.kind === "a2a.receive"
                ? `${components[e.label]?.[0] || e.label} → 조정기 · 응답 수신`
                : e.kind === "model.call"
                  ? "Gemini에 근거 해석 요청"
                  : e.kind === "model.result"
                    ? "Gemini 구조화 응답 검증 완료"
                    : e.kind === "agent.started"
                      ? "에이전트 작업 시작"
                      : e.kind === "agent.finished"
                        ? "에이전트 결과 전달"
                        : e.kind === "approval.received"
                          ? "담당자 승인 접수"
                          : e.label;
      const summary = node(
        "summary",
        `${(e.at_ms / 1000).toFixed(2)}초 · ${title}`,
      );
      row.append(summary, node("pre", JSON.stringify(e.data, null, 2)));
      panel.append(row);
    }
  }
  window.addEventListener("examflow:run", (event) => {
    lastRun = event.detail;
    drawGraph();
    const key = lastRun.id + ":" + lastRun.state;
    if (
      ["confirmed", "cancelled", "conflict"].includes(lastRun.state) &&
      key !== refreshedRun
    ) {
      refreshedRun = key;
      refresh();
    }
  });
  drawGraph();
  refresh();
})();
