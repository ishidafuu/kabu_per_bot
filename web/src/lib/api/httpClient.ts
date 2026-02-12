import { ApiError } from './errors';

type TokenProvider = () => Promise<string | null>;

export class HttpClient {
  private readonly baseUrl: string;

  private readonly getToken?: TokenProvider;

  constructor(baseUrl: string, getToken?: TokenProvider) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.getToken = getToken;
  }

  async request<TResponse>(path: string, init: RequestInit = {}): Promise<TResponse> {
    const headers = new Headers(init.headers);

    if (!headers.has('Content-Type') && init.body) {
      headers.set('Content-Type', 'application/json');
    }

    if (this.getToken) {
      const token = await this.getToken();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
    });

    if (response.status === 204) {
      return undefined as TResponse;
    }

    const contentType = response.headers.get('content-type') ?? '';
    const hasJson = contentType.includes('application/json');

    const payload = hasJson
      ? await response.json().catch(() => undefined)
      : await response.text().catch(() => undefined);

    if (!response.ok) {
      const detail = this.extractDetail(payload, response.status);
      throw new ApiError(response.status, detail, payload);
    }

    return payload as TResponse;
  }

  private extractDetail(payload: unknown, status: number): string {
    if (typeof payload === 'string' && payload.length > 0) {
      return payload;
    }

    if (payload && typeof payload === 'object') {
      if ('detail' in payload && typeof payload.detail === 'string') {
        return payload.detail;
      }

      if ('message' in payload && typeof payload.message === 'string') {
        return payload.message;
      }
    }

    return `API request failed (${status})`;
  }
}
