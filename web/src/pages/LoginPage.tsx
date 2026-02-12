import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

export const LoginPage = () => {
  const { status, login, mockLogin, canUseFirebaseAuth } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (status === 'authenticated') {
      const destination =
        (location.state as { from?: string } | null)?.from ?? '/watchlist';
      navigate(destination, { replace: true });
    }
  }, [status, navigate, location.state]);

  const handleLogin = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setErrorMessage('');
    setIsSubmitting(true);

    try {
      await login({ email: email.trim(), password });
    } catch (error) {
      if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage('ログインに失敗しました。');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMockLogin = async (): Promise<void> => {
    setErrorMessage('');
    setIsSubmitting(true);

    try {
      await mockLogin();
    } catch {
      setErrorMessage('モックログインに失敗しました。');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="page-shell centered">
      <section className="login-card panel">
        <h1>kabu_per_bot 管理画面</h1>
        <p className="muted">Firebase Auth でログインし、ウォッチリストを管理します。</p>

        <form onSubmit={handleLogin} className="login-form">
          <label>
            メールアドレス
            <input
              type="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
              required
              disabled={!canUseFirebaseAuth || isSubmitting}
            />
          </label>

          <label>
            パスワード
            <input
              type="password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
              required
              disabled={!canUseFirebaseAuth || isSubmitting}
            />
          </label>

          <button type="submit" className="primary" disabled={!canUseFirebaseAuth || isSubmitting}>
            {isSubmitting ? '処理中...' : 'Firebaseでログイン'}
          </button>
        </form>

        {!canUseFirebaseAuth && (
          <div className="notice-box">
            <p>Firebase設定が未指定のためモック認証で動作します。</p>
            <button type="button" className="secondary" onClick={handleMockLogin} disabled={isSubmitting}>
              モックログイン
            </button>
          </div>
        )}

        {errorMessage && <p className="error-text">{errorMessage}</p>}
      </section>
    </main>
  );
};
