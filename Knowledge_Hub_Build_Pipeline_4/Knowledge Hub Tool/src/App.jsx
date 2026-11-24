import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import GlossaryPage from "./pages/GlossaryPage";
import InterfaceIndexPage from "./pages/InterfaceIndexPage";
import FlowViewPage from "./pages/FlowViewPage";
import TraceabilityPage from "./pages/TraceabilityPage";

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/glossary" replace />} />
          <Route path="glossary" element={<GlossaryPage />} />
          <Route path="interfaces" element={<InterfaceIndexPage />} />
          <Route path="flows" element={<FlowViewPage />} />
          <Route path="traceability" element={<TraceabilityPage />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
