export class ApiError extends Error {
  status: number;
  detail: string;
  payload: unknown;

  constructor(status: number, detail: string, payload?: unknown) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

export const toUserMessage = (error: unknown): string => {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return '認証が必要です。再ログインしてください。';
      case 403:
        return 'この操作を実行する権限がありません。';
      case 404:
        return '対象データが見つかりません。';
      case 409:
        return '同じ銘柄コードが既に登録されています。';
      case 422:
        return '入力内容が不正です。項目を確認してください。';
      case 429:
        return 'ウォッチリスト上限(100件)を超えています。';
      default:
        return `APIエラーが発生しました (${error.status})`;
    }
  }

  if (error instanceof Error) {
    return error.message;
  }

  return '不明なエラーが発生しました。';
};
