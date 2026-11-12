import { Navigate, Route, Routes } from "react-router-dom";

import { TokenGate } from "./auth/TokenGate";
import { AppShell } from "./components/AppShell";
import { AuditTrail } from "./pages/AuditTrail";
import { BalanceSheets } from "./pages/BalanceSheets";
import { EconomyExplorer } from "./pages/EconomyExplorer";
import { Experiments } from "./pages/Experiments";
import { HedgeActions } from "./pages/HedgeActions";
import { MarketPaths } from "./pages/MarketPaths";
import { ModelUsage } from "./pages/ModelUsage";
import { Overview } from "./pages/Overview";
import { PortfolioRisk } from "./pages/PortfolioRisk";
import { PricingDiagnostics } from "./pages/PricingDiagnostics";
import { ValidationIssues } from "./pages/ValidationIssues";
import { InflationcastLab } from "./pages/lab/InflationcastLab";
import { MarlLab } from "./pages/lab/MarlLab";
import { NeuralSdeLab } from "./pages/lab/NeuralSdeLab";
import { PdeSolverLab } from "./pages/lab/PdeSolverLab";
import { QMacroLab } from "./pages/lab/QMacroLab";
import { RecessionNetLab } from "./pages/lab/RecessionNetLab";
import { RlHedgeLab } from "./pages/lab/RlHedgeLab";

export default function App() {
  return (
    <TokenGate>
      <AppShell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/economy" element={<EconomyExplorer />} />
          <Route path="/balance-sheets" element={<BalanceSheets />} />
          <Route path="/market-paths" element={<MarketPaths />} />
          <Route path="/pricing" element={<PricingDiagnostics />} />
          <Route path="/hedge-actions" element={<HedgeActions />} />
          <Route path="/portfolio-risk" element={<PortfolioRisk />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="/audit-trail" element={<AuditTrail />} />
          <Route path="/validation-issues" element={<ValidationIssues />} />
          <Route path="/model-usage" element={<ModelUsage />} />
          <Route path="/lab/qmacro" element={<QMacroLab />} />
          <Route path="/lab/recessionnet" element={<RecessionNetLab />} />
          <Route path="/lab/inflationcast" element={<InflationcastLab />} />
          <Route path="/lab/neural-sde" element={<NeuralSdeLab />} />
          <Route path="/lab/pde-solver" element={<PdeSolverLab />} />
          <Route path="/lab/marl" element={<MarlLab />} />
          <Route path="/lab/rl-hedge" element={<RlHedgeLab />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </TokenGate>
  );
}
