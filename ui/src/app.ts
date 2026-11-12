// Belegfluss review UI.
//
// Security: documents come from outside the company, so every piece of data is inserted as
// text (textContent), never as HTML. A manipulated description on an invoice cannot inject
// markup or script into this page. tests/test_ui.py checks that innerHTML is never used.

// ---------- API types (mirror the FastAPI models) ----------

type Decision = "approve" | "review";
type Status = "open" | "auto_approved" | "approved" | "rejected";

interface Finding {
  finding_id: string;
  type: string;
  position: number | null;
  sku: string | null;
  expected: string | null;
  actual: string | null;
  clause_id: string | null;
  quote: string | null;
  explanation_de: string;
  verified: boolean;
  verification_note: string | null;
}

interface Issue {
  code: string;
  message: string;
}

interface TraceStep {
  step: string;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  detail: string | null;
}

interface MatchResult {
  invoice_number: string;
  supplier_id: string;
  supplier_name: string | null;
  po_number: string;
  decision: Decision;
  findings: Finding[];
  issues: Issue[];
  adjudicator: string;
  llm_input_tokens: number;
  llm_output_tokens: number;
  trace: TraceStep[];
  duration_ms: number;
  estimated_cost_usd: number | null;
}

interface MatchRecord {
  match_id: string;
  created_at: string;
  result: MatchResult;
  status: Status;
  reviewer: string | null;
  comment: string | null;
  decided_at: string | null;
}

interface DemoSet {
  set_id: string;
  invoice_file: string;
  delivery_note_file: string;
}

interface Stats {
  matches: number;
  by_status: Record<string, number>;
  auto_approval_rate: number | null;
  avg_duration_ms: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  estimated_cost_usd: number | null;
}

// ---------- Wording (German, for accounts payable) ----------

const FINDING_LABELS: Record<string, string> = {
  price_above_contract: "Preis über Vertrag",
  volume_discount_missing: "Mengenrabatt fehlt",
  quantity_exceeds_delivery: "Menge über Lieferung",
  item_not_ordered: "Nicht bestellt",
  wrong_vat_rate: "Falscher USt-Satz",
  totals_inconsistent: "Summen nicht schlüssig",
  payment_terms_deviation: "Zahlungsbedingungen abweichend",
  bank_details_changed: "Bankverbindung geändert",
};

const ISSUE_LABELS: Record<string, string> = {
  unknown_order: "Bestellnummer unbekannt",
  order_mismatch: "Bestellnummern passen nicht zusammen",
  delivery_note_mismatch: "Lieferscheinnummer passt nicht",
  due_date_inconsistent: "Fälligkeit passt nicht zum Zahlungsziel",
  issue_date_implausible: "Rechnungsdatum unplausibel",
  duplicate_invoice: "Rechnung bereits verarbeitet",
  extraction_warning: "Hinweis beim Auslesen",
  suspicious_content: "Verdächtiger Inhalt im Dokument",
  iban_unreadable: "IBAN nicht lesbar",
};

const STEP_LABELS: Record<string, string> = {
  extract_invoice: "Rechnung auslesen",
  extract_delivery_note: "Lieferschein auslesen",
  rules: "Regeln prüfen",
  plausibility: "Plausibilität",
  retrieve: "Vertrag durchsuchen",
  adjudicate: "Abweichungen bewerten",
  verify: "Belege prüfen",
  decide: "Entscheidung",
};

const STATUS_LABELS: Record<Status, string> = {
  open: "Offen",
  auto_approved: "Automatisch freigegeben",
  approved: "Freigegeben",
  rejected: "Abgelehnt",
};

// ---------- DOM helpers: text only ----------

type Child = Node | string | null | undefined | false;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: { class?: string; text?: string; attrs?: Record<string, string> } = {},
  children: Child[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (props.class) node.className = props.class;
  if (props.text !== undefined) node.textContent = props.text;
  for (const [name, value] of Object.entries(props.attrs ?? {})) node.setAttribute(name, value);
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function byId<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element #${id}`);
  return node as T;
}

const numberDe = new Intl.NumberFormat("de-DE");
const costDe = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 4, maximumFractionDigits: 5 });

// ---------- API ----------

