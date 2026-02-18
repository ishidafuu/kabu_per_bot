import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AppLayout } from '../components/AppLayout';

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

const extractSectionTitles = (markdown: string): string[] => {
  const titles: string[] = [];
  const lines = markdown.split('\n');

  for (const line of lines) {
    const matched = line.match(/^##\s+(.+)$/);
    if (!matched) {
      continue;
    }

    const normalized = matched[1]
      .replace(/\[(.*?)\]\(.*?\)/g, '$1')
      .replace(/`/g, '')
      .replace(/^\d+[.)、]?\s*/, '')
      .trim();

    if (normalized) {
      titles.push(normalized);
    }
  }

  return titles;
};

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
  const sectionTitles = useMemo(() => extractSectionTitles(markdown), [markdown]);

  const scrollToSection = (title: string): void => {
    const headings = Array.from(document.querySelectorAll<HTMLElement>('.help-markdown h2'));
    const target = headings.find((heading) => {
      const text = heading.textContent?.trim();
      return text ? text.includes(title) : false;
    });

    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <AppLayout title="ヘルプ / ドキュメント">
      <section className="panel guide-panel">
        <h2>使い方ヘルプ</h2>
        <p className="muted">最終同期: {generatedAt}（JST）</p>
        <div className="help-summary-grid">
          <div className="help-summary-card">
            <h3>最短で始める</h3>
            <p className="muted">「3分で始める」を上から順に実施すれば初期設定が完了します。</p>
            <button type="button" className="ghost help-jump-button" onClick={() => scrollToSection('3分で始める')}>
              3分で始めるへ移動
            </button>
          </div>
          <div className="help-summary-card">
            <h3>銘柄設定を見直す</h3>
            <p className="muted">ticker形式・通知時間・常時通知の設定ルールを確認できます。</p>
            <button type="button" className="ghost help-jump-button" onClick={() => scrollToSection('入力ルール')}>
              入力ルールへ移動
            </button>
          </div>
          <div className="help-summary-card">
            <h3>通知トラブル確認</h3>
            <p className="muted">通知が来ないときの確認ポイントをすぐに見られます。</p>
            <button type="button" className="ghost help-jump-button" onClick={() => scrollToSection('よくあるトラブル')}>
              よくあるトラブルへ移動
            </button>
          </div>
        </div>
      </section>

      <section className="help-layout">
        <aside className="panel help-toc" aria-label="ガイド目次">
          <h3>目次</h3>
          <p className="muted">必要な項目だけ素早く確認できます。</p>
          {isIndexLoading && <p className="muted">ガイドを準備中です...</p>}
          {indexError && <p className="error-text">{indexError}</p>}
          {!isIndexLoading && !indexError && sectionTitles.length > 0 && (
            <div className="help-toc-links">
              {sectionTitles.map((title) => (
                <button
                  key={title}
                  type="button"
                  className="help-toc-link"
                  onClick={() => {
                    scrollToSection(title);
                  }}
                >
                  {title}
                </button>
              ))}
            </div>
          )}
        </aside>

        <article className="panel help-content" aria-live="polite">
          {selectedDoc && (
            <div className="help-meta-row">
              <p className="muted">表示中: トレーダー向けガイド</p>
              <p className="muted">最初に「3分で始める」だけ読めば基本操作は完了です。</p>
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
    </AppLayout>
  );
};
