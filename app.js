/* SmartClaim web UI. React 18 UMD, no build step. Embed: SmartClaim.mount(el, {role:"customer"}) */
(function () {
  var h = React.createElement, useState = React.useState, useEffect = React.useEffect, useCallback = React.useCallback;
  var TOKENS = { customer: "demo-customer", claims_handler: "demo-handler", administrator: "demo-admin" };
  function api(role, method, path, body) {
    return fetch(path, { method: method, headers: { "X-Session": TOKENS[role], "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.error || "Error " + r.status); return j; }); });
  }
  var CHIPS = [["Water leak", "Water is leaking from behind my dishwasher, and the floor is getting wet."], ["Broken window", "A storm broke the kitchen window last night."],
    ["Storm damage", "Hail damaged the car port roof"], ["Appliance failure", "My refrigerator stopped working this morning."],
    ["Fire or smoke", "There is smoke coming from an electrical socket."], ["Theft", "Someone broke into my apartment and stole my laptop."]];
  var TITLE = { A: "Emergency: act now", B: "Notify building maintenance", C: "Possible personal claim", D: "A person will take a look" };

  function useAsync() {
    var s = useState({ busy: false, err: "" }), st = s[0], set = s[1];
    return [st, function (p) { set({ busy: true, err: "" }); return p.then(function (r) { set({ busy: false, err: "" }); return r; }, function (e) { set({ busy: false, err: e.message }); }); }];
  }

  function Notify(p) {
    var a = useState(null), prep = a[0], setPrep = a[1], b = useState(""), body = b[0], setBody = b[1], c = useState(false), consent = c[0], setConsent = c[1], d = useState(null), sent = d[0], setSent = d[1];
    var as = useAsync(), st = as[0], run = as[1];
    if (sent) return h("div", { className: "box ok" }, h("b", null, "Status: " + sent.status.replace(/_/g, " ")), h("div", null, sent.note || "Already recorded earlier."));
    if (!prep) return h("div", null, h("button", { className: "btn", disabled: st.busy, onClick: function () { run(api("customer", "POST", "/api/notifications/prepare", { incident_id: p.id })).then(function (r) { if (r) { setPrep(r); setBody(r.body); } }); } }, st.busy ? "Preparing..." : "Review and send notification"), st.err && h("div", { className: "box err" }, st.err));
    return h("div", null, h("label", { className: "lbl", htmlFor: "nb" }, "To: " + prep.recipient + " (" + prep.address + ")"),
      h("textarea", { id: "nb", value: body, onChange: function (e) { setBody(e.target.value); } }),
      h("label", { className: "lbl" }, h("input", { type: "checkbox", style: { width: "auto", marginRight: 8 }, checked: consent, onChange: function (e) { setConsent(e.target.checked); } }), "I agree that this message and my address are sent (demo system only)."),
      h("button", { className: "btn", disabled: !consent || st.busy, onClick: function () { run(api("customer", "POST", "/api/notifications/dispatch", { incident_id: p.id, consent: true, body: body })).then(function (r) { if (r) setSent(r); }); } }, st.busy ? "Sending..." : "Send notification"),
      st.err && h("div", { className: "box err" }, st.err));
  }

  function Claim(p) {
    var a = useState(null), cl = a[0], setCl = a[1], b = useState(""), desc = b[0], setDesc = b[1], c = useState(null), done = c[0], setDone = c[1];
    var as = useAsync(), st = as[0], run = as[1];
    if (done) return h("div", { className: "box ok" }, h("b", null, "Status: " + done.status.replace(/_/g, " ")), h("div", null, done.note || "Already submitted earlier."));
    if (!cl) return h("div", null, h("button", { className: "btn", disabled: st.busy, onClick: function () { run(api("customer", "POST", "/api/claims/draft", { incident_id: p.id })).then(function (r) { if (r) { setCl(r); setDesc(r.draft.description); } }); } }, st.busy ? "Preparing..." : "Prepare draft claim"), st.err && h("div", { className: "box err" }, st.err));
    var d = cl.draft;
    return h("div", null, h("p", { className: "fine" }, "Policy " + d.policy_ref + " | " + d.address + " | deductible " + d.deductible_eur + " EUR (demo data)"),
      h("label", { className: "lbl", htmlFor: "cd" }, "Description (you can edit)"), h("textarea", { id: "cd", value: desc, onChange: function (e) { setDesc(e.target.value); } }),
      h("button", { className: "btn", disabled: st.busy, onClick: function () { run(api("customer", "POST", "/api/claims/submit", { incident_id: p.id, edits: { description: desc } })).then(function (r) { if (r) setDone(r); }); } }, st.busy ? "Submitting..." : "Submit claim for review"),
      st.err && h("div", { className: "box err" }, st.err));
  }

  function Result(p) {
    var r = p.res, a = useState(""), more = a[0], setMore = a[1];
    return h("div", { className: "card", "aria-live": "polite" },
      r.outcome === "A" && h("div", { className: "box a" }, "Call 112 now if anyone is in danger."),
      h("h2", null, TITLE[r.outcome]), h("div", { className: "box s" }, h("b", null, "Do now: "), r.safety),
      h("p", null, r.message), h("p", { className: "fine" }, r.disclaimer),
      r.outcome === "B" && h(Notify, { id: r.id, key: r.id }), r.outcome === "C" && h(Claim, { id: r.id, key: r.id }),
      r.question && h("div", null, h("label", { className: "lbl", htmlFor: "q2" }, r.question),
        h("input", { id: "q2", value: more, onChange: function (e) { setMore(e.target.value); } }),
        h("button", { className: "btn sm sec", style: { marginTop: 8 }, disabled: more.trim().length < 3, onClick: function () { p.onMore(more.trim()); } }, "Continue")),
      r.status === "needs_review" && h("div", { className: "box ok" }, "Queued for a claims handler. Responsibility is not decided by this tool."));
  }

  function Widget() {
    var a = useState(""), text = a[0], setText = a[1], b = useState(null), res = b[0], setRes = b[1];
    var as = useAsync(), st = as[0], run = as[1];
    function go(t) { return run(api("customer", "POST", "/api/incidents/analyze", { text: t })).then(function (r) { if (r) setRes(r); }); }
    return h("div", { className: "narrow" }, h("h1", null, "Tell us what happened. We'll help you take the next step."),
      h("div", { className: "sos" }, "In danger or a fire? Call 112 first. Do not wait for this application."),
      h("div", { className: "card" }, h("label", { className: "lbl", htmlFor: "t" }, "Describe the problem in one sentence"),
        h("textarea", { id: "t", value: text, maxLength: 1000, onChange: function (e) { setText(e.target.value); }, placeholder: "Water is leaking from behind my dishwasher" }),
        h("div", { className: "chips" }, CHIPS.map(function (c) { return h("button", { key: c[0], type: "button", className: "chip", onClick: function () { setText(c[1]); } }, c[0]); })),
        h("button", { className: "btn", disabled: st.busy || text.trim().length < 3, onClick: function () { go(text.trim()); } }, st.busy ? "Analyzing..." : "Analyze and resolve"),
        st.err && h("div", { className: "box err" }, st.err),
        h("p", { className: "fine" }, "Prototype with synthetic data. Your text is processed by this demo only; nothing is sent to a real insurer, property manager or external AI service.")),
      res && h(Result, { res: res, key: res.id, onMore: function (m) { var t = (text + " " + m).trim(); setText(t); go(t); } }));
  }

  function Bars(p) {
    var e = Object.entries(p.data || {}), mx = Math.max.apply(null, e.map(function (x) { return x[1]; }).concat([1]));
    return h("div", { className: "card" }, h("h2", null, p.title), e.map(function (x) { return h("div", { className: "bar", key: x[0] }, h("span", null, x[0]), h("i", { style: { width: (x[1] / mx * 55) + "%" } }), h("span", null, x[1])); }));
  }

  function Detail(p) {
    var a = useState(null), d = a[0], setD = a[1], b = useState("B"), out = b[0], setOut = b[1], c = useState(""), why = c[0], setWhy = c[1], as = useAsync(), st = as[0], run = as[1];
    var load = useCallback(function () { api(p.role, "GET", "/api/staff/incidents/" + p.id).then(setD); }, [p.id, p.role]); useEffect(load, [load]);
    function act(path, body) { run(api(p.role, "POST", "/api/staff/incidents/" + p.id + "/" + path, body)).then(function (r) { if (r) { setD(r); p.onChange(); } }); }
    if (!d) return h("div", { className: "modal" }, h("div", { className: "card" }, "Loading..."));
    var an = d.analysis;
    return h("div", { className: "modal", onClick: function (e) { if (e.target === e.currentTarget) p.onClose(); } }, h("div", { className: "card", role: "dialog", "aria-label": "Case details" },
      h("h2", null, d.id + " (" + d.status + ")"), h("p", null, h("b", null, "Customer text: "), d.text),
      h("p", null, d.category + " | " + d.urgency + " | confidence " + d.confidence + " (" + an.method + ", not a coverage probability)"),
      h("p", null, h("b", null, "Decision: "), "outcome " + d.outcome + " via " + d.rule_ids.join(", ") + " to " + d.destination + ". " + an.reason),
      d.notification && h("p", null, "Notification: " + d.notification.status), d.claim && h("p", null, "Claim: " + d.claim.status + " | " + d.claim.draft.handler_summary),
      h("h2", null, "Audit trail"), h("ol", { className: "ev" }, d.events.map(function (e, i) { return h("li", { key: i }, e.ts.slice(0, 19).replace("T", " ") + " | " + e.type + (e.detail ? " | " + e.detail : "")); })),
      h("h2", { style: { marginTop: 14 } }, "Human review"), h("div", { className: "filters" },
        h("select", { value: out, onChange: function (e) { setOut(e.target.value); }, "aria-label": "New outcome" }, ["A", "B", "C", "D"].map(function (o) { return h("option", { key: o, value: o }, o + ": " + TITLE[o]); })),
        h("input", { placeholder: "Reason", value: why, onChange: function (e) { setWhy(e.target.value); }, "aria-label": "Reason" })),
      h("button", { className: "btn sm", disabled: st.busy || !why.trim(), onClick: function () { act("override", { outcome: out, reason: why }); } }, "Apply override"), " ",
      h("button", { className: "btn sm sec", disabled: st.busy, onClick: function () { act("resolve", {}); } }, "Mark resolved"), " ", h("button", { className: "btn sm sec", onClick: p.onClose }, "Close"),
      st.err && h("div", { className: "box err" }, st.err)));
  }

  function Dashboard() {
    var r = useState("claims_handler"), role = r[0], setRole = r[1], m = useState(null), met = m[0], setMet = m[1], l = useState([]), rows = l[0], setRows = l[1];
    var f = useState({ status: "", category: "", urgency: "", outcome: "" }), fl = f[0], setFl = f[1], o = useState(null), open = o[0], setOpen = o[1], e = useState("");
    var qs = Object.keys(fl).filter(function (k) { return fl[k]; }).map(function (k) { return k + "=" + encodeURIComponent(fl[k]); }).join("&");
    var load = useCallback(function () {
      api(role, "GET", "/api/dashboard/metrics" + (fl.category ? "?category=" + fl.category : "")).then(setMet).catch(function () { });
      api(role, "GET", "/api/staff/incidents?" + qs).then(function (x) { setRows(x.incidents); }).catch(function () { });
    }, [role, qs]); useEffect(load, [load]);
    function sel(k, vals) { return h("select", { "aria-label": k, value: fl[k], onChange: function (ev) { var n = Object.assign({}, fl); n[k] = ev.target.value; setFl(n); } }, [h("option", { key: "", value: "" }, "All " + k)].concat(vals.map(function (v) { return h("option", { key: v, value: v }, v); }))); }
    var k = function (label, v) { return h("div", { className: "kpi", key: label }, h("b", null, v == null ? "n/a" : v), h("span", null, label)); };
    return h("div", null, h("div", { className: "filters" }, h("select", { "aria-label": "Role", value: role, onChange: function (ev) { setRole(ev.target.value); } }, h("option", { value: "claims_handler" }, "Claims handler"), h("option", { value: "administrator" }, "Administrator")),
      sel("status", ["needs_review", "needs_clarification", "awaiting_customer", "notified", "claim_submitted", "emergency_shown", "resolved"]),
      sel("category", ["water_leak", "water_damage", "fire_smoke", "electrical", "theft", "storm", "glass", "appliance", "structural", "other"]), sel("urgency", ["emergency", "high", "medium", "low"]), sel("outcome", ["A", "B", "C", "D"])),
      met && h("div", null, h("div", { className: "grid", style: { marginBottom: 14 } }, [k("Incidents analyzed", met.total_incidents), k("Notifications (simulated)", met.notifications_dispatched_simulated), k("Claims drafted", met.claims_drafted), k("Claims submitted", met.claims_submitted),
        k("Routed without claim (prototype)", met.routed_without_claim_prototype), k("Avg recommendation (ms)", met.avg_recommendation_ms), k("Avg completion (s)", met.avg_completion_seconds), k("Awaiting review", met.awaiting_human_review), k("Uncertain", met.uncertain)]),
        h("div", { className: "grid" }, h(Bars, { title: "By category", data: met.by_category }), h(Bars, { title: "Routing outcome", data: met.by_outcome }), h(Bars, { title: "Confidence", data: met.confidence_buckets })), h("p", { className: "fine" }, met.note)),
      h("div", { className: "card tw" }, h("h2", null, "Cases (" + rows.length + ")"), h("table", null, h("thead", null, h("tr", null, ["ID", "Time", "Category", "Urgency", "Outcome", "Status", "Conf.", "Destination"].map(function (c) { return h("th", { key: c }, c); }))),
        h("tbody", null, rows.slice(0, 60).map(function (x) { return h("tr", { className: "row", key: x.id, tabIndex: 0, onClick: function () { setOpen(x.id); }, onKeyDown: function (ev) { if (ev.key === "Enter") setOpen(x.id); } },
          h("td", null, x.id), h("td", null, x.created_at.slice(0, 16).replace("T", " ")), h("td", null, x.category), h("td", null, h("span", { className: "pill " + x.urgency }, x.urgency)), h("td", null, x.outcome), h("td", null, x.status), h("td", null, x.confidence), h("td", null, x.destination)); })))),
      open && h(Detail, { id: open, role: role, onClose: function () { setOpen(null); }, onChange: load }));
  }

  function App() {
    var a = useState("customer"), tab = a[0], setTab = a[1];
    return h("div", null, h("header", null, h("b", null, "If SmartClaim"), h("span", { className: "tag" }, "Prototype, synthetic data"),
      h("nav", null, ["customer", "staff"].map(function (t) { return h("button", { key: t, className: tab === t ? "on" : "", onClick: function () { setTab(t); } }, t === "customer" ? "Customer widget" : "Staff dashboard"); }))),
      h("main", null, tab === "customer" ? h(Widget) : h(Dashboard)));
  }
  window.SmartClaim = { mount: function (el) { ReactDOM.createRoot(el).render(h(Widget)); } };
  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
