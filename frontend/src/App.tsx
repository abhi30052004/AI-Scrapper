import { useEffect, useState } from 'react';
import {
  Activity,
  Bot,
  CircleHelp,
  Clock3,
  Database,
  Globe2,
  LayoutDashboard,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Workflow,
  X,
  CheckCircle2,
  AlertCircle,
  Download,
  ArrowRight,
  Package,
  ExternalLink,
  Camera,
  FileCode,
  Sparkles
} from 'lucide-react';
import { request, downloadCsv, apiBase, type Site, type Capture } from './api';
import { DatabaseExplorer } from './components/DatabaseExplorer';

export default function App() {
  const [mainNav, setMainNav] = useState<'overview' | 'db_explorer'>('overview');
  const [sites, setSites] = useState<Site[]>([]);
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>('checking');
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [capturing, setCapturing] = useState<number | null>(null);
  const [quickUrl, setQuickUrl] = useState('');
  const [quickCapturing, setQuickCapturing] = useState(false);
  const [captureStage, setCaptureStage] = useState<number>(0);
  const [latestCapture, setLatestCapture] = useState<Capture | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [downloadingRunId, setDownloadingRunId] = useState<number | null>(null);
  const [dbRefreshKey, setDbRefreshKey] = useState(0);

  function notify(message: string, type: 'success' | 'error' = 'success') {
    setToast({ message, type });
    setTimeout(() => {
      setToast(null);
    }, 4500);
  }

  async function load() {
    try {
      const h = await request<{ status: string }>('/api/health');
      setHealth(h.status === 'ok' ? 'online' : 'offline');
      const data = await request<Site[]>('/api/sites');
      setSites(data);
      setError('');
    } catch (e) {
      setHealth('offline');
      setError(e instanceof Error ? e.message : 'Could not connect to backend');
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // Run full automated capture pipeline
  async function runCapturePipeline(targetUrl: string, siteId?: number) {
    if (siteId) setCapturing(siteId);
    else setQuickCapturing(true);

    setError('');
    setCaptureStage(1); // Stage 1: Capturing webpage

    const stageTimer1 = setTimeout(() => setCaptureStage(2), 2500); // Stage 2: Taking screenshot & HTML
    const stageTimer2 = setTimeout(() => setCaptureStage(3), 5000); // Stage 3: Resolving configuration
    const stageTimer3 = setTimeout(() => setCaptureStage(4), 7500); // Stage 4: Extracting records

    try {
      const result = await request<Capture>('/api/capture', {
        method: 'POST',
        body: JSON.stringify({ url: targetUrl, site_id: siteId || undefined })
      });

      clearTimeout(stageTimer1);
      clearTimeout(stageTimer2);
      clearTimeout(stageTimer3);
      setCaptureStage(5); // Stage 5: Database saved

      setLatestCapture(result);

      if (result.extraction?.status === 'completed') {
        notify(`Success: Captured webpage and saved ${result.extraction.record_count} products to SQLite!`, 'success');
        setDbRefreshKey(k => k + 1); // trigger DB explorer refresh
      } else if (result.extraction?.status === 'empty') {
        notify('Capture and extraction ran but 0 products matched selectors. Check config.', 'error');
      } else if (result.extraction?.status === 'needs_configuration') {
        notify(`Capture saved. AI config failed: ${result.extraction.error || 'check GROQ_API_KEY / network'}`, 'error');
      } else if (result.extraction?.status === 'failed') {
        notify(`Capture saved. Extraction error: ${result.extraction.error}`, 'error');
      } else {
        notify('Webpage captured successfully!', 'success');
      }

      await load();
    } catch (e) {
      clearTimeout(stageTimer1);
      clearTimeout(stageTimer2);
      clearTimeout(stageTimer3);
      setCaptureStage(0);
      const msg = e instanceof Error ? e.message : 'Capture failed';
      setError(msg);
      notify(msg, 'error');
    } finally {
      setCapturing(null);
      setQuickCapturing(false);
    }
  }

  async function addSite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await request<Site>('/api/sites', {
        method: 'POST',
        body: JSON.stringify({ name: name || undefined, url, run_frequency: 'manual', fields: [] })
      });
      setUrl('');
      setName('');
      setShowForm(false);
      notify('Website registered successfully', 'success');
      await load();
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unable to add website';
      setError(msg);
      notify(msg, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function handleDownloadRunCsv(runId: number) {
    setDownloadingRunId(runId);
    try {
      const filename = await downloadCsv(`/api/extraction/runs/${runId}/export?format=csv`, `extraction_${runId}.csv`);
      notify(`Downloaded ${filename} successfully!`, 'success');
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Export failed', 'error');
    } finally {
      setDownloadingRunId(null);
    }
  }

  const isProcessing = capturing !== null || quickCapturing;
  const filtered = sites.filter(s => `${s.name} ${s.url}`.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Workflow size={21} />
          </div>
          <div>
            <b>ScraperOps</b>
            <small>AI SELF-HEALING PLATFORM</small>
          </div>
        </div>

        <div className="nav-label">WORKSPACE</div>

        <div
          className={`nav-item ${mainNav === 'overview' ? 'active' : ''}`}
          onClick={() => setMainNav('overview')}
          style={{ cursor: 'pointer' }}
        >
          <LayoutDashboard size={18} /> Overview
        </div>

        <div
          className={`nav-item ${mainNav === 'db_explorer' ? 'active' : ''}`}
          onClick={() => setMainNav('db_explorer')}
          style={{ cursor: 'pointer' }}
        >
          <Database size={18} /> Database Explorer
        </div>

        <div
          className="nav-item"
          onClick={() => setMainNav('overview')}
          style={{ cursor: 'pointer' }}
        >
          <Globe2 size={18} /> Websites <span>{sites.length}</span>
        </div>

        <div className="nav-item" onClick={() => setMainNav('db_explorer')} style={{ cursor: 'pointer' }}>
          <Activity size={18} /> Runs
        </div>

        <div className="nav-item">
          <ShieldCheck size={18} /> Review queue
        </div>

        <div className="nav-item" onClick={() => setMainNav('db_explorer')} style={{ cursor: 'pointer' }}>
          <Database size={18} /> Configurations
        </div>

        <div className="nav-label second">INSIGHTS</div>

        <div className="nav-item" onClick={() => setMainNav('db_explorer')} style={{ cursor: 'pointer' }}>
          <Activity size={18} /> Reports
        </div>

        <div className="nav-item" onClick={() => setMainNav('db_explorer')} style={{ cursor: 'pointer' }}>
          <Clock3 size={18} /> Audit log
        </div>

        <div className="sidebar-bottom">
          <div className="help">
            <CircleHelp size={17} />
            <div>
              <b>Need help?</b>
              <small>View setup guide</small>
            </div>
          </div>
          <div className="profile">
            <div className="avatar">A</div>
            <div>
              <b>Workspace admin</b>
              <small>Local environment</small>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main">
        <header className="topbar">
          <div className="crumb">
            Workspace <span>/</span> {mainNav === 'db_explorer' ? 'Database Explorer' : 'Automated Scraper'}
          </div>

          <div className="top-actions">
            <div className={`connection ${health}`}>
              <i /> API {health === 'online' ? 'Connected' : health === 'checking' ? 'Checking' : 'Offline'}
            </div>

            <button className="icon-btn" onClick={() => void load()} title="Refresh status">
              <RefreshCw size={17} />
            </button>

            <div className="avatar small">A</div>
          </div>
        </header>

        <section className="content">
          {error && <div className="alert"><b>Connection or request issue:</b> {error}</div>}

          {mainNav === 'db_explorer' ? (
            <DatabaseExplorer
              sites={sites}
              onNotify={notify}
              refreshKey={dbRefreshKey}
            />
          ) : (
            <div>
              {/* Overview Header */}
              <div className="welcome">
                <div>
                  <div className="eyebrow">AUTOMATED WEB SCRAPING</div>
                  <h1>AI Scraper Control Center</h1>
                  <p>Execute end-to-end automated scraping: Capture → Screenshot → HTML → AI Selectors → Extraction → SQLite Storage.</p>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button className="secondary" onClick={() => setMainNav('db_explorer')}>
                    <Database size={16} /> Open Database Explorer
                  </button>
                  <button className="primary" onClick={() => setShowForm(true)}>
                    <Plus size={16} /> Register Website
                  </button>
                </div>
              </div>

              {/* Instant Automated Capture Bar */}
              <div style={{
                background: '#ffffff',
                border: '1px solid #dce8e8',
                borderRadius: '12px',
                padding: '20px',
                marginBottom: '28px',
                boxShadow: '0 4px 14px #0f4f5209'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Sparkles size={17} color="#137f83" />
                  <strong style={{ fontSize: '13px', color: '#17263a' }}>Instant Automated Capture & Extraction</strong>
                  <span className="badge teal">Zero Configuration Required</span>
                </div>

                <form
                  onSubmit={e => {
                    e.preventDefault();
                    if (quickUrl.trim()) {
                      void runCapturePipeline(quickUrl.trim());
                    }
                  }}
                  style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}
                >
                  <div style={{ flex: 1, minWidth: '280px', display: 'flex', alignItems: 'center', background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '8px', padding: '0 12px' }}>
                    <Globe2 size={16} color="#94a3b8" />
                    <input
                      required
                      type="url"
                      placeholder="Enter website URL (e.g. https://books.toscrape.com or an Amazon catalog)..."
                      value={quickUrl}
                      onChange={e => setQuickUrl(e.target.value)}
                      style={{ border: '0', background: 'transparent', outline: 'none', padding: '11px', width: '100%', font: "12px 'DM Sans'" }}
                    />
                  </div>

                  <button
                    type="submit"
                    className="primary"
                    disabled={isProcessing}
                    style={{ padding: '0 20px', height: '42px', fontSize: '13px' }}
                  >
                    {quickCapturing ? (
                      <>
                        <RefreshCw size={15} className="animate-spin" /> Processing...
                      </>
                    ) : (
                      <>
                        <Camera size={15} /> Capture & Extract Now
                      </>
                    )}
                  </button>
                </form>

                {/* Live Pipeline Stepper */}
                {isProcessing && (
                  <div className="pipeline-stepper">
                    <div className={`step-item ${captureStage >= 1 ? (captureStage === 1 ? 'active' : 'done') : ''}`}>
                      <div className="step-circle">{captureStage > 1 ? '✓' : '1'}</div>
                      <span>Capture Webpage</span>
                    </div>
                    <span className="step-arrow">→</span>

                    <div className={`step-item ${captureStage >= 2 ? (captureStage === 2 ? 'active' : 'done') : ''}`}>
                      <div className="step-circle">{captureStage > 2 ? '✓' : '2'}</div>
                      <span>Screenshot & HTML</span>
                    </div>
                    <span className="step-arrow">→</span>

                    <div className={`step-item ${captureStage >= 3 ? (captureStage === 3 ? 'active' : 'done') : ''}`}>
                      <div className="step-circle">{captureStage > 3 ? '✓' : '3'}</div>
                      <span>AI Selectors / Config</span>
                    </div>
                    <span className="step-arrow">→</span>

                    <div className={`step-item ${captureStage >= 4 ? (captureStage === 4 ? 'active' : 'done') : ''}`}>
                      <div className="step-circle">{captureStage > 4 ? '✓' : '4'}</div>
                      <span>Extract Records</span>
                    </div>
                    <span className="step-arrow">→</span>

                    <div className={`step-item ${captureStage >= 5 ? 'done' : ''}`}>
                      <div className="step-circle">{captureStage >= 5 ? '✓' : '5'}</div>
                      <span>Saved to SQLite</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Statistics Overview */}
              <div className="stats">
                <Stat icon={<Globe2 />} label="Registered Targets" value={String(sites.length)} note="Managed in workspace" />
                <Stat icon={<Activity />} label="Automation Engine" value="Ready" note="Playwright Chromium + Async loop" />
                <Stat icon={<Database />} label="Database Persistence" value="SQLite" note="Real product records saved" />
                <Stat icon={<Bot />} label="AI Self-Healing" value="Active" note="Deterministic selector inference" />
              </div>

              {/* Latest Capture & Automated Extraction Results */}
              {latestCapture && (
                <div className="capture-result" style={{ border: '2px solid #bce1e3', background: '#ffffff' }}>
                  <div className="capture-result-head">
                    <div>
                      <div className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span>LATEST CAPTURE RESULT · #{latestCapture.id}</span>
                        {latestCapture.extraction?.status === 'completed' && (
                          <span className="badge green">Extraction Completed</span>
                        )}
                      </div>
                      <h2>{latestCapture.page_title || 'Captured Webpage'}</h2>
                      <p style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Globe2 size={13} /> {latestCapture.final_url}
                      </p>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="capture-code">{latestCapture.status_code ?? '200'} HTTP</span>
                    </div>
                  </div>

                  {/* Metrics */}
                  <div className="capture-metrics">
                    <div>
                      <b>{latestCapture.load_time_ms.toLocaleString()} ms</b>
                      <small>Page load time</small>
                    </div>
                    <div>
                      <b>{latestCapture.html_characters.toLocaleString()}</b>
                      <small>HTML characters</small>
                    </div>
                    <div>
                      <b>{latestCapture.cleaned_html_characters.toLocaleString()}</b>
                      <small>Cleaned DOM characters</small>
                    </div>
                  </div>

                  {/* Screenshot Preview */}
                  {latestCapture.screenshot_url && (
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: '#334458', display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <Camera size={13} color="#137f83" /> Rendered Screenshot Preview:
                        </span>
                        <div style={{ display: 'flex', gap: '10px' }}>
                          <a
                            className="screenshot-link"
                            href={`${apiBase}${latestCapture.screenshot_url}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open Full-Res Screenshot ↗
                          </a>
                          <a
                            className="screenshot-link"
                            href={`${apiBase}/api/capture/${latestCapture.id}/html`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View Raw HTML ↗
                          </a>
                        </div>
                      </div>

                      <div className="screenshot-box">
                        <img
                          src={`${apiBase}${latestCapture.screenshot_url}`}
                          alt="Captured webpage screenshot"
                          className="screenshot-img"
                        />
                      </div>
                    </div>
                  )}

                  {/* Extraction Outcome Banner & Extracted Products Preview */}
                  {latestCapture.extraction && (
                    <div className={`extracted-box ${latestCapture.extraction.status}`}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          {latestCapture.extraction.status === 'completed' ? (
                            <CheckCircle2 size={22} color="#16a34a" />
                          ) : latestCapture.extraction.status === 'needs_configuration' || latestCapture.extraction.status === 'empty' ? (
                            <AlertCircle size={22} color="#d97706" />
                          ) : (
                            <AlertCircle size={22} color="#dc2626" />
                          )}
                          <div>
                            <strong style={{ fontSize: '14px', color: '#142234' }}>
                              {latestCapture.extraction.status === 'completed'
                                ? `Successfully Extracted ${latestCapture.extraction.record_count} Records!`
                                : latestCapture.extraction.status === 'empty'
                                ? `0 Records Matched — Selectors May Need Updating`
                                : latestCapture.extraction.status === 'needs_configuration'
                                ? 'AI Configuration Failed'
                                : 'Extraction Note'}
                            </strong>
                            <p style={{ margin: '2px 0 0', fontSize: '11px', color: '#475569' }}>
                              {latestCapture.extraction.message}
                            </p>
                          </div>
                        </div>

                        {latestCapture.extraction.status === 'completed' && latestCapture.extraction.run_id && (
                          <div style={{ display: 'flex', gap: '8px' }}>
                            <button
                              className="secondary"
                              onClick={() => setMainNav('db_explorer')}
                              style={{ fontSize: '11px' }}
                            >
                              <Package size={13} /> View in Database Explorer
                            </button>

                            <button
                              className="primary"
                              onClick={() => handleDownloadRunCsv(latestCapture.extraction!.run_id!)}
                              disabled={downloadingRunId === latestCapture.extraction.run_id}
                              style={{ fontSize: '11px' }}
                            >
                              <Download size={13} />{' '}
                              {downloadingRunId === latestCapture.extraction.run_id ? 'Exporting...' : 'Download Run CSV'}
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Sample Extracted Products Preview */}
                      {latestCapture.extraction.records && latestCapture.extraction.records.length > 0 && (
                        <div style={{ marginTop: '14px' }}>
                          <span style={{ fontSize: '10px', fontWeight: 700, color: '#166534', textTransform: 'uppercase', letterSpacing: '0.6px', display: 'block', marginBottom: '8px' }}>
                            Harvested Records Preview (Saved to SQLite):
                          </span>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '8px' }}>
                            {latestCapture.extraction.records.slice(0, 4).map((rec, idx) => (
                              <div
                                key={idx}
                                style={{
                                  background: '#ffffff',
                                  border: '1px solid #cbd5e1',
                                  borderRadius: '6px',
                                  padding: '10px 12px',
                                  fontSize: '11px'
                                }}
                              >
                                <b style={{ display: 'block', color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {rec.title || rec.name || 'Untitled item'}
                                </b>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '6px' }}>
                                  <span style={{ color: '#0d9488', fontWeight: 700 }}>{rec.price || '—'}</span>
                                  <span style={{ color: '#64748b', fontSize: '10px' }}>{rec.rating || rec.availability || 'In stock'}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Collapsible Cleaned HTML Preview */}
                  <details style={{ marginTop: '14px' }}>
                    <summary style={{ cursor: 'pointer', fontSize: '11px', fontWeight: 700, color: '#536276', display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <FileCode size={13} /> View Cleaned HTML Preview
                    </summary>
                    <pre>{latestCapture.cleaned_html_preview}</pre>
                  </details>
                </div>
              )}

              {/* Registered Targets Table */}
              <div className="section-head">
                <div>
                  <h2>Registered Websites</h2>
                  <p>Your saved scraping targets with pre-configured schemas</p>
                </div>
                <div className="table-tools">
                  <div className="search">
                    <Search size={16} />
                    <input
                      placeholder="Search websites..."
                      value={query}
                      onChange={e => setQuery(e.target.value)}
                    />
                  </div>
                  <button className="secondary" onClick={() => void load()}>
                    <RefreshCw size={15} /> Refresh
                  </button>
                </div>
              </div>

              <div className="table-card">
                <table>
                  <thead>
                    <tr>
                      <th>WEBSITE</th>
                      <th>STATUS</th>
                      <th>SCHEDULE</th>
                      <th>FIELDS</th>
                      <th>ADDED</th>
                      <th>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(site => (
                      <tr key={site.id}>
                        <td>
                          <div className="site-cell">
                            <div className="site-icon"><Globe2 size={17} /></div>
                            <div>
                              <b>{site.name}</b>
                              <small>{site.url}</small>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className={`status ${site.status}`}>{site.status.replace('_', ' ')}</span>
                        </td>
                        <td>Manual</td>
                        <td>{site.fields.length} fields</td>
                        <td>{new Date(site.created_at).toLocaleDateString()}</td>
                        <td>
                          <button
                            className="secondary capture-btn"
                            disabled={isProcessing}
                            onClick={() => void runCapturePipeline(site.url, site.id)}
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                          >
                            <Camera size={12} /> {capturing === site.id ? 'Capturing...' : 'Capture & Extract'}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={6}>
                          <div className="empty">
                            <div className="empty-icon"><Globe2 /></div>
                            <b>{query ? 'No matching websites' : 'No websites registered yet'}</b>
                            <p>{query ? 'Try another search query.' : 'Add a website or use the Instant Capture bar above.'}</p>
                            {!query && (
                              <button className="primary" onClick={() => setShowForm(true)}>
                                <Plus size={16} /> Register First Website
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Information Cards */}
              <div className="bottom-grid">
                <div className="info-card">
                  <div className="info-icon blue"><Bot /></div>
                  <div>
                    <b>Intelligent Configuration Matching</b>
                    <p>The pipeline automatically tests captured HTML against existing site configurations or infers new selectors via Groq AI without manual intervention.</p>
                  </div>
                </div>
                <div className="info-card">
                  <div className="info-icon green"><ShieldCheck /></div>
                  <div>
                    <b>Direct SQLite Ingestion</b>
                    <p>Extracted records are immediately indexed into your local SQLite products table and exportable as standard CSV files.</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          <footer>ScraperOps <span>•</span> Local SQLite Engine <span>•</span> Built for transparent, verifiable extraction</footer>
        </section>
      </main>

      {/* Add Website Modal */}
      {showForm && (
        <div className="modal-backdrop" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>Register a website</h2>
                <p>Register a public website as a scraping target.</p>
              </div>
              <button className="icon-btn" onClick={() => setShowForm(false)}><X /></button>
            </div>
            <form onSubmit={addSite}>
              <label>Website name</label>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Books to Scrape" />
              <label>Website URL *</label>
              <input required type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com" />
              <div className="form-note">
                Only public websites you are authorized to access. Local/private network targets are blocked by security validation.
              </div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowForm(false)}>Cancel</button>
                <button className="primary" disabled={busy}>{busy ? 'Registering...' : 'Save Website'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Toast Feedback */}
      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          <span>{toast.message}</span>
        </div>
      )}
    </div>
  );
}

function Stat({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: string; note: string }) {
  return (
    <div className="stat">
      <div className="stat-top">
        <span>{label}</span>
        <div className="stat-icon">{icon}</div>
      </div>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
