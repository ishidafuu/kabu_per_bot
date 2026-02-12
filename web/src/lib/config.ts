const parseBoolean = (value: string | undefined, defaultValue: boolean): boolean => {
  if (value == null || value === '') {
    return defaultValue;
  }

  return value.toLowerCase() === 'true';
};

const parseNumber = (value: string | undefined, defaultValue: number): number => {
  const parsed = Number(value);

  if (Number.isNaN(parsed) || parsed <= 0) {
    return defaultValue;
  }

  return parsed;
};

export const appConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  useMockApi: parseBoolean(import.meta.env.VITE_USE_MOCK_API, true),
  useMockAuth: parseBoolean(import.meta.env.VITE_USE_MOCK_AUTH, true),
  pageSize: parseNumber(import.meta.env.VITE_PAGE_SIZE, 10),
};
