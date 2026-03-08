import type {
  TechnicalProfile,
  TechnicalProfileCloneInput,
  TechnicalProfileCreateInput,
  TechnicalProfileListResponse,
  TechnicalProfileUpdateInput,
} from '../../types/technicalProfiles';
import { HttpClient } from './httpClient';

export interface TechnicalProfilesClient {
  list(): Promise<TechnicalProfileListResponse>;
  get(profileId: string): Promise<TechnicalProfile>;
  create(input: TechnicalProfileCreateInput): Promise<TechnicalProfile>;
  clone(profileId: string, input: TechnicalProfileCloneInput): Promise<TechnicalProfile>;
  update(profileId: string, input: TechnicalProfileUpdateInput): Promise<TechnicalProfile>;
}

export class HttpTechnicalProfilesClient implements TechnicalProfilesClient {
  private readonly httpClient: HttpClient;

  constructor(httpClient: HttpClient) {
    this.httpClient = httpClient;
  }

  async list(): Promise<TechnicalProfileListResponse> {
    return this.httpClient.request<TechnicalProfileListResponse>('/technical-profiles', { method: 'GET' });
  }

  async get(profileId: string): Promise<TechnicalProfile> {
    return this.httpClient.request<TechnicalProfile>(`/technical-profiles/${encodeURIComponent(profileId)}`, {
      method: 'GET',
    });
  }

  async create(input: TechnicalProfileCreateInput): Promise<TechnicalProfile> {
    return this.httpClient.request<TechnicalProfile>('/technical-profiles', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  }

  async clone(profileId: string, input: TechnicalProfileCloneInput): Promise<TechnicalProfile> {
    return this.httpClient.request<TechnicalProfile>(`/technical-profiles/${encodeURIComponent(profileId)}/clone`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  }

  async update(profileId: string, input: TechnicalProfileUpdateInput): Promise<TechnicalProfile> {
    return this.httpClient.request<TechnicalProfile>(`/technical-profiles/${encodeURIComponent(profileId)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  }
}
