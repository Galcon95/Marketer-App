/* @ds-bundle: {"format":4,"namespace":"BookCraft","components":[{"name":"Icon"},{"name":"Button"},{"name":"Badge"},{"name":"Card"},{"name":"Field"},{"name":"Tabs"},{"name":"Sidebar"},{"name":"OutputCard"},{"name":"UploadZone"},{"name":"ChunkCard"},{"name":"CitationCard"},{"name":"McpServerCard"},{"name":"LeadsTable"},{"name":"AgentGraph"},{"name":"AgentConsole"},{"name":"ReviewPanel"}]} */
(function () {
  var React = window.React, h = React.createElement, useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(" "); }

  /* Lucide icon geometry (ISC licence), 24×24, stroke 2. */
  var P = {
    check: ["p:M20 6 9 17l-5-5"],
    alert: ["p:m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "p:M12 9v4", "p:M12 17h.01"],
    cpu: ["r:4,4,16,16,2", "r:9,9,6,6,1", "p:M15 2v2", "p:M15 20v2", "p:M2 15h2", "p:M2 9h2", "p:M20 15h2", "p:M20 9h2", "p:M9 2v2", "p:M9 20v2"],
    database: ["e:12,5,9,3", "p:M3 5V19A9 3 0 0 0 21 19V5", "p:M3 12A9 3 0 0 0 21 12"],
    network: ["r:16,16,6,6,1", "r:2,16,6,6,1", "r:9,2,6,6,1", "p:M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3", "p:M12 12V8"],
    send: ["p:M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z", "p:m21.854 2.147-10.94 10.939"],
    refresh: ["p:M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", "p:M21 3v5h-5", "p:M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", "p:M8 16H3v5"],
    copy: ["r:8,8,14,14,2", "p:M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"],
    search: ["c:11,11,8", "p:m21 21-4.3-4.3"],
    upload: ["p:M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "p:m17 8-5-5-5 5", "p:M12 3v12"],
    x: ["p:M18 6 6 18", "p:m6 6 12 12"],
    book: ["p:M12 7v14", "p:M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"],
    sparkles: ["p:M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.563.563 0 0 1 1.073 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.563.563 0 0 1-1.073 0z", "p:M20 3v4", "p:M22 5h-4"],
    terminal: ["p:m4 17 6-6-6-6", "p:M12 19h8"],
    pencil: ["p:M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z", "p:m15 5 4 4"],
    shield: ["p:M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z", "p:m9 12 2 2 4-4"],
    users: ["p:M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "c:9,7,4", "p:M22 21v-2a4 4 0 0 0-3-3.87", "p:M16 3.13a4 4 0 0 1 0 7.75"],
    user: ["p:M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2", "c:12,7,4"],
    layout: ["r:3,3,7,9,1", "r:14,3,7,5,1", "r:14,12,7,9,1", "r:3,16,7,5,1"],
    chevron: ["p:m6 9 6 6 6-6"],
    chevronsUD: ["p:m7 15 5 5 5-5", "p:m7 9 5-5 5 5"],
    file: ["p:M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z", "p:M14 2v4a2 2 0 0 0 2 2h4", "p:M16 13H8", "p:M16 17H8", "p:M10 9H8"],
    message: ["p:M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"],
    mic: ["p:M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z", "p:M19 10v2a7 7 0 0 1-14 0v-2", "p:M12 19v3"],
    star: ["p:M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"],
    bot: ["p:M12 8V4H8", "r:4,8,16,12,2", "p:M2 14h2", "p:M20 14h2", "p:M15 13v2", "p:M9 13v2"],
    target: ["c:12,12,10", "c:12,12,6", "c:12,12,2"],
    quote: ["p:M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z", "p:M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"],
    menu: ["p:M4 12h16", "p:M4 6h16", "p:M4 18h16"],
    settings: ["p:M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z", "c:12,12,3"],
    play: ["p:M6 3 20 12 6 21 6 3z"],
    pause: ["r:14,4,4,16,1", "r:6,4,4,16,1"]
  };
  function Icon(props) {
    var size = props.size || 16, d = P[props.name] || P.x;
    var kids = d.map(function (s, i) {
      var t = s[0], v = s.slice(2);
      if (t === "p") return h("path", { key: i, d: v });
      var n = v.split(",").map(Number);
      if (t === "c") return h("circle", { key: i, cx: n[0], cy: n[1], r: n[2] });
      if (t === "e") return h("ellipse", { key: i, cx: n[0], cy: n[1], rx: n[2], ry: n[3] });
      return h("rect", { key: i, x: n[0], y: n[1], width: n[2], height: n[3], rx: n[4] });
    });
    return h("svg", { className: cx("bc-ico", props.className), width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: props.strokeWidth || 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": props.label ? undefined : true, role: props.label ? "img" : undefined, "aria-label": props.label }, kids);
  }

  function Button(p) {
    var rest = Object.assign({}, p); ["variant", "size", "icon", "iconRight", "loading", "className", "children"].forEach(function (k) { delete rest[k]; });
    return h("button", Object.assign({ type: "button" }, rest, { className: cx("bc-btn", "bc-btn-" + (p.variant || "primary"), p.size === "sm" && "bc-btn-sm", p.className), disabled: p.disabled || p.loading }),
      p.loading ? h(Icon, { name: "refresh", size: p.size === "sm" ? 14 : 16, className: "bc-spin" }) : p.icon && h(Icon, { name: p.icon, size: p.size === "sm" ? 14 : 16 }),
      p.children, p.iconRight && h(Icon, { name: p.iconRight, size: 14 }));
  }

  function Badge(p) {
    return h("span", { className: cx("bc-badge", p.tone && p.tone !== "neutral" && "bc-badge-" + p.tone, p.mono && "bc-badge-mono", p.className) },
      p.dot && h("i", { className: cx("bc-dot", p.pulse && "bc-dot-pulse") }), p.icon && h(Icon, { name: p.icon, size: 12 }), p.children);
  }

  function Card(p) {
    return h("section", { className: cx("bc-card", p.className), style: p.style },
      (p.title || p.actions) && h("header", { className: "bc-card-head" }, p.icon && h(Icon, { name: p.icon }), h("h3", null, p.title), p.meta, p.actions),
      h("div", { className: p.flush ? "" : "bc-card-body" }, p.children));
  }

  function Field(p) {
    var id = p.id || ("f-" + String(p.label).replace(/\W+/g, "-").toLowerCase());
    var ctl;
    var base = { id: id, value: p.value, defaultValue: p.defaultValue, placeholder: p.placeholder, onChange: p.onChange };
    if (p.as === "textarea") ctl = h("textarea", Object.assign(base, { className: "bc-textarea", rows: p.rows || 3 }));
    else if (p.as === "select") ctl = h("div", { className: "bc-select-wrap" }, h("select", Object.assign(base, { className: "bc-select" }), (p.options || []).map(function (o) { return h("option", { key: o, value: o }, o); })), h(Icon, { name: "chevron", size: 16 }));
    else if (p.as === "search") ctl = h("div", { className: "bc-search" }, h(Icon, { name: "search", size: 16 }), h("input", Object.assign(base, { className: "bc-input", type: "search" })));
    else ctl = h("input", Object.assign(base, { className: "bc-input", type: "text" }));
    return h("div", { className: cx("bc-field", p.className) }, p.label && h("label", { className: "bc-label", htmlFor: id }, p.label), ctl, p.hint && h("span", { className: "bc-hint" }, p.hint));
  }

  function Tabs(p) {
    return h("div", { className: "bc-tabs", role: "tablist" }, p.items.map(function (t) {
      return h("button", { key: t.id, role: "tab", className: "bc-tab", "aria-selected": p.value === t.id, onClick: function () { p.onChange && p.onChange(t.id); } },
        t.kicker && h("span", { className: "bc-tab-k" }, t.kicker), h("span", { className: "bc-tab-l" }, t.icon && h(Icon, { name: t.icon, size: 14 }), t.label));
    }));
  }

  function Sidebar(p) {
    var nav = p.nav || [];
    return h("aside", { className: "bc-side", "aria-label": "Main" },
      h("div", { className: "bc-logo" }, h("span", { className: "bc-logo-mark" }, h(Icon, { name: "book", size: 18 })),
        h("div", null, h("div", { className: "bc-logo-name" }, "BookCraft ", h("span", null, "AI")), h("div", { className: "bc-logo-sub" }, p.workspace || "author-marketing os"))),
      h("button", { className: "bc-proj", "aria-label": "Switch project" }, h("span", { className: "bc-proj-ico" }, h(Icon, { name: "file", size: 14 })),
        h("span", { style: { minWidth: 0, flex: 1 } }, h("span", { className: "bc-label", style: { display: "block", fontSize: 10, lineHeight: "14px" } }, "Current book"), h("span", { className: "bc-proj-t", style: { display: "block" } }, p.project || "The Atomic Loop.epub"), h("span", { className: "bc-proj-s" }, p.projectMeta || "62k words · 18 ch")),
        h(Icon, { name: "chevronsUD", size: 14, className: "bc-muted" })),
      nav.map(function (g) {
        return h("nav", { key: g.title, className: "bc-nav" }, h("div", { className: "bc-nav-h" }, g.title), g.items.map(function (it) {
          return h("button", { key: it.id, className: "bc-nav-a", "aria-current": p.active === it.id ? "page" : undefined, onClick: function () { p.onNavigate && p.onNavigate(it.id); } },
            h(Icon, { name: it.icon, size: 16 }), it.label, it.count != null && h("span", { className: "bc-n" }, it.count));
        }));
      }),
      h("div", { className: "bc-status", role: "status" }, h("div", { className: "bc-nav-h", style: { padding: 0 } }, "System status"),
        (p.status || [{ icon: "network", label: "MCP Servers", value: "3 Active" }, { icon: "database", label: "Vector DB", value: "Connected" }]).map(function (s) {
          return h("div", { key: s.label, className: "bc-status-r" }, h(Icon, { name: s.icon, size: 14 }), s.label, h("b", null, h("i", { className: "bc-dot bc-dot-pulse" }), s.value));
        })));
  }

  function OutputCard(p) {
    var st = useState(false), done = st[0], setDone = st[1];
    var words = (p.text || "").trim().split(/\s+/).filter(Boolean).length;
    function copy() { try { navigator.clipboard && navigator.clipboard.writeText(p.text); } catch (e) {} setDone(true); setTimeout(function () { setDone(false); }, 1400); }
    return h("article", { className: cx("bc-out", p.className) },
      h("div", { className: "bc-out-h" }, p.icon && h(Icon, { name: p.icon, size: 14, className: "bc-acc" }), h("strong", null, p.title), p.tag && h(Badge, { tone: p.tagTone || "accent", mono: true }, p.tag)),
      h("p", null, p.text),
      h("div", { className: "bc-out-f" }, h("span", null, words + " words"), p.limit && h("span", null, "· " + (p.text || "").length + "/" + p.limit + " chars"),
        h(Button, { variant: "ghost", size: "sm", icon: done ? "check" : "copy", className: "bc-copy", "data-done": done, onClick: copy, "aria-label": "Copy " + p.title }, done ? "Copied" : "Copy")));
  }

  function UploadZone(p) {
    var pct = Math.round(p.progress == null ? 100 : p.progress), done = pct >= 100;
    return h("div", { className: "bc-up" }, h("span", { className: "bc-up-ico" }, h(Icon, { name: done ? "database" : "upload", size: 20 })),
      h("div", { className: "bc-up-main" },
        h("div", { className: "bc-up-t" }, p.fileName || "Drop manuscript", done ? h(Badge, { tone: "success", icon: "check" }, "Indexed") : h(Badge, { tone: "accent", dot: true, pulse: true }, "Embedding " + pct + "%")),
        h("div", { className: "bc-bar", "data-done": done, role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 }, h("i", { style: { width: pct + "%" } })),
        h("div", { className: "bc-up-meta" }, (p.meta || []).map(function (m) { return h("span", { key: m }, m); }))),
      h(Button, { variant: "secondary", icon: "upload", onClick: p.onBrowse }, "Upload .pdf · .epub · .md"));
  }

  function tier(s) { return s >= 0.85 ? "hi" : s >= 0.7 ? "md" : "lo"; }
  function ChunkCard(p) {
    var c = p.chunk;
    return h("button", { className: "bc-chunk", "aria-pressed": !!p.active, onClick: p.onClick },
      h("div", { className: "bc-chunk-h" }, h("span", { className: "bc-chunk-id" }, c.id), h(Badge, { mono: true }, c.chapter), h(Badge, { mono: true }, "p." + c.page),
        h("span", { className: "bc-score bc-score-" + tier(c.score) }, "quote " + c.score.toFixed(2))),
      h("p", null, c.text),
      c.tags && h("div", { className: "bc-chunk-h" }, c.tags.map(function (t) { return h(Badge, { key: t, mono: true, tone: "accent" }, "#" + t); })));
  }

  function CitationCard(p) {
    var st = useState(p.defaultOpen !== false), open = st[0], setOpen = st[1], a = p.asset, c = p.citation;
    return h("article", { className: "bc-cite", "data-open": open },
      h("div", { className: "bc-cite-main" },
        h("div", { className: "bc-row" }, h(Badge, { tone: "accent", mono: true }, a.kind), h(Badge, { tone: "success", icon: "shield" }, "Grounded"), h("span", { style: { flex: 1 } }),
          h(Button, { variant: "ghost", size: "sm", icon: "quote", onClick: function () { setOpen(!open); }, "aria-expanded": open }, open ? "Hide source" : "Show source")),
        h("h4", null, a.title), h("p", null, a.before, a.quote && h("mark", null, a.quote), a.after),
        h("div", { className: "bc-out-f" }, h("span", null, (a.before + (a.quote || "") + (a.after || "")).split(/\s+/).length + " words"), h("span", null, "· model: grounded-rag"))),
      open && h("aside", { className: "bc-cite-src", "aria-label": "Retrieved source citation" },
        h("div", { className: "bc-label" }, "Retrieved source citation"),
        h("div", { className: "bc-cite-k" }, h(Badge, { mono: true }, c.chapter), h(Badge, { mono: true }, "p." + c.page), h(Badge, { mono: true }, c.chunk), h("span", { className: "bc-score bc-score-" + tier(c.score) }, "sim " + c.score.toFixed(2))),
        h("blockquote", null, c.text),
        h("div", { className: "bc-cite-k" }, h(Icon, { name: "check", size: 12 }), "exact match · " + c.matchChars + " chars")));
  }

  function McpServerCard(p) {
    var tone = p.status === "Active" ? "success" : p.status === "Degraded" ? "warning" : "danger";
    return h("article", { className: "bc-mcp" },
      h("div", { className: "bc-mcp-h" }, h("span", { className: "bc-mcp-ico" }, h(Icon, { name: p.icon || "network", size: 16 })), h("span", { className: "bc-mcp-n", title: p.name }, p.name),
        h(Badge, { tone: tone, dot: true, pulse: tone === "success" }, p.status)),
      h("div", { className: "bc-mcp-m" }, h("b", null, p.metric), h("span", null, p.metricLabel),
        p.spark && h("span", { className: "bc-spark", "aria-hidden": true }, p.spark.map(function (v, i) { return h("i", { key: i, style: { height: v + "%" } }); }))),
      h("div", { className: "bc-mcp-d" }, p.detail),
      h("div", { className: "bc-mcp-f" }, (p.footer || []).map(function (f) { return h("span", { key: f }, f); })));
  }

  var SRC = { reddit: "message", web: "search", goodreads: "star", podcast: "mic" };
  function LeadsTable(p) {
    var st = useState({}), drafted = st[0], setDrafted = st[1];
    return h("div", { className: "bc-table-wrap" }, h("table", { className: "bc-table" },
      h("thead", null, h("tr", null, ["Source", "User question / thread", "Intent score", "Keyword match", ""].map(function (c, i) { return h("th", { key: i, style: i === 4 ? { textAlign: "right" } : null }, c); }))),
      h("tbody", null, p.rows.map(function (r) {
        var t = tier(r.intent), d = drafted[r.id];
        return h("tr", { key: r.id, "data-new": r.fresh ? "true" : undefined },
          h("td", null, h("span", { className: "bc-src" }, h(Icon, { name: SRC[r.kind] || "search", size: 14 }), r.source)),
          h("td", null, h("div", { className: "bc-q" }, r.question, h("small", null, r.meta))),
          h("td", null, h("div", { className: "bc-intent", "data-tier": t }, h("span", { className: "bc-score bc-score-" + t }, Math.round(r.intent * 100)), h("div", { className: "bc-bar" }, h("i", { style: { width: r.intent * 100 + "%" } })))),
          h("td", null, h("div", { className: "bc-row", style: { gap: 4 } }, r.keywords.map(function (k) { return h(Badge, { key: k, mono: true, tone: "accent" }, k); }))),
          h("td", { style: { textAlign: "right" } }, h(Button, { size: "sm", variant: d ? "secondary" : "primary", icon: d ? "check" : "send", onClick: function () { var n = Object.assign({}, drafted); n[r.id] = true; setDrafted(n); p.onDraft && p.onDraft(r); } }, d ? "Drafted" : "Draft Pitch")));
      }))));
  }

  var STATE_LABEL = { idle: "Queued", running: "Running", done: "Complete", waiting: "Awaiting review" };
  function Edge(p) {
    return h("div", { className: "bc-edge", "data-state": p.state, "aria-hidden": true },
      h("svg", { viewBox: "0 0 100 24", preserveAspectRatio: "none" },
        h("line", { className: "bc-edge-base", x1: 0, y1: 12, x2: 100, y2: 12, vectorEffect: "non-scaling-stroke" }),
        h("line", { className: "bc-edge-flow", x1: 0, y1: 12, x2: 100, y2: 12, vectorEffect: "non-scaling-stroke" }),
        h("circle", { className: "bc-edge-pkt", r: 3.5, cy: 12, cx: 0 }, h("animate", { attributeName: "cx", from: "0", to: "100", dur: p.state === "done" ? "2.4s" : "1.2s", repeatCount: "indefinite" }))));
  }
  function AgentGraph(p) {
    var nodes = p.nodes, kids = [];
    nodes.forEach(function (n, i) {
      if (i) kids.push(h(Edge, { key: "e" + i, state: nodes[i - 1].state !== "done" ? "idle" : n.state === "running" ? "running" : n.state === "idle" ? "idle" : "done" }));
      kids.push(h("div", { key: n.id, className: "bc-node", "data-state": n.state, role: "group", "aria-label": n.name + ": " + STATE_LABEL[n.state] },
        h("div", { className: "bc-node-h" }, h("span", { className: "bc-node-ico" }, h(Icon, { name: n.icon, size: 16 })), h("div", null, h("div", { className: "bc-node-n" }, n.name), h("div", { className: "bc-node-m" }, n.model))),
        h("div", { className: "bc-node-s" }, h(Icon, { name: n.state === "done" ? "check" : n.state === "waiting" ? "alert" : n.state === "running" ? "refresh" : "pause", size: 12, className: n.state === "running" ? "bc-spin" : null }), STATE_LABEL[n.state], n.stat && h("span", { style: { marginLeft: "auto", color: "var(--ink-subtle)" } }, n.stat))));
    });
    return h("div", { className: "bc-graph" }, h("div", { className: "bc-graph-row" }, kids));
  }

  function AgentConsole(p) {
    var ref = useRef(null);
    useEffect(function () { var el = ref.current; if (el) el.scrollTop = el.scrollHeight; }, [p.lines.length]);
    return h("section", { className: "bc-con", style: p.height ? { height: p.height } : null, "aria-label": "Agent terminal" },
      h("div", { className: "bc-con-h" }, h(Icon, { name: "terminal", size: 14 }), p.title || "agent-runtime · thread_7f3a", p.live ? h(Badge, { tone: "success", dot: true, pulse: true }, "Live") : h(Badge, null, "Paused"), p.onToggle && h(Button, { variant: "ghost", size: "sm", icon: p.live ? "pause" : "play", onClick: p.onToggle, "aria-label": p.live ? "Pause stream" : "Resume stream" })),
      h("div", { className: "bc-con-b", ref: ref, role: "log", "aria-live": "polite" }, p.lines.map(function (l, i) {
        return h("div", { key: i, className: "bc-log", "data-kind": l.kind }, h("span", { className: "bc-log-t" }, l.t), h("span", { className: "bc-log-a" }, l.agent), h("span", { className: "bc-log-m" }, l.msg));
      }), p.live && h("span", { className: "bc-caret" })));
  }

  function ReviewPanel(p) {
    var st = useState(null), outcome = st[0], setOutcome = st[1];
    var ed = useState(false), editing = ed[0], setEditing = ed[1];
    var fb = useState(false), fbOpen = fb[0], setFb = fb[1];
    return h("section", { className: "bc-rev", "aria-label": "Human-in-the-loop review" },
      h("header", { className: "bc-rev-h" }, h(Icon, { name: "user", size: 16 }), h("h3", null, p.title || "Human Checkpoint Gate"),
        outcome === "approved" ? h(Badge, { tone: "success", icon: "send" }, "Dispatched") : outcome === "rejected" ? h(Badge, { tone: "danger", icon: "x" }, "Returned to Copywriter") : h(Badge, { tone: "warning", dot: true, pulse: true }, "Awaiting your decision"),
        p.target && h(Badge, { mono: true }, p.target)),
      h("div", { className: "bc-rev-g" },
        h("div", { className: "bc-rev-col" }, h("div", { className: "bc-rev-k" }, h(Icon, { name: "pencil", size: 12 }), "Agent drafted pitch"),
          h("p", { className: "bc-rev-copy", contentEditable: editing, suppressContentEditableWarning: true }, p.draft),
          h("div", { className: "bc-out-f" }, h("span", null, p.draft.split(/\s+/).length + " words"), h("span", null, "· copywriter-agent v3"))),
        h("div", { className: "bc-rev-col" }, h("div", { className: "bc-rev-k" }, h(Icon, { name: "shield", size: 12 }), "Auditor verification report", h("span", { style: { marginLeft: "auto" } }, h(Badge, { tone: "success", mono: true }, p.score || "score 0.94"))),
          p.checks.map(function (c, i) { return h("div", { key: i, className: "bc-check", "data-ok": c.ok }, h(Icon, { name: c.ok ? "check" : "alert", size: 14 }), h("div", null, c.label, c.detail && h("small", null, c.detail))); }))),
      fbOpen && !outcome && h("div", { className: "bc-rev-f" }, h(Field, { as: "textarea", label: "Feedback for the Copywriter Agent", placeholder: "e.g. Lead with the time-loop hook, drop the second quote.", className: "bc-rev-fb", rows: 2 })),
      h("footer", { className: "bc-rev-f" },
        h(Button, { variant: "success", icon: "send", disabled: !!outcome, onClick: function () { setOutcome("approved"); setEditing(false); p.onApprove && p.onApprove(); } }, "Approve & Dispatch"),
        h(Button, { variant: "danger", icon: "x", disabled: !!outcome, onClick: function () { if (!fbOpen) { setFb(true); return; } setOutcome("rejected"); p.onReject && p.onReject(); } }, fbOpen ? "Send feedback" : "Reject with Feedback"),
        h(Button, { variant: "secondary", icon: editing ? "check" : "pencil", disabled: !!outcome, onClick: function () { setEditing(!editing); } }, editing ? "Done editing" : "Edit Copy"),
        h("span", { className: "bc-sp" }),
        outcome && h(Button, { variant: "ghost", size: "sm", icon: "refresh", onClick: function () { setOutcome(null); setFb(false); } }, "Reset")));
  }

  window.BookCraft = Object.assign(window.BookCraft || {}, { Icon: Icon, Button: Button, Badge: Badge, Card: Card, Field: Field, Tabs: Tabs, Sidebar: Sidebar, OutputCard: OutputCard, UploadZone: UploadZone, ChunkCard: ChunkCard, CitationCard: CitationCard, McpServerCard: McpServerCard, LeadsTable: LeadsTable, AgentGraph: AgentGraph, AgentConsole: AgentConsole, ReviewPanel: ReviewPanel, icons: Object.keys(P) });
})();
