import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FIELDS } from "../data/exampleData";

const SENSITIVITY_PILL = {
  Internal: "pill-int",
  Confidential: "pill-conf",
  Public: "pill-pub",
};

export default function GlossaryPage() {
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return FIELDS;
    return FIELDS.filter(
      (f) =>
        f.id.toLowerCase().includes(q) ||
        f.definition.toLowerCase().includes(q) ||
        f.owner.toLowerCase().includes(q)
    );
  }, [query]);

  const openField = FIELDS.find((f) => f.id === openId);

  return (
    <>
      <div className="panel-head">
        <h2>Glossary — Field-Level Data Dictionary</h2>
        <div className="hint">Deliverable #3</div>
      </div>
      <div className="search">
        <input
          placeholder="Search fields… e.g. plan-id (filters client-side, no server call)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <table>
        <thead>
          <tr>
            <th>Field ID</th>
            <th>Definition</th>
            <th>Owner</th>
            <th>Sensitivity</th>
            <th>Used In</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((f) => (
            <tr
              key={f.id}
              className={"grow" + (openId === f.id ? " sel" : "")}
              onClick={() => setOpenId(openId === f.id ? null : f.id)}
            >
              <td className="fid">{f.id}</td>
              <td>{f.definition}</td>
              <td>{f.owner}</td>
              <td>
                <span className={"pill " + (SENSITIVITY_PILL[f.sensitivity] || "pill-int")}>
                  {f.sensitivity}
                </span>
              </td>
              <td>
                <div className="used-list">
                  {f.usedIn.map((iid) => (
                    <Link
                      key={iid}
                      className="used-chip"
                      to={`/interfaces?id=${iid}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {iid}
                    </Link>
                  ))}
                </div>
              </td>
              <td className="viewlink">View full record ▸</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={6} className="no-results">No fields match "{query}".</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="foot-note">
        A static HTML table plus an embedded JSON index — the search box filters rows
        in the browser, nothing is queried from a server. Click a row (try plan-id) to
        see the full record.
      </div>

      {openField && (
        <div className="record open">
          <div className="record-head">
            <div>
              <div className="record-title">{openField.id}</div>
              <div className="record-sub">
                Business term: <em>{openField.businessTerm}</em> &nbsp;·&nbsp; Object:{" "}
                <em>{openField.object}</em>
              </div>
            </div>
            <div className={"pill " + (SENSITIVITY_PILL[openField.sensitivity] || "pill-int")}>
              {openField.sensitivity}
            </div>
          </div>
          <div className="record-grid">
            <div>
              <h4>Definition</h4>
              <p>{openField.definition}</p>
            </div>
            <div>
              <h4>Data Type &amp; Format</h4>
              <p>{openField.dataType}</p>
            </div>
            <div>
              <h4>Field Length</h4>
              <p>{openField.length}</p>
            </div>
            <div>
              <h4>Allowed Values</h4>
              <p>{openField.allowedValues}</p>
            </div>
            <div>
              <h4>Mandatory / Conditional</h4>
              <p>{openField.mandatory}</p>
            </div>
            <div>
              <h4>Source System</h4>
              <p>{openField.sourceSystem}</p>
            </div>
            <div>
              <h4>Target Systems</h4>
              <p>{openField.targetSystems}</p>
            </div>
            <div>
              <h4>Data Ownership</h4>
              <p>{openField.owner}</p>
            </div>
            <div>
              <h4>Data Sensitivity Classification</h4>
              <p>{openField.sensitivity}</p>
            </div>
            <div>
              <h4>Transformation Rules</h4>
              <p>{openField.transformationRules}</p>
            </div>
            <div>
              <h4>Data Quality Rules</h4>
              <p>{openField.dataQualityRules}</p>
            </div>
            <div>
              <h4>Used In</h4>
              <p>
                <div className="used-list">
                  {openField.usedIn.map((iid) => (
                    <Link key={iid} className="used-chip" to={`/interfaces?id=${iid}`}>
                      {iid}
                    </Link>
                  ))}
                </div>
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
