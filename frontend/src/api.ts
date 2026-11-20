const API = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
export type Site = { id:number; name:string; url:string; run_frequency:string; status:string; created_at:string; fields:{id:number;name:string;data_type:string;required:boolean;example_value?:string|null}[] };
export type Capture = { id:number; site_id:number|null; requested_url:string; final_url:string; page_title:string; status_code:number|null; load_time_ms:number; html_characters:number; cleaned_html_characters:number; screenshot_url:string|null; cleaned_html_preview:string; created_at:string|null };
export async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response = await fetch(`${API}${path}`, { ...init, headers:{'Content-Type':'application/json', ...(init?.headers||{})} });
  if(!response.ok){ let message = `Request failed (${response.status})`; try { const body=await response.json(); message=body.detail||message; } catch {} throw new Error(message); }
  return response.json() as Promise<T>;
}
export const apiBase = API;
