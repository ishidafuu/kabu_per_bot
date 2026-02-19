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
const PROJECT_OVERVIEW_DOC_ID = 'docs/04_利用ガイド/プロジェクト全体像_非エンジニア向け/01_このプロジェクトの全体像.md';
const WEB_USAGE_DOC_ID = 'docs/04_利用ガイド/プロジェクト全体像_非エンジニア向け/06_管理画面（Web）でできること.md';
const DAILY_NOTIFICATION_DOC_ID = 'docs/04_利用ガイド/プロジェクト全体像_非エンジニア向け/03_日次の割安判定と通知.md';
const TRADER_DOC_PREFIX = 'docs/04_利用ガイド/';

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

const extractUpdatedAtFromMarkdown = (markdown: string): string => {
  const lines = markdown.split('\n');
  for (const line of lines) {
    const matched = line.match(/^\s*最終更新[:：]\s*(.+)$/);
    if (matched?.[1]) {
      return matched[1].trim();
    }
  }
  return '';
};

const extractUpdatedAtFromSummary = (summary: string): string => {
  const matched = summary.match(/最終更新[:：]\s*(.+)$/);
  return matched?.[1]?.trim() ?? '';
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

const filterTraderCategories = (index: HelpDocIndex | null): HelpDocCategory[] => {
  if (!index) {
    return [];
  }

  return index.categories
    .map((category) => ({
      ...category,
      items: category.items.filter((item) => item.id.startsWith(TRADER_DOC_PREFIX)),
    }))
    .filter((category) => category.items.length > 0);
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

const getFirstTraderDocId = (index: HelpDocIndex | null): string => {
  const traderCategories = filterTraderCategories(index);
  if (traderCategories.length === 0) {
    return '';
  }

  for (const preferredId of [TRADER_GUIDE_ID, PROJECT_OVERVIEW_DOC_ID, WEB_USAGE_DOC_ID]) {
    const preferred = findDocById({ generated_at: '', categories: traderCategories }, preferredId);
    if (preferred) {
      return preferred.id;
    }
  }

  return traderCategories[0]?.items[0]?.id ?? '';
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
        setSelectedDocId((current) => current || getFirstTraderDocId(payload) || getFirstDocId(payload));
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

  const traderCategories = useMemo(() => filterTraderCategories(index), [index]);
  const selectedDoc = useMemo(() => findDocById(index, selectedDocId), [index, selectedDocId]);
  const traderGuideDoc = useMemo(() => findDocById(index, TRADER_GUIDE_ID), [index]);
  const projectOverviewDoc = useMemo(() => findDocById(index, PROJECT_OVERVIEW_DOC_ID), [index]);
  const webUsageDoc = useMemo(() => findDocById(index, WEB_USAGE_DOC_ID), [index]);
  const dailyNotificationDoc = useMemo(() => findDocById(index, DAILY_NOTIFICATION_DOC_ID), [index]);

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
  const selectedDocUpdatedAt = useMemo(() => {
    const fromMarkdown = extractUpdatedAtFromMarkdown(markdown);
    if (fromMarkdown) {
      return fromMarkdown;
    }
    const fromSummary = extractUpdatedAtFromSummary(selectedDoc?.summary ?? '');
    if (fromSummary) {
      return fromSummary;
    }
    return `未記載（同期: ${generatedAt}）`;
  }, [generatedAt, markdown, selectedDoc?.summary]);

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
    <AppLayout title="使い方ガイド" subtitle="トレーダー向けに、管理サイトで日々見るポイントを整理しています。">
      <section className="panel guide-hero">
        <p className="guide-hero-badge">トレーダー向け</p>
        <h2>管理ページの使い方とプロジェクト概要</h2>
        <p className="muted">
          運用コマンドや技術詳細ではなく、毎日の確認順と判断に必要な情報を中心にまとめています。
        </p>
        <p className="muted">最終同期: {generatedAt}（JST）</p>
        <div className="guide-quick-grid">
          <button
            type="button"
            className="guide-quick-card"
            disabled={!traderGuideDoc}
            onClick={() => {
              if (traderGuideDoc) {
                setSelectedDocId(traderGuideDoc.id);
              }
            }}
          >
            <span className="guide-quick-card-title">最短スタート</span>
            <span className="muted">最初の3分で必要な設定と、日々の確認順を把握</span>
          </button>
          <button
            type="button"
            className="guide-quick-card"
            disabled={!projectOverviewDoc}
            onClick={() => {
              if (projectOverviewDoc) {
                setSelectedDocId(projectOverviewDoc.id);
              }
            }}
          >
            <span className="guide-quick-card-title">プロジェクト全体像</span>
            <span className="muted">この仕組みが何を自動化し、どこまでを支援するかを確認</span>
          </button>
          <button
            type="button"
            className="guide-quick-card"
            disabled={!webUsageDoc}
            onClick={() => {
              if (webUsageDoc) {
                setSelectedDocId(webUsageDoc.id);
              }
            }}
          >
            <span className="guide-quick-card-title">管理サイトでできること</span>
            <span className="muted">ダッシュボード、ウォッチリスト、通知ログの役割を把握</span>
          </button>
        </div>
      </section>

      <section className="panel guide-section">
        <h3>日々の使い方（要点）</h3>
        <div className="guide-steps">
          <div className="guide-step">
            <p className="guide-step-title">1. ダッシュボード</p>
            <p className="muted">失敗ジョブ有無とデータ不明件数を先に確認します。</p>
          </div>
          <div className="guide-step">
            <p className="guide-step-title">2. 通知ログ</p>
            <p className="muted">当日の通知カテゴリと条件キーを確認します。</p>
          </div>
          <div className="guide-step">
            <p className="guide-step-title">3. ウォッチリスト</p>
            <p className="muted">主要銘柄の有効状態・通知タイミング・現在値を確認します。</p>
          </div>
          <div className="guide-step">
            <p className="guide-step-title">4. 必要時のみ設定変更</p>
            <p className="muted">変更した日は履歴ページで操作記録を見直します。</p>
          </div>
        </div>
      </section>

      <section className="help-layout">
        <aside className="panel help-sidebar" aria-label="ガイド一覧">
          <h3>トレーダー向けガイド一覧</h3>
          <p className="muted">技術仕様・運用コマンドはここでは表示していません。</p>
          {isIndexLoading && <p className="muted">ガイドを準備中です...</p>}
          {indexError && <p className="error-text">{indexError}</p>}
          {!isIndexLoading && !indexError && traderCategories.length > 0 && (
            <div className="help-links">
              {traderCategories.map((category) => (
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
              <p className="muted">更新日時: {selectedDocUpdatedAt}</p>
              {firstSectionTitle && (
                <button type="button" className="ghost help-jump-button fit-content" onClick={() => scrollToSection(firstSectionTitle)}>
                  最初の章へ移動
                </button>
              )}
            </div>
          )}

          {isDocLoading && <p className="muted">本文を読み込み中です...</p>}
          {docError && <p className="error-text">{docError}</p>}

          {!isDocLoading && !docError && markdown && (
            <div className="help-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
          )}

          {!isDocLoading && !docError && !markdown && (
            <div className="help-empty-state">
              <p className="muted">左側のガイド一覧から読みたい項目を選択してください。</p>
              <button
                type="button"
                className="secondary fit-content"
                disabled={!dailyNotificationDoc}
                onClick={() => {
                  if (dailyNotificationDoc) {
                    setSelectedDocId(dailyNotificationDoc.id);
                  }
                }}
              >
                日次通知の説明を開く
              </button>
            </div>
          )}
        </article>
      </section>
    </AppLayout>
  );
};
