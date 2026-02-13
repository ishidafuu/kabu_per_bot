import type { NotificationLogItem, NotificationLogListResponse } from '../../types/notificationLog';
import type { ListNotificationLogParams, NotificationLogClient } from './notificationLogClient';

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

    const filtered = ticker.length === 0
      ? seedNotificationLogs
      : seedNotificationLogs.filter((item) => item.ticker.toUpperCase() === ticker);

    return {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
    };
  }
}
