import type { WatchlistHistoryItem, WatchlistHistoryListResponse } from '../../types/watchlistHistory';
import type { ListWatchlistHistoryParams, WatchlistHistoryClient } from './watchlistHistoryClient';

const seedWatchlistHistory: WatchlistHistoryItem[] = [
  {
    record_id: 'hist-20260211-01',
    ticker: '7203:TSE',
    action: 'REMOVE',
    reason: '監視対象見直し',
    acted_at: '2026-02-11T13:20:05+09:00',
  },
  {
    record_id: 'hist-20260210-01',
    ticker: '7203:TSE',
    action: 'ADD',
    reason: 'PER監視追加',
    acted_at: '2026-02-10T09:35:42+09:00',
  },
  {
    record_id: 'hist-20260209-01',
    ticker: '9432:TSE',
    action: 'REMOVE',
    reason: '通知停止',
    acted_at: '2026-02-09T21:10:15+09:00',
  },
  {
    record_id: 'hist-20260208-01',
    ticker: '9432:TSE',
    action: 'ADD',
    reason: '監視再開',
    acted_at: '2026-02-08T10:01:11+09:00',
  },
  {
    record_id: 'hist-20260207-01',
    ticker: '6501:TSE',
    action: 'ADD',
    reason: '初回登録',
    acted_at: '2026-02-07T08:45:00+09:00',
  },
];

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

export class MockWatchlistHistoryClient implements WatchlistHistoryClient {
  async list(params: ListWatchlistHistoryParams = {}): Promise<WatchlistHistoryListResponse> {
    await wait(120);

    const limit = params.limit ?? 20;
    const offset = params.offset ?? 0;
    const ticker = params.ticker?.trim().toUpperCase() ?? '';

    const filtered = ticker.length === 0
      ? seedWatchlistHistory
      : seedWatchlistHistory.filter((item) => item.ticker.toUpperCase() === ticker);

    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
    };
  }
}
