import type { NotificationLogItem, NotificationLogListResponse } from '../../types/notificationLog';
import type { ListNotificationLogParams, NotificationLogClient } from './notificationLogClient';

const watchPriorityByTicker: Record<string, 'HIGH' | 'MEDIUM' | 'LOW'> = {
  '7203:TSE': 'HIGH',
  '6501:TSE': 'HIGH',
  '9432:TSE': 'MEDIUM',
  '8035:TSE': 'HIGH',
};

const seedNotificationLogs: NotificationLogItem[] = [
  {
    entry_id: 'log-20260212-01',
    ticker: '7203:TSE',
    category: 'PER',
    condition_key: 'PER:1W:UNDER',
    sent_at: '2026-02-12T08:10:00+09:00',
    channel: 'DISCORD',
    payload_hash: 'af1b9c2d',
    is_strong: false,
    body: '【PER割安】7203:TSE トヨタ自動車 1Y 3M under（2日連続）',
    data_source: '株探',
    data_fetched_at: '2026-02-12T08:00:00+09:00',
  },
  {
    entry_id: 'log-20260211-02',
    ticker: '6501:TSE',
    category: 'PSR',
    condition_key: 'PSR:3M:UNDER_STRONG',
    sent_at: '2026-02-11T21:00:00+09:00',
    channel: 'DISCORD',
    payload_hash: '8d1efaa0',
    is_strong: true,
    body: '【超PSR割安】6501:TSE 日立製作所 1Y 3M 1W under（1日目）',
    data_source: 'J-Quants v2',
    data_fetched_at: '2026-02-11T20:55:00+09:00',
  },
  {
    entry_id: 'log-20260211-01',
    ticker: '9432:TSE',
    category: 'データ不明',
    condition_key: 'DATA_UNKNOWN',
    sent_at: '2026-02-11T07:45:10+09:00',
    channel: 'DISCORD',
    payload_hash: '90cde110',
    is_strong: false,
    body: '【データ不明】9432:TSE 日本電信電話 予想EPSが取得できませんでした',
    data_source: 'Yahoo!ファイナンス',
    data_fetched_at: '2026-02-11T07:40:00+09:00',
  },
  {
    entry_id: 'log-20260210-01',
    ticker: '8035:TSE',
    category: '決算',
    condition_key: 'EARNINGS:BEFORE_OPEN',
    sent_at: '2026-02-10T06:30:00+09:00',
    channel: 'DISCORD',
    payload_hash: 'b0f1974e',
    is_strong: false,
    body: '【明日決算】8035:TSE 東京エレクトロン 2026-02-11 15:00',
    data_source: '株探',
    data_fetched_at: '2026-02-10T06:20:00+09:00',
  },
];

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

export class MockNotificationLogClient implements NotificationLogClient {
  async list(params: ListNotificationLogParams = {}): Promise<NotificationLogListResponse> {
    await wait(120);

    const limit = params.limit ?? 20;
    const offset = params.offset ?? 0;
    const ticker = params.ticker?.trim().toUpperCase() ?? '';
    const priority = params.priority;

    const filtered = seedNotificationLogs.filter((item) => {
      if (ticker.length > 0 && item.ticker.toUpperCase() !== ticker) {
        return false;
      }
      if (priority && watchPriorityByTicker[item.ticker] !== priority) {
        return false;
      }
      return true;
    });

    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
    };
  }
}
