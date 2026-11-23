import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import Chat from "./pages/Chat";
import Documents from "./pages/Documents";
import Login from "./pages/Login";
import Search from "./pages/Search";
import Users from "./pages/Users";
import "./styles.css";

const Analytics = lazy(() => import("./pages/Analytics"));
const Evaluation = lazy(() => import("./pages/Evaluation"));

function Guard({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { user, loading, can } = useAuth();
  if (loading) return <div className="empty">Loading…</div>;
  if (!user) return <Login />;
  if (admin && !can("admin")) return <Navigate to="/chat" replace />;
  return <Suspense fallback={<div className="empty">Loading…</div>}>{children}</Suspense>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Guard><Layout /></Guard>}>
            <Route path="/chat" element={<Chat />} />
            <Route path="/search" element={<Search />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/evaluation" element={<Evaluation />} />
            <Route path="/analytics" element={<Guard admin><Analytics /></Guard>} />
            <Route path="/users" element={<Guard admin><Users /></Guard>} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
);
