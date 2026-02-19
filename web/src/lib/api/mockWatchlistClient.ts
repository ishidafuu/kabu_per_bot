import { ApiError } from './errors';
import type {
  IrUrlCandidateListResponse,
  IrUrlCandidateSuggestInput,
  WatchlistCreateInput,
  WatchlistItem,
  WatchlistListResponse,
  WatchlistUpdateInput,
} from '../../types/watchlist';
import type { ListWatchlistParams, WatchlistClient } from './watchlistClient';

const MAX_WATCHLIST_COUNT = 100;
const TICKER_PATTERN = /^\d{4}:TSE$/;

const seedWatchlist: WatchlistItem[] = [
  {
    ticker: '1332:TSE',
    name: 'ニッスイ',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'IMMEDIATE',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '1605:TSE',
    name: 'INPEX',
    metric_type: 'PSR',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
    ir_urls: [],
    x_official_account: 'inpex_jp',
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '2914:TSE',
    name: 'JT',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'OFF',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: false,
    ai_enabled: false,
  },
  {
    ticker: '4063:TSE',
    name: '信越化学工業',
    metric_type: 'PSR',
    notify_channel: 'DISCORD',
    notify_timing: 'IMMEDIATE',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '4502:TSE',
    name: '武田薬品工業',
    metric_type: 'PER',
    notify_channel: 'OFF',
    notify_timing: 'OFF',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '6367:TSE',
    name: 'ダイキン工業',
    metric_type: 'PSR',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '6501:TSE',
    name: '日立製作所',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'IMMEDIATE',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '6758:TSE',
    name: 'ソニーグループ',
    metric_type: 'PSR',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '7203:TSE',
    name: 'トヨタ自動車',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'IMMEDIATE',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '8035:TSE',
    name: '東京エレクトロン',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '8058:TSE',
    name: '三菱商事',
    metric_type: 'PSR',
    notify_channel: 'DISCORD',
    notify_timing: 'OFF',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: false,
    ai_enabled: false,
  },
  {
    ticker: '9432:TSE',
    name: '日本電信電話',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
    ir_urls: [],
    x_official_account: null,
    x_executive_accounts: [],
    is_active: true,
    ai_enabled: false,
  },
];

let mockStore = [...seedWatchlist];

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

const hasInvalidInput = (input: WatchlistCreateInput | WatchlistUpdateInput): boolean => {
  if ('ticker' in input) {
    const ticker = input.ticker.trim().toUpperCase();
    if (!TICKER_PATTERN.test(ticker)) {
      return true;
    }
  }

  if ('name' in input && input.name != null) {
    if (input.name.trim().length === 0) {
      return true;
    }
  }

  return false;
};

export class MockWatchlistClient implements WatchlistClient {
  async list(params: ListWatchlistParams = {}): Promise<WatchlistListResponse> {
    await wait(120);

    const limit = params.limit ?? 10;
    const offset = params.offset ?? 0;
    const keyword = params.q?.trim().toLowerCase() ?? '';

    const filtered = keyword.length === 0
      ? mockStore
      : mockStore.filter((item) => {
          return (
            item.ticker.toLowerCase().includes(keyword) ||
            item.name.toLowerCase().includes(keyword)
          );
        });

    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
    };
  }

  async suggestIrUrlCandidates(input: IrUrlCandidateSuggestInput): Promise<IrUrlCandidateListResponse> {
    await wait(180);
    const normalizedTicker = input.ticker.trim().toUpperCase();
    const normalizedName = input.company_name.trim();
    if (!TICKER_PATTERN.test(normalizedTicker) || normalizedName.length === 0) {
      throw new ApiError(422, '入力不正');
    }
    const maxCandidates = Math.min(Math.max(input.max_candidates ?? 5, 1), 10);
    const domain = normalizedName
      .toLowerCase()
      .replace(/\s+/g, '')
      .replace(/株式会社/g, '')
      .replace(/[^a-z0-9]/g, '')
      || 'example';
    const allRows: IrUrlCandidateListResponse['items'] = [
      {
        url: `https://www.${domain}.co.jp/ir/`,
        title: `${normalizedName} IR情報`,
        reason: 'モック候補: 公式IRトップ想定',
        confidence: 'High',
        validation_status: 'VALID',
        score: 8,
        http_status: 200,
        content_type: 'text/html',
      },
      {
        url: `https://www.${domain}.co.jp/ir/library/`,
        title: `${normalizedName} IRライブラリ`,
        reason: 'モック候補: 資料一覧想定',
        confidence: 'Med',
        validation_status: 'WARNING',
        score: 5,
        http_status: 200,
        content_type: 'text/html',
      },
      {
        url: `https://www.${domain}.co.jp/contact/`,
        title: `${normalizedName} お問い合わせ`,
        reason: 'モック候補: 非IRページ例',
        confidence: 'Low',
        validation_status: 'INVALID',
        score: 1,
        http_status: 200,
        content_type: 'text/html',
      },
    ];
    const rows = allRows.slice(0, maxCandidates);

    return {
      items: rows,
      total: rows.length,
      source: 'MOCK_AI',
    };
  }

  async create(input: WatchlistCreateInput): Promise<WatchlistItem> {
    await wait(120);

    const normalizedTicker = input.ticker.trim().toUpperCase();
    const normalizedInput: WatchlistCreateInput = {
      ...input,
      ticker: normalizedTicker,
      name: input.name.trim(),
    };

    if (hasInvalidInput(normalizedInput)) {
      throw new ApiError(422, '入力不正');
    }

    if (mockStore.length >= MAX_WATCHLIST_COUNT) {
      throw new ApiError(429, '上限超過');
    }

    const duplicated = mockStore.some((item) => item.ticker === normalizedInput.ticker);
    if (duplicated) {
      throw new ApiError(409, '重複データ');
    }

    const created: WatchlistItem = {
      ticker: normalizedInput.ticker,
      name: normalizedInput.name,
      metric_type: normalizedInput.metric_type,
      notify_channel: normalizedInput.notify_channel,
      notify_timing: normalizedInput.notify_timing,
      always_notify_enabled: normalizedInput.always_notify_enabled ?? false,
      ir_urls: normalizedInput.ir_urls ?? [],
      x_official_account: normalizedInput.x_official_account ?? null,
      x_executive_accounts: normalizedInput.x_executive_accounts ?? [],
      is_active: normalizedInput.is_active ?? true,
      ai_enabled: true,
    };

    mockStore = [created, ...mockStore];

    return created;
  }

  async update(ticker: string, input: WatchlistUpdateInput): Promise<WatchlistItem> {
    await wait(120);

    if (hasInvalidInput(input)) {
      throw new ApiError(422, '入力不正');
    }

    const index = mockStore.findIndex((item) => item.ticker === ticker);

    if (index < 0) {
      throw new ApiError(404, 'データなし');
    }

    const current = mockStore[index];
    const updated = {
      ...current,
      ...input,
      name: input.name != null ? input.name.trim() : current.name,
      ai_enabled: true,
    };

    mockStore = [
      ...mockStore.slice(0, index),
      updated,
      ...mockStore.slice(index + 1),
    ];

    return updated;
  }

  async remove(ticker: string, reason?: string): Promise<void> {
    await wait(120);
    void reason;

    const existed = mockStore.some((item) => item.ticker === ticker);

    if (!existed) {
      throw new ApiError(404, 'データなし');
    }

    mockStore = mockStore.filter((item) => item.ticker !== ticker);
  }
}

export const resetMockWatchlist = (): void => {
  mockStore = [...seedWatchlist];
};

export const getMockWatchlistCount = (): number => {
  return mockStore.length;
};
