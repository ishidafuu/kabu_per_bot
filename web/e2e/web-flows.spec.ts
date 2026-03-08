import { expect, test, type Page } from '@playwright/test';

const loginWithMock = async (page: Page, destinationPath = '/dashboard'): Promise<void> => {
  await page.goto(destinationPath);

  if (page.url().includes('/login')) {
    await page.getByRole('button', { name: 'モックログイン' }).click();
  }

  await expect(page).toHaveURL(new RegExp(`${destinationPath}$`));
};

const readTotalCount = async (page: Page): Promise<number> => {
  const text = await page.locator('.watchlist-meta-item', { hasText: '総件数' }).first().textContent();
  const matched = text?.match(/\d+/);
  if (!matched) {
    throw new Error(`総件数の取得に失敗しました: ${text ?? '(empty)'}`);
  }
  return Number(matched[0]);
};

test('ログイン後にダッシュボード主要KPIが表示される', async ({ page }) => {
  await page.goto('/login');

  await expect(page.getByRole('heading', { name: 'kabu_per_bot 管理画面' })).toBeVisible();
  await page.getByRole('button', { name: 'モックログイン' }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: 'ダッシュボード' })).toBeVisible();
  await expect(page.locator('.kpi-label', { hasText: '監視銘柄数' })).toBeVisible();
  await expect(page.locator('.kpi-label', { hasText: '当日通知件数' })).toBeVisible();
  await expect(page.locator('.kpi-label', { hasText: 'データ不明件数' })).toBeVisible();
  await expect(page.locator('.kpi-label', { hasText: '失敗ジョブ有無' })).toBeVisible();
  await expect(page.locator('.kpi-card .kpi-value')).toHaveCount(4);

  await page.setViewportSize({ width: 1366, height: 2200 });
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 2200 });
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true });
});