class ApiError extends Error {}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown; error_id?: string };
      if (typeof body.detail === "string") detail = body.detail;
      if (body.error_id) detail += ` (Fehler-ID ${body.error_id})`;
    } catch {
      // keep the status line
    }
    throw new ApiError(detail);
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function upload(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const stored = await api<{ document_id: string }>("/v1/documents", { method: "POST", body: form });
  return stored.document_id;
}

// ---------- Feedback ----------

function showError(message: string): void {
  const banner = byId("message");
  banner.className = "message message-error";
  banner.textContent = message;
  banner.hidden = false;
}

function showNotice(message: string): void {
  const banner = byId("message");
  banner.className = "message message-ok";
  banner.textContent = message;
  banner.hidden = false;
}

function clearMessage(): void {
  byId("message").hidden = true;
}

async function busy(button: HTMLButtonElement, label: string, work: () => Promise<void>) {
  const original = button.textContent ?? "";
  button.disabled = true;
  button.textContent = label;
  clearMessage();
  try {
    await work();
  } catch (error) {
    showError(error instanceof Error ? error.message : String(error));
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

// ---------- Stats ----------

async function renderStats(): Promise<void> {
  const stats = await api<Stats>("/v1/stats");
  const items: [string, string][] = [
    ["Geprüfte Rechnungen", numberDe.format(stats.matches)],
    [
      "Automatisch freigegeben",
      stats.auto_approval_rate === null ? "–" : `${Math.round(stats.auto_approval_rate * 100)} %`,
    ],
    ["Offen", numberDe.format(stats.by_status["open"] ?? 0)],
    ["Ø Dauer", stats.avg_duration_ms === null ? "–" : `${numberDe.format(stats.avg_duration_ms)} ms`],
    ["Tokens", numberDe.format(stats.total_input_tokens + stats.total_output_tokens)],
  ];
  if (stats.estimated_cost_usd !== null) {
    items.push(["Kosten (geschätzt)", `${costDe.format(stats.estimated_cost_usd)} $`]);
  }
  byId("stats").replaceChildren(
    ...items.map(([label, value]) =>
      el("div", { class: "stat" }, [el("dt", { text: label }), el("dd", { text: value })]),
    ),
  );
}

// ---------- Demo sets ----------

function formatOf(file: string): string {
  const ext = file.split(".").pop() ?? "";
  return { xml: "XML", pdf: "PDF", png: "Scan" }[ext] ?? ext.toUpperCase();
}

async function renderDemoSets(): Promise<void> {
  const sets = await api<DemoSet[]>("/v1/demo/sets");
  const list = byId("demo-sets");
  if (sets.length === 0) {
    list.replaceChildren(el("p", { class: "empty", text: "Auf diesem Server sind keine Beispiele installiert." }));
    return;
  }
  list.replaceChildren(
    ...sets.map((set) => {
      const button = el("button", { class: "button-quiet", text: "Prüfen", attrs: { type: "button" } });
      button.addEventListener("click", () =>
        busy(button, "Prüfe …", async () => {
          const record = await api<MatchRecord>(`/v1/demo/sets/${encodeURIComponent(set.set_id)}/match`, {
            method: "POST",
          });
          await afterMatch(record);
        }),
      );
      return el("li", { class: "demo-set" }, [
        el("span", { class: "demo-name", text: set.set_id }),
        el("span", {
          class: "demo-formats",
          text: `Rechnung ${formatOf(set.invoice_file)}, Lieferschein ${formatOf(
            set.delivery_note_file,
          )}`,
        }),
        button,
      ]);
    }),
  );
}

// ---------- Own documents ----------

function setupUpload(): void {
  const form = byId<HTMLFormElement>("upload-form");
  const button = byId<HTMLButtonElement>("upload-button");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const invoice = byId<HTMLInputElement>("invoice-file").files?.[0];
    const note = byId<HTMLInputElement>("note-file").files?.[0];
    if (!invoice || !note) {
      showError("Bitte eine Rechnung und einen Lieferschein auswählen.");
      return;
    }
    void busy(button, "Prüfe …", async () => {
      const [invoiceId, noteId] = [await upload(invoice), await upload(note)];
      const record = await postJson<MatchRecord>("/v1/matches", {
        invoice_document_id: invoiceId,
        delivery_note_document_id: noteId,
      });
      form.reset();
      await afterMatch(record);
    });
  });
}

