const API = (import.meta as any).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export type Site = {
  id: number;
  name: string;
  url: string;
  run_frequency: string;
  status: string;
  created_at: string;
  fields: { id: number; name: string; data_type: string; required: boolean; example_value?: string | null }[];
};

export type ExtractionResult = {
  status: 'completed' | 'needs_configuration' | 'failed' | 'empty';
  run_id: number | null;
  config_id: number | null;
  record_count: number;
  products_saved?: number;
  records: Record<string, any>[];
  message: string;
  error?: string | null;
};

export type Capture = {
  id: number;
  site_id: number | null;
  requested_url: string;
  final_url: string;
  page_title: string;
  status_code: number | null;
  load_time_ms: number;
  html_characters: number;
  cleaned_html_characters: number;
  screenshot_url: string | null;
  cleaned_html_preview: string;
  created_at: string | null;
  extraction?: ExtractionResult | null;
};

export type DatabaseOverview = {
  connection_status: 'connected' | 'disconnected';
  database_name: string;
  database_size_bytes: number;
  database_size_formatted: string;
  total_tables: number;
  total_products: number;
  total_sites: number;
  total_runs: number;
  latest_scraping_timestamp: string | null;
  tables: { name: string; row_count: number; column_count: number }[];
};

export type TableColumn = {
  name: string;
  type: string;
  primary_key: boolean;
  not_null?: boolean;
};

export type TableMetadata = {
  name: string;
  row_count: number;
  columns: TableColumn[];
};

export type TableDataResponse = {
  table_name: string;
  columns: TableColumn[];
  total_records: number;
  page: number;
  limit: number;
  total_pages: number;
  records: Record<string, any>[];
};

export type Product = {
  id: number;
  run_id: number;
  config_id?: number | null;
  site_id?: number | null;
  site_name?: string | null;
  title: string | null;
  price: string | null;
  rating: string | null;
  availability: string | null;
  product_url: string | null;
  scraped_at: string | null;
  raw_data?: Record<string, any> | null;
  raw_data_json?: string | null;
};

export type ProductsResponse = {
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  products: Product[];
};

export type ExtractionRun = {
  id: number;
  config_id: number;
  start_url: string;
  pages_crawled: number;
  record_count: number;
  created_at: string;
};

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function downloadCsv(path: string, defaultFilename: string): Promise<string> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) {
    let message = `Export failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {}
    throw new Error(message);
  }

  const disposition = response.headers.get('Content-Disposition');
  let filename = defaultFilename;
  if (disposition && disposition.includes('filename=')) {
    const match = disposition.match(/filename="?([^"]+)"?/);
    if (match && match[1]) {
      filename = match[1];
    }
  }

  const blob = await response.blob();
  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(blobUrl);

  return filename;
}

export const apiBase = API;
