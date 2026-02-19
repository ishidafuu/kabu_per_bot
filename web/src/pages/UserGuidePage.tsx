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

const TRADER_GUIDE_ID = 'docs/04_利用ガイド/トレーダー向け_使い方手順書.md';
const OPS_DETAIL_GUIDE_ID = 'docs/03_運用/ジョブ実行と通知抑制の詳細整理.md';
const OPS_QUICK_GUIDE_ID = 'docs/03_運用/ジョブ実行と通知抑制_早見表.md';

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
  const preferred = findDocById(index, TRADER_GUIDE_ID);
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
  const opsDetailDoc = useMemo(() => findDocById(index, OPS_DETAIL_GUIDE_ID), [index]);
  const opsQuickDoc = useMemo(() => findDocById(index, OPS_QUICK_GUIDE_ID), [index]);

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
  const firstSectionTitle = sectionTitles[0] ?? '';

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
            <h3>表示中ドキュメント</h3>
            <p className="muted">{selectedDoc?.title ?? '未選択'}</p>
            {firstSectionTitle && (
              <button type="button" className="ghost help-jump-button" onClick={() => scrollToSection(firstSectionTitle)}>
                最初の章へ移動
              </button>
            )}
          </div>
          <div className="help-summary-card">
            <h3>通知運用の詳細</h3>
            <p className="muted">ジョブ実行順序と通知抑制条件を詳細に確認できます。</p>
            {opsDetailDoc && (
              <button
                type="button"
                className="ghost help-jump-button"
                onClick={() => {
                  setSelectedDocId(opsDetailDoc.id);
                }}
              >
                詳細整理を開く
              </button>
            )}
          </div>
          <div className="help-summary-card">
            <h3>通知トラブルの早見</h3>
            <p className="muted">通知が来ない時の確認順を短時間で見直せます。</p>
            {opsQuickDoc && (
              <button
                type="button"
                className="ghost help-jump-button"
                onClick={() => {
                  setSelectedDocId(opsQuickDoc.id);
                }}
              >
                早見表を開く
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="help-layout">
        <aside className="panel help-sidebar" aria-label="ガイド一覧">
          <h3>ドキュメント一覧</h3>
          <p className="muted">カテゴリごとに閲覧対象を切り替えできます。</p>
          {isIndexLoading && <p className="muted">ガイドを準備中です...</p>}
          {indexError && <p className="error-text">{indexError}</p>}
          {!isIndexLoading && !indexError && index && (
            <div className="help-links">
              {index.categories.map((category) => (
                <div key={category.key} className="help-category">
                  <h3>{category.label}</h3>
                  <div className="help-links">
                    {category.items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={`help-link ${selectedDocId === item.id ? 'active' : ''}`}
                        onClick={() => {
                          setSelectedDocId(item.id);
                        }}
                      >
                        <span>{item.title}</span>
                        {item.summary && <small>{item.summary}</small>}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isIndexLoading && !indexError && sectionTitles.length > 0 && (
            <div className="help-category">
              <h3>表示中ドキュメントの目次</h3>
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
            </div>
          )}
        </aside>

        <article className="panel help-content" aria-live="polite">
          {selectedDoc && (
            <div className="help-meta-row">
              <p className="muted">表示中: {selectedDoc.title}</p>
              <p className="muted">ソース: {selectedDoc.source_path}</p>
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
