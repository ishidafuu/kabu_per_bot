import { useEffect, useMemo, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuth } from '../auth/useAuth';

interface HelpDocItem {
  id: string;
  title: string;
  summary: string;
  source_path: string;
  web_path: string;
  web_path_encoded: string;
}

interface HelpDocCategory {
  key: string;
  label: string;
  items: HelpDocItem[];
}

interface HelpDocIndex {
  generated_at: string;
  categories: HelpDocCategory[];
}

const findDocById = (index: HelpDocIndex | null, id: string): HelpDocItem | null => {
  if (!index || !id) {
    return null;
  }

  for (const category of index.categories) {
    const matched = category.items.find((item) => item.id === id);
    if (matched) {
      return matched;
    }
  }

  return null;
};

const getFirstDocId = (index: HelpDocIndex | null): string => {
  if (!index) {
    return '';
  }
  const preferredId = 'docs/04_利用ガイド/トレーダー向け_使い方手順書.md';
  const preferred = findDocById(index, preferredId);
  if (preferred) {
    return preferred.id;
  }
  return index.categories[0]?.items[0]?.id ?? '';
};

const formatGeneratedAt = (value: string): string => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString('ja-JP', {
    hour12: false,
    timeZone: 'Asia/Tokyo',
  });
};

export const UserGuidePage = () => {
  const { user, logout } = useAuth();

  const [index, setIndex] = useState<HelpDocIndex | null>(null);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [markdown, setMarkdown] = useState('');

  const [isIndexLoading, setIsIndexLoading] = useState(true);
  const [isDocLoading, setIsDocLoading] = useState(false);
  const [indexError, setIndexError] = useState('');
  const [docError, setDocError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const loadIndex = async (): Promise<void> => {
      setIsIndexLoading(true);
      setIndexError('');

      try {
        const response = await fetch('/help-docs/index.json', { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`index load failed: ${response.status}`);
        }

        const payload = (await response.json()) as HelpDocIndex;
        if (cancelled) {
          return;
        }

        setIndex(payload);
        setSelectedDocId((current) => current || getFirstDocId(payload));
      } catch {
        if (cancelled) {
          return;
        }
        setIndex(null);
        setSelectedDocId('');
        setIndexError('ヘルプドキュメント一覧を読み込めませんでした。');
      } finally {
        if (!cancelled) {
          setIsIndexLoading(false);
        }
      }
    };

    void loadIndex();

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedDoc = useMemo(() => findDocById(index, selectedDocId), [index, selectedDocId]);

  useEffect(() => {
    if (!selectedDoc) {
      setMarkdown('');
      return;
    }

    let cancelled = false;

    const loadMarkdown = async (): Promise<void> => {
      setIsDocLoading(true);
      setDocError('');

      try {
        const response = await fetch(`/help-docs/${selectedDoc.web_path_encoded}`, { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`doc load failed: ${response.status}`);
        }

        const text = await response.text();
        if (cancelled) {
          return;
        }

        setMarkdown(text);
      } catch {
        if (cancelled) {
          return;
        }
        setMarkdown('');
        setDocError('選択したドキュメント本文を読み込めませんでした。');
      } finally {
        if (!cancelled) {
          setIsDocLoading(false);
        }
      }
    };

    void loadMarkdown();

    return () => {
      cancelled = true;
    };
  }, [selectedDoc]);

  const generatedAt = index ? formatGeneratedAt(index.generated_at) : '-';

  return (
    <main className="page-shell">
      <header className="top-bar panel">
        <div>
          <h1>ヘルプ / ドキュメント</h1>
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

      <nav className="panel page-nav" aria-label="ページ遷移">
        <NavLink to="/dashboard" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          ダッシュボード
        </NavLink>
        <NavLink to="/watchlist" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          ウォッチリスト
        </NavLink>
        <NavLink to="/watchlist/history" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          履歴
        </NavLink>
        <NavLink to="/notifications/logs" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          通知ログ
        </NavLink>
        <NavLink to="/guide" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          使い方
        </NavLink>
      </nav>

      <section className="panel guide-panel">
        <h2>ドキュメント一覧</h2>
        <p className="muted">最終同期: {generatedAt}（JST）</p>
      </section>

      <section className="help-layout">
        <aside className="panel help-sidebar" aria-label="ヘルプドキュメント選択">
          {isIndexLoading && <p className="muted">ドキュメント一覧を読み込み中です...</p>}
          {indexError && <p className="error-text">{indexError}</p>}

          {!isIndexLoading && !indexError && index?.categories.map((category) => (
            <section key={category.key} className="help-category">
              <h3>{category.label}</h3>
              <div className="help-links">
                {category.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`help-link${item.id === selectedDocId ? ' active' : ''}`}
                    onClick={() => {
                      setSelectedDocId(item.id);
                    }}
                  >
                    <span>{item.title}</span>
                    {item.summary && <small>{item.summary}</small>}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </aside>

        <article className="panel help-content" aria-live="polite">
          {selectedDoc && (
            <div className="help-meta-row">
              <p className="muted">表示中: {selectedDoc.title}</p>
              <p className="muted">正本: {selectedDoc.source_path}</p>
            </div>
          )}

          {isDocLoading && <p className="muted">本文を読み込み中です...</p>}
          {docError && <p className="error-text">{docError}</p>}

          {!isDocLoading && !docError && markdown && (
            <div className="help-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
          )}
        </article>
      </section>
    </main>
  );
};
