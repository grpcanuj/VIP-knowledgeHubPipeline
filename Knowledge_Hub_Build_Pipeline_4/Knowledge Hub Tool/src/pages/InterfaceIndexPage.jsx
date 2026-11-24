import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FIELDS, INTERFACES } from "../data/exampleData";

export default function InterfaceIndexPage() {
  const [searchParams] = useSearchParams();
  const idFromQuery = searchParams.get("id");

  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(idFromQuery || "INT-102");

  // If we arrived here via a "used in" link (e.g. from the Glossary page),
  // jump straight to that interface even if this page was already mounted.
  useEffect(() => {
    if (idFromQuery) {
      setSelectedId(idFromQuery);
      setQuery("");
    }
  }, [idFromQuery]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return INTERFACES;
    return INTERFACES.filter(
      (i) =>
        i.id.toLowerCase().includes(q) ||
        i.name.toLowerCase().includes(q) ||
        i.source.toLowerCase().includes(q) ||
        i.target.toLowerCase().includes(q)
    );
  }, [query]);

  const selected = INTERFACES.find((i) => i.id === selectedId);

  return (
    <>
      <div className="panel-head">
        <h2>Interface Index — Interface &amp; Message Catalogue</h2>
        <div className="hint">Deliverable #4</div>
      </div>
      <div className="search">
        <input
          placeholder="Search interfaces… e.g. Shippeo (filters client-side, no server call)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <table>
        <thead>
          <tr>
            <th>Interface ID</th>
            <th>Name</th>
            <th>Source → Target</th>
            <th>Type</th>
            <th>Owner</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((i) => (
            <tr
              key={i.id}
              className={"grow" + (selectedId === i.id ? " sel" : "")}
              onClick={() => setSelectedId(i.id)}
            >
              <td className="fid">{i.id}</td>
              <td>{i.name}</td>
              <td>{i.source} → {i.target}</td>
              <td>{i.type}</td>
              <td>{i.owner}</td>
              <td className="viewlink">View detail ▸</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={6} className="no-results">No interfaces match "{query}".</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="foot-note">
        The Hub holds the metadata (owner, fields, linkage) and links out to each
        team's own published API docs. Only an interface with no published spec of
        its own gets an embedded fallback view <span className="fallback-badge">fallback</span> — that's the
        exception, not the default.
      </div>

      {selected && (
        <div className="ib-detail">
          <div className="ib-detail-head">
            <div>
              <span className="path">{selected.path}</span>
              {selected.usedByRequirement && (
                <Link className="trace-chip" to="/traceability">
                  traces to {selected.usedByRequirement} ↗
                </Link>
              )}
            </div>
          </div>
          <div className="owner-line">
            Owner: {selected.owner} &nbsp;·&nbsp; Type: {selected.type} &nbsp;·&nbsp; Spec
            version: {selected.specVersion} &nbsp;·&nbsp; Frequency: {selected.frequency}
          </div>
          <table className="meta-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Type</th>
                <th>Owner (Glossary)</th>
              </tr>
            </thead>
            <tbody>
              {selected.fields.map((fid) => {
                const field = FIELDS.find((f) => f.id === fid);
                return (
                  <tr key={fid}>
                    <td className="fid">
                      <Link to="/glossary">{fid}</Link>
                    </td>
                    <td>{field ? field.dataType : "—"}</td>
                    <td>{field ? field.owner : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="linkout">
            <div>
              <div className="l1">Full API specification</div>
              <div className="l2">
                Published and maintained by the {selected.owner.split("(")[0].split("—")[0].trim()} team's own docs site
              </div>
            </div>
            <a href="#" onClick={(e) => e.preventDefault()}>View full spec ↗</a>
          </div>
        </div>
      )}
    </>
  );
}
