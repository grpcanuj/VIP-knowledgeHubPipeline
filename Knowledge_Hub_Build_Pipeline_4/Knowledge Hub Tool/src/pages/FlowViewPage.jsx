import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { FLOWS, INTERFACES } from "../data/exampleData";

let mermaidInitialized = false;
function ensureMermaid() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    themeVariables: {
      primaryColor: "#E8ECFC",
      primaryBorderColor: "#3B5BDB",
      primaryTextColor: "#0B1F3A",
      lineColor: "#5B6770",
      fontFamily: "Arial, Helvetica Neue, sans-serif",
      fontSize: "13px",
    },
  });
  mermaidInitialized = true;
}

function FlowDiagram({ flow }) {
  const ref = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    ensureMermaid();
    let cancelled = false;
    const renderId = "flow-svg-" + flow.id;
    mermaid
      .render(renderId, flow.diagram)
      .then(({ svg }) => {
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [flow]);

  if (error) {
    return <div className="no-results">Could not render diagram: {error}</div>;
  }
  return <div className="flow-canvas" ref={ref} />;
}

export default function FlowViewPage() {
  const [selectedId, setSelectedId] = useState(null);
  const selected = FLOWS.find((f) => f.id === selectedId);

  if (!selected) {
    return (
      <>
        <div className="panel-head">
          <h2>Flow View — Choose a Flow</h2>
          <div className="hint">Deliverable #5</div>
        </div>
        <div className="flow-list">
          {FLOWS.map((f) => (
            <div key={f.id} className="flow-card" onClick={() => setSelectedId(f.id)}>
              <div className="fc-id">{f.id}</div>
              <div className="fc-name">{f.name}</div>
              <div className="fc-desc">{f.description}</div>
            </div>
          ))}
        </div>
        <div className="foot-note">
          Landing page lists every flow defined in the shared model. Select one to see
          its diagram, generated directly from that flow's YAML at build time.
        </div>
      </>
    );
  }

  return (
    <>
      <div className="panel-head">
        <h2>Flow View — {selected.name}</h2>
        <div className="hint">Deliverable #5</div>
      </div>
      <button className="back-link" onClick={() => setSelectedId(null)}>
        ← Back to all flows
      </button>
      <FlowDiagram flow={selected} />
      <div className="foot-note">
        Generated directly from the flow's YAML at build time — this is a plain
        rendered diagram, not a live graph. Interfaces in this flow:{" "}
        {selected.interfaces
          .map((id) => {
            const i = INTERFACES.find((x) => x.id === id);
            return i ? `${i.id} (${i.name})` : id;
          })
          .join(" · ")}
        .
      </div>
    </>
  );
}