test('ウォッチリスト一覧で作成・編集・削除できる', async ({ page }) => {
  const ticker = '9999:TSE';
  const createdName = 'E2Eテスト銘柄';
  const updatedName = 'E2E編集済み銘柄';

  await loginWithMock(page, '/watchlist');

  await expect(page.getByRole('heading', { name: 'ウォッチリスト管理' })).toBeVisible();
  await expect.poll(() => page.locator('tbody tr').count(), { timeout: 20_000 }).toBeGreaterThan(0);

  await page.setViewportSize({ width: 1366, height: 2200 });
  await page.screenshot({ path: 'test-results/watchlist-desktop.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 2200 });
  await page.screenshot({ path: 'test-results/watchlist-mobile.png', fullPage: true });

  await page.setViewportSize({ width: 1280, height: 720 });
  const beforeTotal = await readTotalCount(page);
  if (beforeTotal === 0) {
    await expect(page.locator('tbody tr .empty-cell')).toHaveCount(1);
  } else {
    await expect(page.locator('tbody tr .empty-cell')).toHaveCount(0);
  }

  await page.getByRole('button', { name: '新規追加' }).click();
  await expect(page.getByRole('heading', { name: '銘柄を追加' })).toBeVisible();

  await page.getByLabel('ticker').fill(ticker);
  await page.getByLabel('会社名').fill(createdName);
  await page.getByLabel('監視方式').selectOption('PSR');
  await page.getByLabel('通知時間').selectOption('AT_21');
  await page.getByRole('button', { name: '追加する' }).click();

  await expect(page.getByText(`追加しました: ${ticker}`)).toBeVisible();
  await expect.poll(() => readTotalCount(page)).toBe(beforeTotal + 1);
  await page.getByRole('searchbox').fill(ticker);
  await page.getByRole('button', { name: '検索' }).click();
  await expect(page.locator('tbody tr', { hasText: new RegExp(`${ticker}.*${createdName}`) })).toBeVisible();

  const createdRow = page.locator('tbody tr', { hasText: ticker });
  await createdRow.getByRole('button', { name: '編集' }).click();
  await expect(page.getByRole('heading', { name: '銘柄を編集' })).toBeVisible();

  await page.getByLabel('会社名').fill(updatedName);
  await page.getByLabel('通知時間').selectOption('OFF');
  await page.getByRole('button', { name: '更新する' }).click();

  await expect(page.getByText(`更新しました: ${ticker}`)).toBeVisible();
  await expect(page.locator('tbody tr', { hasText: new RegExp(`${ticker}.*${updatedName}`) })).toBeVisible();
  await expect(page.locator('tbody tr', { hasText: ticker }).getByRole('cell', { name: 'OFF', exact: true }).first()).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('tbody tr', { hasText: ticker }).getByRole('button', { name: '削除' }).click();

  await expect(page.getByText(`削除しました: ${ticker}`)).toBeVisible();
  await page.getByRole('searchbox').fill('');
  await page.getByRole('button', { name: '検索' }).click();
  await expect.poll(() => readTotalCount(page)).toBe(beforeTotal);
  await expect(page.locator('tbody tr', { hasText: ticker })).toHaveCount(0);
});

test('履歴画面と通知ログ画面と使い方ページが表示される', async ({ page }) => {
  await loginWithMock(page, '/watchlist');

  await page.getByRole('link', { name: '履歴' }).click();
  await expect(page).toHaveURL(/\/watchlist\/history$/);
  await expect(page.getByRole('heading', { name: 'ウォッチリスト履歴' })).toBeVisible();
  await expect(page.locator('tbody tr .empty-cell')).toHaveCount(0);

  await page.getByRole('searchbox').fill('9432:tse');
  await page.getByRole('button', { name: '検索' }).click();
  await expect(page.getByText('絞り込み: 9432:TSE')).toBeVisible();
  const historyRows = page.locator('tbody tr');
  expect(await historyRows.count()).toBeGreaterThan(0);
  await expect(page.locator('tbody tr', { hasText: '9432:TSE' }).first()).toBeVisible();

  await page.getByRole('link', { name: '通知ログ' }).click();
  await expect(page).toHaveURL(/\/notifications\/logs$/);
  await expect(page.getByRole('heading', { name: '通知ログ' })).toBeVisible();
  await expect(page.locator('tbody tr .empty-cell')).toHaveCount(0);

  await page.getByRole('searchbox').fill('6501:tse');
  await page.getByRole('button', { name: '検索' }).click();
  await expect(page.getByText('絞り込み: 6501:TSE')).toBeVisible();
  const logRows = page.locator('tbody tr');
  expect(await logRows.count()).toBeGreaterThan(0);
  await expect(page.locator('tbody tr', { hasText: '6501:TSE' }).first()).toBeVisible();
  await expect(page.locator('tbody tr', { hasText: '6501:TSE' }).first()).toContainText('PSR');

  await page.getByRole('link', { name: '使い方ガイド' }).click();
  await expect(page).toHaveURL(/\/guide$/);
  await expect(page.getByRole('heading', { name: '使い方ガイド' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '管理ページの使い方とプロジェクト概要' })).toBeVisible();
  await expect(page.getByText('技術仕様・運用コマンドはここでは表示していません。')).toBeVisible();

  await page.setViewportSize({ width: 1366, height: 2200 });
  await page.screenshot({ path: 'test-results/guide-desktop.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 2200 });
  await page.screenshot({ path: 'test-results/guide-mobile.png', fullPage: true });
});

test('ウォッチリスト詳細でテクニカル表示とルール編集ができる', async ({ page }) => {
  const ruleName = `出来高スパイクE2E-${Date.now()}`;

  await loginWithMock(page, '/watchlist/6501%3ATSE/detail');

  await expect(page.getByRole('heading', { name: '最新テクニカル' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '技術アラートルール' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '直近発火履歴' })).toBeVisible();
  await expect(page.getByText('テンプレートから作成')).toBeVisible();

  await page.getByRole('button', { name: '出来高急増 出来高が平常時の2倍以上に膨らんだ日を拾います。' }).click();
  await expect(page.getByLabel('ルール名')).toHaveValue('出来高急増');
  await expect(page.getByLabel('指標')).toHaveValue('volume_ratio');
  await expect(page.getByLabel('判定方法')).toHaveValue('GTE');
  await expect(page.getByLabel('基準値')).toHaveValue('2');

  await page.getByLabel('ルール名').fill(ruleName);
  await page.getByLabel('指標').selectOption('volume_ratio');
  await page.getByLabel('判定方法').selectOption('GTE');
  await page.getByLabel('基準値').fill('2');
  await page.getByRole('button', { name: '追加する' }).click();

  await expect(page.getByText('技術アラートルールを追加しました。')).toBeVisible();
  const createdCard = page.locator('.technical-rule-card', { hasText: ruleName });
  await expect(createdCard).toBeVisible();

  await createdCard.getByRole('button', { name: '無効化' }).click();
  await expect(page.getByText('技術アラートルールを無効化しました。')).toBeVisible();
  await expect(createdCard.getByText('無効')).toBeVisible();
});

test('ウォッチリスト詳細でフラグ系ルールはTRUE/FALSEのみ選べる', async ({ page }) => {
  await loginWithMock(page, '/watchlist/6501%3ATSE/detail');

  await page.getByLabel('指標').selectOption('new_high_20d');

  await expect(page.getByLabel('判定方法')).toHaveValue('IS_TRUE');
  await expect(page.getByText('フラグ項目です。しきい値は不要で、TRUE / FALSE 判定のみ指定できます。')).toBeVisible();
  await expect(page.getByLabel('判定方法').locator('option')).toHaveCount(2);
  await expect(page.getByLabel('基準値')).toHaveCount(0);
  await expect(page.getByLabel('上限値')).toHaveCount(0);
  expect(await page.locator('select optgroup').count()).toBeGreaterThan(5);
});

test('ウォッチリスト詳細で未取得の技術過去データを一括取得依頼できる', async ({ page }) => {
  await loginWithMock(page, '/watchlist/9432%3ATSE/detail');

  await expect(page.getByRole('heading', { name: '最新テクニカル' })).toBeVisible();
  await expect(page.getByRole('button', { name: '過去データを一括取得' })).toBeVisible();

  await page.getByRole('button', { name: '過去データを一括取得' }).click();

  await expect(page.getByText(/過去データ取得を受け付けました。/)).toBeVisible();
});

test('/ops で immediate_schedule 保存と手動実行ができ、通知ログ画面に遷移できる', async ({ page }) => {
  await loginWithMock(page, '/ops');

  await expect(page.getByRole('heading', { name: '運用操作（管理者）' })).toBeVisible();

  await page.getByLabel('クールダウン（時間）').fill('2');
  await page.getByLabel('寄り付き帯 開始（HH:MM）').fill('09:00');
  await page.getByLabel('寄り付き帯 終了（HH:MM）').fill('10:00');
  await page.getByLabel('寄り付き帯 間隔（分）').fill('15');
  await page.getByLabel('引け帯 開始（HH:MM）').fill('14:30');
  await page.getByLabel('引け帯 終了（HH:MM）').fill('15:30');
  await page.getByLabel('引け帯 間隔（分）').fill('10');
  await page.getByRole('button', { name: '設定を保存' }).click();

  await expect(page.getByText('全体設定を更新しました（クールダウン: 2時間）。')).toBeVisible();

  await page.locator('.ops-subnav').getByRole('button', { name: '手動実行' }).click();
  await expect(page.getByRole('heading', { name: 'ジョブ説明と実行' })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '未計算のみ一括取得' }).click();
  await expect(page.getByText(/未計算の最新テクニカル/)).toBeVisible();
  await expect.poll(() => page.locator('.ops-job-table tbody tr').count()).toBeGreaterThan(0);
  const runButton = page.locator('.ops-job-table tbody tr button').first();
  await expect(runButton).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await runButton.click();
  await expect(page.getByText(/実行を受け付けました:/)).toBeVisible();

  await page.locator('.page-nav').getByRole('link', { name: '通知ログ' }).click();
  await expect(page).toHaveURL(/\/notifications\/logs$/);
  await expect(page.locator('main')).toContainText('通知ログ', { timeout: 10_000 });
  await expect.poll(() => page.locator('tbody tr').count(), { timeout: 10_000 }).toBeGreaterThan(0);
  const logRows = page.locator('tbody tr');
  expect(await logRows.count()).toBeGreaterThan(0);
});
