import { useEffect, useState } from 'react';
import { Activity, Bot, CircleHelp, Clock3, Database, Globe2, LayoutDashboard, Plus, RefreshCw, Search, ShieldCheck, Workflow, X } from 'lucide-react';
import { request, apiBase, type Site, type Capture } from './api';

export default function App(){
  const [sites,setSites]=useState<Site[]>([]);
  const [health,setHealth]=useState<'checking'|'online'|'offline'>('checking');
  const [error,setError]=useState('');
  const [showForm,setShowForm]=useState(false);
  const [url,setUrl]=useState('');
  const [name,setName]=useState('');
  const [busy,setBusy]=useState(false);
  const [query,setQuery]=useState('');
  const [capturing,setCapturing]=useState<number|null>(null);
  const [latestCapture,setLatestCapture]=useState<Capture|null>(null);
  async function load(){
    try { const h=await request<{status:string}>('/api/health'); setHealth(h.status==='ok'?'online':'offline'); const data=await request<Site[]>('/api/sites'); setSites(data); setError(''); }
    catch(e){setHealth('offline');setError(e instanceof Error?e.message:'Could not connect to backend');}
  }
  useEffect(()=>{void load();},[]);
  async function runCapture(site:Site){
    setCapturing(site.id); setError('');
    try {
      const result=await request<Capture>('/api/capture',{method:'POST',body:JSON.stringify({url:site.url,site_id:site.id})});
      setLatestCapture(result); await load();
    } catch(e){setError(e instanceof Error?e.message:'Capture failed');}
    finally{setCapturing(null);}
  }
  async function addSite(e:React.FormEvent){
    e.preventDefault(); setBusy(true); setError('');
    try { await request<Site>('/api/sites',{method:'POST',body:JSON.stringify({name:name||undefined,url,run_frequency:'manual',fields:[]})}); setUrl('');setName('');setShowForm(false);await load(); }
    catch(e){setError(e instanceof Error?e.message:'Unable to add website');}
    finally{setBusy(false);}
  }
  const filtered=sites.filter(s=>`${s.name} ${s.url}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Workflow size={21}/></div><div><b>ScraperOps</b><small>SELF-HEALING PLATFORM</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <div className="nav-item active"><LayoutDashboard size={18}/> Overview</div>
      <div className="nav-item"><Globe2 size={18}/> Websites <span>{sites.length}</span></div>
      <div className="nav-item"><Activity size={18}/> Runs</div>
      <div className="nav-item"><ShieldCheck size={18}/> Review queue</div>
      <div className="nav-item"><Database size={18}/> Configurations</div>
      <div className="nav-label second">INSIGHTS</div>
      <div className="nav-item"><Activity size={18}/> Reports</div>
      <div className="nav-item"><Clock3 size={18}/> Audit log</div>
      <div className="sidebar-bottom"><div className="help"><CircleHelp size={17}/><div><b>Need help?</b><small>View setup guide</small></div></div><div className="profile"><div className="avatar">A</div><div><b>Workspace admin</b><small>Local environment</small></div></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="crumb">Workspace <span>/</span> Overview</div><div className="top-actions"><div className={`connection ${health}`}><i/> API {health==='online'?'Connected':health==='checking'?'Checking':'Offline'}</div><button className="icon-btn" onClick={()=>void load()} title="Refresh"><RefreshCw size={17}/></button><div className="avatar small">A</div></div></header>
      <section className="content">
        <div className="welcome"><div><div className="eyebrow">MONITORING OVERVIEW</div><h1>Good afternoon</h1><p>Monitor your websites, extraction health and automation activity.</p></div><button className="primary" onClick={()=>setShowForm(true)}><Plus size={17}/> Add website</button></div>
        {error&&<div className="alert"><b>Connection or request issue:</b> {error}</div>}
        <div className="stats">
          <Stat icon={<Globe2/>} label="Total websites" value={String(sites.length)} note="Registered in workspace"/>
          <Stat icon={<Activity/>} label="Active scrapers" value="—" note="Run engine milestone pending"/>
          <Stat icon={<ShieldCheck/>} label="Successful runs" value="—" note="Awaiting run history module"/>
          <Stat icon={<Bot/>} label="Pending reviews" value="—" note="Review workflow milestone pending"/>
        </div>
        <div className="section-head"><div><h2>Websites</h2><p>Your registered scraping targets</p></div><div className="table-tools"><div className="search"><Search size={16}/><input placeholder="Search websites..." value={query} onChange={e=>setQuery(e.target.value)}/></div><button className="secondary" onClick={()=>void load()}><RefreshCw size={15}/> Refresh</button></div></div>
        <div className="table-card"><table><thead><tr><th>WEBSITE</th><th>STATUS</th><th>SCHEDULE</th><th>FIELDS</th><th>ADDED</th><th>ACTION</th></tr></thead><tbody>
          {filtered.map(site=><tr key={site.id}><td><div className="site-cell"><div className="site-icon"><Globe2 size={17}/></div><div><b>{site.name}</b><small>{site.url}</small></div></div></td><td><span className={`status ${site.status}`}>{site.status.replace('_',' ')}</span></td><td>Manual</td><td>{site.fields.length}</td><td>{new Date(site.created_at).toLocaleDateString()}</td><td><button className="secondary capture-btn" disabled={capturing!==null} onClick={()=>void runCapture(site)}>{capturing===site.id?'Capturing...':'Capture page'}</button></td></tr>)}
          {filtered.length===0&&<tr><td colSpan={6}><div className="empty"><div className="empty-icon"><Globe2/></div><b>{query?'No matching websites':'No websites yet'}</b><p>{query?'Try another search.':'Add your first website to begin building an automated scraper.'}</p>{!query&&<button className="primary" onClick={()=>setShowForm(true)}><Plus size={16}/> Add first website</button>}</div></td></tr>}
        </tbody></table></div>
        {latestCapture&&<div className="capture-result">
          <div className="capture-result-head"><div><div className="eyebrow">LATEST CAPTURE · #{latestCapture.id}</div><h2>{latestCapture.page_title||'Captured page'}</h2><p>{latestCapture.final_url}</p></div><span className="capture-code">{latestCapture.status_code??'—'} HTTP</span></div>
          <div className="capture-metrics"><div><b>{latestCapture.load_time_ms.toLocaleString()} ms</b><small>Load time</small></div><div><b>{latestCapture.html_characters.toLocaleString()}</b><small>HTML characters</small></div><div><b>{latestCapture.cleaned_html_characters.toLocaleString()}</b><small>Cleaned characters</small></div></div>
          {latestCapture.screenshot_url&&<a className="screenshot-link" href={`${apiBase}${latestCapture.screenshot_url}`} target="_blank" rel="noreferrer">Open captured screenshot ↗</a>}
          <details><summary>View cleaned HTML preview</summary><pre>{latestCapture.cleaned_html_preview}</pre></details>
        </div>}
        <div className="bottom-grid"><div className="info-card"><div className="info-icon blue"><Bot/></div><div><b>AI-assisted onboarding</b><p>Groq will help generate extraction configurations from captured website structure. This feature will be connected in the next build milestone.</p></div></div><div className="info-card"><div className="info-icon green"><ShieldCheck/></div><div><b>Safe by design</b><p>Extraction results will pass validation before data is accepted. Uncertain repairs will require human review.</p></div></div></div>
        <footer>ScraperOps <span>•</span> Local proof of concept <span>•</span> Built for transparent, verifiable extraction</footer>
      </section>
    </main>
    {showForm&&<div className="modal-backdrop" onClick={()=>setShowForm(false)}><div className="modal" onClick={e=>e.stopPropagation()}><div className="modal-head"><div><h2>Add a website</h2><p>Register a public website as a scraping target.</p></div><button className="icon-btn" onClick={()=>setShowForm(false)}><X/></button></div><form onSubmit={addSite}><label>Website name</label><input value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Books to Scrape"/><label>Website URL *</label><input required type="url" value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://example.com"/><div className="form-note">Only websites you are authorized to access. Local/private network targets are blocked by the capture service.</div><div className="modal-actions"><button type="button" className="secondary" onClick={()=>setShowForm(false)}>Cancel</button><button className="primary" disabled={busy}>{busy?'Adding...':'Add website'}</button></div></form></div></div>}
  </div>
}
function Stat({icon,label,value,note}:{icon:React.ReactNode;label:string;value:string;note:string}){return <div className="stat"><div className="stat-top"><span>{label}</span><div className="stat-icon">{icon}</div></div><strong>{value}</strong><small>{note}</small></div>}
