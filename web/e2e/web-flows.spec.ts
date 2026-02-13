import { expect, test, type Page } from '@playwright/test';

const loginWithMock = async (page: Page, destinationPath = '/dashboard'): Promise<void> => {
  await page.goto(destinationPath);

  if (page.url().includes('/login')) {
    await page.getByRole('button', { name: 'モックログイン' }).click();
  }

  await expect(page).toHaveURL(new RegExp(`${destinationPath}$`));
};

const readTotalCount = async (page: Page): Promise<number> => {
  const text = await page.getByText(/^総件数:/).first().textContent();
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
  await expect(page.getByText('監視銘柄数')).toBeVisible();
  await expect(page.getByText('当日通知件数')).toBeVisible();
  await expect(page.getByText('データ不明件数')).toBeVisible();
  await expect(page.getByText('失敗ジョブ有無')).toBeVisible();
  await expect(page.locator('.kpi-card .kpi-value')).toHaveCount(4);
});

test('ウォッチリスト一覧で作成・編集・削除できる', async ({ page }) => {
  const ticker = '9999:TSE';
  const createdName = 'E2Eテスト銘柄';
  const updatedName = 'E2E編集済み銘柄';

  await loginWithMock(page, '/watchlist');

  await expect(page.getByRole('heading', { name: 'ウォッチリスト管理' })).toBeVisible();
  await expect.poll(() => readTotalCount(page)).toBeGreaterThan(0);
  const beforeTotal = await readTotalCount(page);
  await expect(page.locator('tbody tr .empty-cell')).toHaveCount(0);

  await page.getByRole('button', { name: '新規追加' }).click();
  await expect(page.getByRole('heading', { name: '銘柄を追加' })).toBeVisible();

  await page.getByLabel('ticker').fill(ticker);
  await page.getByLabel('会社名').fill(createdName);
  await page.getByLabel('監視方式').selectOption('PSR');
  await page.getByLabel('通知先').selectOption('LINE');
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
  await page.getByLabel('通知先').selectOption('OFF');
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

test('履歴画面と通知ログ画面が表示される', async ({ page }) => {
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
});
