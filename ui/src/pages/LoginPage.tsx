import { FormEvent, useState } from "react";
import { api } from "../api";

export default function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username.trim(), password);
      onLogin();
    } catch (err: any) {
      setError(err.message ?? "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="loginwrap">
      <form className="logincard" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 4 }}>
          ml-<span>party</span>
        </div>
        <div className="muted small" style={{ marginBottom: 14 }}>
          sign in to this store
        </div>
        <input
          type="text"
          placeholder="username"
          autoFocus
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password"
          placeholder="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="loginerror">{error}</div>}
        <button className="primary" type="submit" disabled={busy || !username || !password}>
          sign in
        </button>
      </form>
    </div>
  );
}
