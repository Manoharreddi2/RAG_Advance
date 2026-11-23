import { useEffect, useState } from "react";
import { api, type Role, type User } from "../api";
import { useAuth } from "../auth";
import { ago } from "../util";

export default function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.users().then(setUsers).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  const update = (id: string, body: Partial<User>) => api.updateUser(id, body).then(load).catch((e) => setError(e.message));

  return (
    <div className="page">
      <div className="page-head"><div><h1>Users &amp; roles</h1><p>Viewers can search and chat · editors can also upload and manage documents · admins manage users and see analytics.</p></div></div>
      {error && <div className="alert">{error}</div>}
      <div className="card table-wrap"><table>
        <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Joined</th></tr></thead>
        <tbody>{users.map((u) => (
          <tr key={u.id}>
            <td><b>{u.full_name || u.email}</b><div className="faint">{u.email}</div></td>
            <td><select value={u.role} disabled={u.id === me?.id} aria-label={`Role for ${u.email}`} onChange={(e) => update(u.id, { role: e.target.value as Role })}>
              <option value="viewer">viewer</option><option value="editor">editor</option><option value="admin">admin</option></select></td>
            <td><label className="check"><input type="checkbox" checked={u.is_active} disabled={u.id === me?.id} onChange={(e) => update(u.id, { is_active: e.target.checked })} />{u.is_active ? "active" : "disabled"}</label></td>
            <td className="faint">{ago(u.created_at)}</td>
          </tr>))}</tbody>
      </table></div>
    </div>
  );
}
