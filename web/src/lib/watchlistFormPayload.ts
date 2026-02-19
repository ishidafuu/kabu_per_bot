import type { WatchlistFormValues } from '../components/WatchlistForm';
import type { WatchlistCreateInput, XAccountLink } from '../types/watchlist';

const parseMultilineValues = (value: string): string[] => {
  return value
    .split(/\r?\n/)
    .map((row) => row.trim())
    .filter((row) => row.length > 0);
};

const parseExecutiveAccounts = (value: string): XAccountLink[] => {
  return parseMultilineValues(value).map((row) => {
    const [handleRaw, ...roleParts] = row.split(',');
    return {
      handle: handleRaw.trim(),
      role: roleParts.join(',').trim() || undefined,
    };
  });
};

export const buildWatchlistPayload = (
  values: WatchlistFormValues,
): Omit<WatchlistCreateInput, 'ticker'> => {
  return {
    name: values.name,
    metric_type: values.metric_type,
    notify_channel: 'DISCORD',
    notify_timing: values.notify_timing,
    always_notify_enabled: values.always_notify_enabled,
    is_active: values.is_active,
    ai_enabled: true,
    reason: values.reason.trim() || undefined,
    ir_urls: parseMultilineValues(values.ir_urls_text),
    x_official_account: values.x_official_account.trim() || undefined,
    x_executive_accounts: parseExecutiveAccounts(values.x_executive_accounts_text),
  };
};
