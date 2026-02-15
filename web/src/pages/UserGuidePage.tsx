import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { USER_GUIDE_SECTIONS, USER_GUIDE_TITLE, USER_GUIDE_UPDATED_AT } from '../content/userGuide';

export const UserGuidePage = () => {
  const { user, logout } = useAuth();

  return (
    <main className="page-shell">
      <header className="top-bar panel">
        <div>
          <h1>使い方ガイド</h1>
          <p className="muted">ログイン中: {user?.email ?? 'unknown'}</p>
        </div>
        <div className="top-actions">
          <Link to="/dashboard" className="nav-link">
            ダッシュボードへ
          </Link>
          <Link to="/watchlist" className="nav-link">
            ウォッチリストへ
          </Link>
          <button type="button" className="ghost" onClick={() => void logout()}>
            ログアウト
          </button>
        </div>
      </header>

      <section className="panel guide-panel">
        <h2>{USER_GUIDE_TITLE}</h2>
        <p className="muted">最終更新: {USER_GUIDE_UPDATED_AT}（JST）</p>
      </section>

      <section className="guide-sections">
        {USER_GUIDE_SECTIONS.map((section) => (
          <article key={section.title} className="panel guide-section">
            <h2>{section.title}</h2>
            <ol className="guide-list">
              {section.body.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ol>
          </article>
        ))}
      </section>
    </main>
  );
};
