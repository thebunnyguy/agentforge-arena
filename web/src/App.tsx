import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Overview } from "./pages/Overview";
import { Leaderboard } from "./pages/Leaderboard";
import { Agents } from "./pages/Agents";
import { AgentDetail } from "./pages/AgentDetail";
import { Tasks } from "./pages/Tasks";
import { TaskDetail } from "./pages/TaskDetail";
import { CellPage } from "./pages/CellPage";
import { RunPage } from "./pages/RunPage";
import { RunsExplorer } from "./pages/RunsExplorer";
import { Methodology } from "./pages/Methodology";
import { NewEvaluation } from "./pages/NewEvaluation";
import { Jobs } from "./pages/Jobs";
import { JobDetail } from "./pages/JobDetail";
import { JobResults } from "./pages/JobResults";
import { Settings } from "./pages/Settings";
import { Reports } from "./pages/Reports";
import { NotFound } from "./pages/NotFound";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          {/* Explorer (read-only) */}
          <Route path="/" element={<Overview />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/agent/:agent" element={<AgentDetail />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/task/:taskId" element={<TaskDetail />} />
          <Route path="/runs" element={<RunsExplorer />} />
          <Route path="/cell/:agent/:taskId" element={<CellPage />} />
          <Route path="/cell/:agent/:taskId/run/:idx" element={<RunPage />} />
          <Route path="/methodology" element={<Methodology />} />

          {/* Product (orchestrate) */}
          <Route path="/new" element={<NewEvaluation />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
          <Route path="/jobs/:jobId/results" element={<JobResults />} />
          <Route path="/jobs/:jobId/runs/:taskId/:idx" element={<RunPage />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/reports" element={<Reports />} />

          <Route path="/404" element={<NotFound />} />
          <Route path="*" element={<Navigate to="/404" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
