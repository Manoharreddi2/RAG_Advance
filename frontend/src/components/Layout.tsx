import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { BarChart3, FileText, FlaskConical, LogOut, Menu, MessagesSquare, Moon, Search, Sun, Users } from "lucide-react";
import { useAuth } from "../auth";

function useTheme() {
  const [theme, setTheme] = useState<string>(() => { try { return localStorage.getItem("edi_theme") ?? ""; } catch { return ""; } });
  const apply = (t: string) => {
    setTheme(t);
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("edi_theme", t); } catch { /* ignore */ }
  };
  if (theme && document.documentElement.dataset.theme !== theme) document.documentElement.dataset.theme = theme;
  const dark = theme ? theme === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return { dark, toggle: () => apply(dark ? "light" : "dark") };
}

export function Logo() {
  return <img src="/favicon.svg" width={28} height={28} alt="" />;
}

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { dark, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const links = [
    { to: "/chat", label: "Ask AI", icon: MessagesSquare },
    { to: "/search", label: "Search", icon: Search },
    { to: "/documents", label: "Documents", icon: FileText },
    { to: "/evaluation", label: "Evaluation", icon: FlaskConical },
    ...(can("admin") ? [{ to: "/analytics", label: "Analytics", icon: BarChart3 }, { to: "/users", label: "Users", icon: Users }] : []),
  ];
  return (
    <div className="shell">
      <div className="mobile-bar">
        <button className="icon-btn" aria-label="Menu" onClick={() => setOpen(!open)}><Menu size={18} /></button>
        <Logo /><b>Document Intelligence</b>
      </div>
      <aside className={`sidebar ${open ? "open" : ""}`} onClick={() => setOpen(false)}>
        <div className="brand"><Logo /><div>Document Intelligence<small>Enterprise RAG platform</small></div></div>
        <nav className="nav stack" style={{ gap: 2 }}>
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to}><Icon size={17} />{label}</NavLink>
          ))}
        </nav>
        <div className="spacer" />
        <div className="userbox">
          <div className="avatar">{(user?.full_name || user?.email || "?")[0].toUpperCase()}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{user?.full_name || user?.email}</div>
            <div className="faint" style={{ fontSize: 12 }}>{user?.role}</div>
          </div>
          <button className="icon-btn" title="Toggle theme" aria-label="Toggle theme" onClick={(e) => { e.stopPropagation(); toggle(); }}>
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button className="icon-btn" title="Sign out" aria-label="Sign out" onClick={logout}><LogOut size={16} /></button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