// ---------- Review queue ----------

async function renderQueue(): Promise<void> {
  const queue = await api<MatchRecord[]>("/v1/review-queue");
  byId("queue-count").textContent = `(${queue.length})`;
  const list = byId("queue");
  if (queue.length === 0) {
    list.replaceChildren(
      el("p", { class: "empty", text: "Keine offenen Rechnungen. Prüfen Sie ein Beispiel, um zu beginnen." }),
    );
    return;
  }
  list.replaceChildren(
    ...queue.map((record) => {
      const item = el("button", { class: "queue-item", attrs: { type: "button" } }, [
        el("span", {
          class: "queue-invoice",
          text: `Rechnung ${record.result.invoice_number}${
            record.result.supplier_name ? `, ${record.result.supplier_name}` : ""
          }`,
        }),
        el("span", {
          class: "queue-reason",
          text: record.result.findings.map((f) => FINDING_LABELS[f.type] ?? f.type).join(", ") ||
            record.result.issues.map((i) => ISSUE_LABELS[i.code] ?? i.code).join(", "),
        }),
      ]);
      item.addEventListener("click", () => renderSheet(record));
      return el("li", {}, [item]);
    }),
  );
}

// ---------- Result sheet ----------

function stamp(record: MatchRecord): HTMLElement {
  const approved = record.status === "approved" || record.status === "auto_approved";
  const rejected = record.status === "rejected";
  const text = rejected ? "ABGELEHNT" : approved ? "FREIGEGEBEN" : "ZU PRÜFEN";
  const tone = approved ? "stamp-green" : "stamp-red";
  return el("div", { class: `stamp ${tone}`, attrs: { role: "status" } }, [
    el("span", { class: "stamp-word", text }),
    el("span", {
      class: "stamp-note",
      text:
        record.status === "open"
          ? "offen"
          : record.status === "auto_approved"
            ? "automatisch"
            : `von ${record.reviewer ?? "?"}`,
    }),
  ]);
}

function findingBlock(finding: Finding): HTMLElement {
  const label = FINDING_LABELS[finding.type] ?? finding.type;
  const where = [
    finding.position ? `Position ${finding.position}` : null,
    finding.sku ? `Artikel ${finding.sku}` : null,
  ]
    .filter(Boolean)
    .join(", ");
  const evidence = finding.quote
    ? el("blockquote", { class: "evidence" }, [
        el("span", { class: "clause", text: finding.clause_id ?? "Vertrag" }),
        el("mark", { text: finding.quote }),
      ])
    : null;
  const verification = finding.verified
    ? el("p", { class: "verified", text: "Beleg im Vertrag geprüft" })
    : el("p", {
        class: "unverified",
        text: `Nicht belegt, manuell prüfen${finding.verification_note ? `: ${finding.verification_note}` : ""}`,
      });
  return el("li", { class: "finding" }, [
    el("h3", { text: label }),
    where ? el("p", { class: "where", text: where }) : null,
    el("p", { class: "explanation", text: finding.explanation_de }),
    evidence,
    verification,
  ]);
}

function traceBlock(result: MatchResult): HTMLElement {
  const longest = Math.max(1, ...result.trace.map((s) => s.duration_ms));
  const rows = result.trace.map((step) => {
    const bar = el("span", { class: "bar" });
    bar.style.width = `${Math.max(2, Math.round((step.duration_ms / longest) * 100))}%`;
    const tokens = step.input_tokens + step.output_tokens;
    return el("li", { class: "trace-row" }, [
      el("span", { class: "trace-step", text: STEP_LABELS[step.step] ?? step.step }),
      el("span", { class: "trace-bar" }, [bar]),
      el("span", {
        class: "trace-value",
        text: `${numberDe.format(step.duration_ms)} ms${tokens ? `, ${numberDe.format(tokens)} Tokens` : ""}`,
      }),
    ]);
  });
  const cost =
    result.estimated_cost_usd === null ? "" : `, geschätzt ${costDe.format(result.estimated_cost_usd)} $`;
  return el("details", { class: "trace" }, [
    el("summary", {
      text: `Ablauf: ${numberDe.format(result.duration_ms)} ms, ${numberDe.format(
        result.llm_input_tokens + result.llm_output_tokens,
      )} Tokens${cost}`,
    }),
    el("ol", {}, rows),
  ]);
}

