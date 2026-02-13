import { ApiError } from './errors';
import type {
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
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '1605:TSE',
    name: 'INPEX',
    metric_type: 'PSR',
    notify_channel: 'BOTH',
    notify_timing: 'AT_21',
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '2914:TSE',
    name: 'JT',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'OFF',
    is_active: false,
    ai_enabled: false,
  },
  {
    ticker: '4063:TSE',
    name: '信越化学工業',
    metric_type: 'PSR',
    notify_channel: 'LINE',
    notify_timing: 'IMMEDIATE',
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '4502:TSE',
    name: '武田薬品工業',
    metric_type: 'PER',
    notify_channel: 'OFF',
    notify_timing: 'OFF',
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '6367:TSE',
    name: 'ダイキン工業',
    metric_type: 'PSR',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '6501:TSE',
    name: '日立製作所',
    metric_type: 'PER',
    notify_channel: 'BOTH',
    notify_timing: 'IMMEDIATE',
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '6758:TSE',
    name: 'ソニーグループ',
    metric_type: 'PSR',
    notify_channel: 'LINE',
    notify_timing: 'AT_21',
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '7203:TSE',
    name: 'トヨタ自動車',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'IMMEDIATE',
    is_active: true,
    ai_enabled: false,
  },
  {
    ticker: '8035:TSE',
    name: '東京エレクトロン',
    metric_type: 'PER',
    notify_channel: 'BOTH',
    notify_timing: 'AT_21',
    is_active: true,
    ai_enabled: true,
  },
  {
    ticker: '8058:TSE',
    name: '三菱商事',
    metric_type: 'PSR',
    notify_channel: 'LINE',
    notify_timing: 'OFF',
    is_active: false,
    ai_enabled: false,
  },
  {
    ticker: '9432:TSE',
    name: '日本電信電話',
    metric_type: 'PER',
    notify_channel: 'DISCORD',
    notify_timing: 'AT_21',
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
      is_active: normalizedInput.is_active ?? true,
      ai_enabled: normalizedInput.ai_enabled ?? false,
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
    };

    mockStore = [
      ...mockStore.slice(0, index),
      updated,
      ...mockStore.slice(index + 1),
    ];

    return updated;
  }

  async remove(ticker: string): Promise<void> {
    await wait(120);

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
