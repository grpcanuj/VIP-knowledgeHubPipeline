import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { REQUIREMENTS, INTERFACES } from "../data/exampleData";

function EvidenceCard({ evidence }) {
  return (
    <div className={"tcard tcard-evidence" + (evidence.status === "pending" ? " pending" : "")}>
      <h3>Evidence</h3>
      <div className="status-line">
        <span className="dotb"></span>
        {evidence.statusLabel}
      </div>
      <div className="ev-fields">
        {evidence.fields.map((f) => (
          <div className="ef" key={f.label}>
            <div className="ef-label">{f.label}</div>
            <div className={"ef-value" + (f.note ? " note" : "")}>
              {f.link ? <a href="#" onClick={(e) => e.preventDefault()}>{f.value} ↗</a> : f.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TwoLegChain() {
  const req102 = REQUIREMENTS.find((r) => r.id === "REQ-102");
  const req103 = REQUIREMENTS.find((r) => r.id === "REQ-103");
  const int102 = INTERFACES.find((i) => i.id === req102.interface);
  const int103 = INTERFACES.find((i) => i.id === req103.interface);

  return (
    <div className="trace-expand">
      <div className="trace-flow">
        <div className="trace-flow-head">
          <span className="trace-flow-tag outbound">Leg 1 — Outbound</span>
          <span className="trace-flow-title">{req102.legTitle}</span>
          <span className="trace-flow-req">{req102.id}</span>
        </div>
        <div className="trace-chain">
          <div className="tcard">
            <h3>Requirement</h3>
            <div className="main">{req102.id}</div>
            <div className="sub">{req102.text}</div>
          </div>
          <div className="tarrow">→</div>
          <div className="tcard">
            <h3>Interface</h3>
            <div className="main">{int102.name}</div>
            <div className="sub">
              <Link to="/interfaces">{int102.id}</Link> · Sends the created plan for execution
            </div>
          </div>
          <div className="tarrow">→</div>
          <div className="tcard">
            <h3>Test Case</h3>
            <div className="main">{req102.testCase}</div>
            <div className="sub">Tower 2 automated contract test</div>
          </div>
          <div className="tarrow">→</div>
          <EvidenceCard evidence={req102.evidence} />
        </div>
      </div>

      <div className="trace-link-note">
        <div className="ln-line"></div>
        <span className="txt">
          Same business exchange — Leg 2 is the asynchronous response Shippeo sends
          back once the plan above is received.
        </span>
      </div>

      <div className="trace-flow">
        <div className="trace-flow-head">
          <span className="trace-flow-tag inbound">Leg 2 — Inbound</span>
          <span className="trace-flow-title">{req103.legTitle}</span>
          <span className="trace-flow-req">{req103.id}</span>
        </div>
        <div className="trace-chain">
          <div className="tcard">
            <h3>Requirement</h3>
            <div className="main">{req103.id}</div>
            <div className="sub">{req103.text}</div>
          </div>
          <div className="tarrow">→</div>
          <div className="tcard">
            <h3>Interface</h3>
            <div className="main">{int103.name}</div>
            <div className="sub">
              <Link to="/interfaces">{int103.id}</Link> · Confirms receipt/acceptance of the plan
            </div>
          </div>
          <div className="tarrow">→</div>
          <div className="tcard">
            <h3>Test Case</h3>
            <div className="main">{req103.testCase}</div>
            <div className="sub">Tower 2 automated contract test</div>
          </div>
          <div className="tarrow">→</div>
          <EvidenceCard evidence={req103.evidence} />
        </div>
      </div>
    </div>
  );
}

export default function TraceabilityPage() {
  const [query, setQuery] = useState("");
  const [expandedGroup, setExpandedGroup] = useState("TMS-SHIPPEO");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return REQUIREMENTS;
    return REQUIREMENTS.filter(
      (r) =>
        r.id.toLowerCase().includes(q) ||
        r.interface.toLowerCase().includes(q) ||
        r.text.toLowerCase().includes(q)
    );
  }, [query]);

  function handleRowClick(r) {
    if (r.legGroup) {
      setExpandedGroup(expandedGroup === r.legGroup ? null : r.legGroup);
    }
  }

  return (
    <>
      <div className="panel-head">
        <h2>Traceability — Requirement → Interface → Test → Evidence</h2>
        <div className="hint">Deliverable #6</div>
      </div>
      <div className="search">
        <input
          placeholder="Search requirements… e.g. REQ-102 or Shippeo (filters client-side, no server call)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <table>
        <thead>
          <tr>
            <th>Requirement</th>
            <th>Interface</th>
            <th>Test Case</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((r) => (
            <tr
              key={r.id}
              className={"grow" + (r.legGroup && expandedGroup === r.legGroup ? " sel" : "")}
              onClick={() => handleRowClick(r)}
            >
              <td className="fid">{r.id}</td>
              <td>{r.interface}</td>
              <td>{r.testCase}</td>
              <td>
                <span className={"pill " + (r.status === "passed" ? "pill-status-passed" : "pill-status-pending")}>
                  {r.statusLabel}
                </span>
              </td>
              <td className="viewlink">{r.legGroup ? "View evidence chain ▸" : "—"}</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={5} className="no-results">No requirements match "{query}".</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="foot-note">
        Full searchable table, one row per requirement. REQ-102 and REQ-103 belong to
        the same business exchange, so clicking either expands the combined two-leg
        evidence chain below.
      </div>

      {expandedGroup === "TMS-SHIPPEO" && <TwoLegChain />}

      <div className="foot-note">
        A static page compiled from the linked model at build time, citing the
        evidence pack from the relevant test cycle — not a live query — so it needs
        no backend to stay accurate. Leg 2 shows amber rather than red because the
        test executed correctly on the TMS side; it simply has no verdict yet, since
        Shippeo has not returned a confirmation within the observed window.
      </div>
    </>
  );
}
