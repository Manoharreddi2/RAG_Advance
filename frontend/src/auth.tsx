import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler, type Role, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  can: (role: Role) => boolean;
}

const Ctx = createContext<AuthState | null>(null);
const RANK: Record<Role, number> = { viewer: 0, editor: 1, admin: 2 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!getToken());

  const logout = useCallback(() => { setToken(null); setUser(null); }, []);
  useEffect(() => { setUnauthorizedHandler(logout); }, [logout]);
  useEffect(() => {
    if (!getToken()) return;
    api.me().then(setUser).catch(logout).finally(() => setLoading(false));
  }, [logout]);

  const login = async (email: string, password: string) => {
    const r = await api.login(email, password);
    setToken(r.access_token);
    setUser(r.user);
  };
  const register = async (email: string, password: string, name?: string) => {
    const r = await api.register(email, password, name);
    setToken(r.access_token);
    setUser(r.user);
  };
  const can = (role: Role) => !!user && RANK[user.role] >= RANK[role];
  return <Ctx.Provider value={{ user, loading, login, register, logout, can }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
}
