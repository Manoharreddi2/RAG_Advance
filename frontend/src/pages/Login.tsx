import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { Logo } from "../components/Layout";

export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name || undefined);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="row"><Logo /><div><h1>Document Intelligence</h1><div className="faint">Grounded answers from your documents</div></div></div>
        {error && <div className="alert" role="alert">{error}</div>}
        {mode === "register" && <label className="field">Full name<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>}
        <label className="field">Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
        <label className="field">Password<input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
        <button className="btn btn-primary" disabled={busy} style={{ justifyContent: "center" }}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="btn btn-ghost" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "No account? Register" : "Have an account? Sign in"}
        </button>
        {mode === "register" && <p className="faint" style={{ fontSize: 12 }}>The first account created becomes the administrator. Later accounts start as viewers.</p>}
      </form>
    </div>
  );
}