function decisionForm(record: MatchRecord): HTMLElement | null {
  if (record.status !== "open") {
    if (!record.reviewer) return null;
    return el("p", {
      class: "decided",
      text: `${STATUS_LABELS[record.status]} von ${record.reviewer}${record.comment ? `: „${record.comment}“` : ""}`,
    });
  }
  const reviewer = el("input", {
    attrs: { id: "reviewer", name: "reviewer", required: "", autocomplete: "name", maxlength: "100" },
  });
  reviewer.value = localStorage.getItem("belegfluss.reviewer") ?? "";
  const comment = el("textarea", { attrs: { id: "comment", name: "comment", rows: "2", maxlength: "2000" } });
  const approve = el("button", { class: "button-approve", text: "Freigeben", attrs: { type: "button" } });
  const reject = el("button", { class: "button-reject", text: "Ablehnen", attrs: { type: "button" } });

  const decide = (approveIt: boolean, button: HTMLButtonElement) =>
    busy(button, approveIt ? "Gebe frei …" : "Lehne ab …", async () => {
      const name = reviewer.value.trim();
      if (!name) throw new ApiError("Bitte Ihren Namen als Prüfer eintragen.");
      localStorage.setItem("belegfluss.reviewer", name);
      const decided = await postJson<MatchRecord>(`/v1/matches/${encodeURIComponent(record.match_id)}/decision`, {
        approve: approveIt,
        reviewer: name,
        comment: comment.value.trim() || null,
      });
      showNotice(approveIt ? "Freigegeben." : "Abgelehnt.");
      renderSheet(decided);
      await Promise.all([renderQueue(), renderStats()]);
    });
  approve.addEventListener("click", () => void decide(true, approve));
  reject.addEventListener("click", () => void decide(false, reject));

  return el("form", { class: "decision", attrs: { "aria-label": "Entscheidung" } }, [
    el("label", { text: "Prüfer", attrs: { for: "reviewer" } }),
    reviewer,
    el("label", { text: "Kommentar (optional)", attrs: { for: "comment" } }),
    comment,
    el("div", { class: "decision-buttons" }, [reject, approve]),
  ]);
}

function renderSheet(record: MatchRecord): void {
  const result = record.result;
  const findings = result.findings.length
    ? el("section", {}, [
        el("h2", { text: `Abweichungen (${result.findings.length})` }),
        el("ul", { class: "findings" }, result.findings.map(findingBlock)),
      ])
    : el("p", { class: "all-clear", text: "Rechnung, Lieferschein und Bestellung stimmen überein." });
  const issues = result.issues.length
    ? el("section", {}, [
        el("h2", { text: "Hinweise" }),
        el(
          "ul",
          { class: "issues" },
          result.issues.map((issue) =>
            el("li", {}, [
              el("strong", { text: ISSUE_LABELS[issue.code] ?? issue.code }),
              el("span", { text: ` ${issue.message}` }),
            ]),
          ),
        ),
      ])
    : null;

  byId("sheet").replaceChildren(
    el("article", { class: "document" }, [
      stamp(record),
      el("h2", { class: "document-title", text: `Rechnung ${result.invoice_number}` }),
      el("dl", { class: "document-facts" }, [
        el("dt", { text: "Lieferant" }),
        el("dd", {
          text: result.supplier_name ? `${result.supplier_name} (${result.supplier_id})` : result.supplier_id,
        }),
        el("dt", { text: "Bestellung" }),
        el("dd", { text: result.po_number }),
        el("dt", { text: "Geprüft am" }),
        el("dd", { text: new Date(record.created_at).toLocaleString("de-DE") }),
      ]),
      findings,
      issues,
      decisionForm(record),
      traceBlock(result),
    ]),
  );
}

async function afterMatch(record: MatchRecord): Promise<void> {
  renderSheet(record);
  await Promise.all([renderQueue(), renderStats()]);
}

// ---------- Start ----------

async function start(): Promise<void> {
  setupUpload();
  try {
    await Promise.all([renderStats(), renderDemoSets(), renderQueue()]);
  } catch (error) {
    showError(error instanceof Error ? error.message : String(error));
  }
}

void start();
