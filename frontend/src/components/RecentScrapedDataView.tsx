import React, { useEffect, useState } from 'react';
import { Activity, Download, RefreshCw, Package, Globe2, Hash, Clock, ArrowRight, ExternalLink } from 'lucide-react';
import { request, downloadCsv, type ExtractionRun, type Product } from '../api';
import { ProductDetailModal } from './ProductDetailModal';

interface Props {
  onNotify: (msg: string, type: 'success' | 'error') => void;
  onFilterByRunInProducts: (runId: number) => void;
}

export function RecentScrapedDataView({ onNotify, onFilterByRunInProducts }: Props) {
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<ExtractionRun | null>(null);
  const [runProducts, setRunProducts] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [exportingRunId, setExportingRunId] = useState<number | null>(null);
  const [inspectProduct, setInspectProduct] = useState<Product | null>(null);

  async function loadRuns() {
    setLoading(true);
    try {
      const data = await request<ExtractionRun[]>('/api/extraction/runs');
      setRuns(data);
      if (data.length > 0 && !selectedRun) {
        void loadRunDetails(data[0]);
      }
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Failed to load extraction runs', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function loadRunDetails(run: ExtractionRun) {
    setSelectedRun(run);
    setLoadingProducts(true);
    try {
      const res = await request<{ records: Record<string, any>[] }>(`/api/extraction/runs/${run.id}`);
      const mapped: Product[] = (res.records || []).map((r, i) => ({
        id: i + 1,
        run_id: run.id,
        title: r.title || r.name || 'Untitled item',
        price: r.price ? String(r.price) : null,
        rating: r.rating ? String(r.rating) : null,
        availability: r.availability ? String(r.availability) : null,
        product_url: r.product_url || r.url || null,
        scraped_at: run.created_at,
        site_name: run.start_url,
        raw_data: r,
      }));
      setRunProducts(mapped);
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Failed to load products for run', 'error');
    } finally {
      setLoadingProducts(false);
    }
  }

  useEffect(() => {
    void loadRuns();
  }, []);

  async function handleExportRunCsv(runId: number, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    setExportingRunId(runId);
    try {
      const filename = await downloadCsv(`/api/extraction/runs/${runId}/export?format=csv`, `extraction_${runId}.csv`);
      onNotify(`Downloaded ${filename} successfully!`, 'success');
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Export failed', 'error');
    } finally {
      setExportingRunId(null);
    }
  }

  return (
    <div>
      <div className="section-head">
        <div>
          <h2>Recent Scraped Data</h2>
          <p>Review recent crawling executions and their harvested product batches</p>
        </div>

        <div className="table-tools">
          <button className="secondary" onClick={() => void loadRuns()} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh Runs
          </button>
        </div>
      </div>

      {/* Two columns: Runs List on Left, Run Products on Right */}
      <div className="tables-layout" style={{ gridTemplateColumns: '320px 1fr' }}>
        {/* Runs List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ fontSize: '11px', fontWeight: 700, color: '#7a899c', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
            Latest Extraction Runs ({runs.length})
          </div>

          {loading && runs.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: '#8d9caa' }}>
              <RefreshCw className="animate-spin" size={18} style={{ margin: '0 auto 8px' }} />
              <small>Loading runs...</small>
            </div>
          ) : runs.length > 0 ? (
            runs.map(run => {
              const isSelected = selectedRun?.id === run.id;
              return (
                <div
                  key={run.id}
                  onClick={() => void loadRunDetails(run)}
                  style={{
                    background: isSelected ? '#ffffff' : '#ffffff',
                    border: isSelected ? '2px solid #137f83' : '1px solid #e2e8f0',
                    borderRadius: '10px',
                    padding: '14px 16px',
                    cursor: 'pointer',
                    boxShadow: isSelected ? '0 4px 12px #137f8315' : '0 1px 3px #13243a08',
                    transition: 'all .15s ease'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span className="badge blue" style={{ gap: '3px' }}>
                      <Hash size={11} /> Run #{run.id}
                    </span>
                    <span className="badge green" style={{ fontSize: '9px' }}>
                      {run.record_count} items
                    </span>
                  </div>

                  <div style={{ fontSize: '12px', fontWeight: 700, color: '#17263a', wordBreak: 'break-all', marginBottom: '4px' }}>
                    {run.start_url}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px', fontSize: '11px', color: '#8898aa' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <Clock size={12} /> {new Date(run.created_at).toLocaleDateString()}
                    </span>

                    <button
                      className="secondary"
                      style={{ padding: '4px 8px', fontSize: '10px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                      onClick={e => handleExportRunCsv(run.id, e)}
                      disabled={exportingRunId === run.id}
                    >
                      <Download size={11} /> {exportingRunId === run.id ? '...' : 'CSV'}
                    </button>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="empty" style={{ padding: '30px' }}>
              <Activity size={24} color="#8595aa" />
              <b style={{ display: 'block', marginTop: '8px' }}>No runs yet</b>
              <small style={{ color: '#8d9caa' }}>Execute an extraction to see batch history.</small>
            </div>
          )}
        </div>

        {/* Selected Run Details & Products List */}
        <div style={{ minWidth: 0 }}>
          {selectedRun ? (
            <div>
              <div style={{
                background: '#ffffff',
                border: '1px solid #e8edf3',
                borderRadius: '10px',
                padding: '16px 20px',
                marginBottom: '16px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '12px'
              }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <h2 style={{ fontSize: '16px', margin: 0 }}>Run #{selectedRun.id} Harvested Batch</h2>
                    <span className="badge green">{selectedRun.record_count} products</span>
                  </div>
                  <small style={{ color: '#8595aa', display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                    <Globe2 size={13} /> {selectedRun.start_url} • Crawled {selectedRun.pages_crawled} page(s)
                  </small>
                </div>

                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    className="secondary"
                    onClick={() => onFilterByRunInProducts(selectedRun.id)}
                    style={{ fontSize: '11px' }}
                  >
                    Open in Products Table <ArrowRight size={13} />
                  </button>

                  <button
                    className="primary"
                    onClick={() => handleExportRunCsv(selectedRun.id)}
                    disabled={exportingRunId === selectedRun.id}
                    style={{ fontSize: '11px' }}
                  >
                    <Download size={14} /> {exportingRunId === selectedRun.id ? 'Exporting...' : 'Export Run CSV'}
                  </button>
                </div>
              </div>

              {/* Products in this run */}
              <div className="table-card" style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>PRODUCT NAME</th>
                      <th>PRICE</th>
                      <th>RATING</th>
                      <th>AVAILABILITY</th>
                      <th style={{ textAlign: 'right' }}>DETAILS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loadingProducts ? (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', padding: '32px' }}>
                          <RefreshCw className="animate-spin" size={18} style={{ margin: '0 auto 8px' }} />
                          <small>Loading run records...</small>
                        </td>
                      </tr>
                    ) : runProducts.length > 0 ? (
                      runProducts.map((p, idx) => (
                        <tr
                          key={idx}
                          className="table-row-clickable"
                          onClick={() => setInspectProduct(p)}
                        >
                          <td>
                            <span className="badge" style={{ fontFamily: 'monospace' }}>{idx + 1}</span>
                          </td>
                          <td style={{ maxWidth: '300px' }}>
                            <b style={{ color: '#17263a', fontSize: '12px', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.title || ''}>
                              {p.title}
                            </b>
                            {p.product_url && (
                              <small style={{ color: '#8d9caa', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {p.product_url}
                              </small>
                            )}
                          </td>
                          <td>
                            <strong style={{ color: '#137f83', fontSize: '12px' }}>{p.price || '—'}</strong>
                          </td>
                          <td>
                            <small style={{ color: '#556679', fontWeight: 600 }}>{p.rating || '—'}</small>
                          </td>
                          <td>
                            <span className={`badge ${p.availability?.toLowerCase().includes('in stock') ? 'green' : 'amber'}`}>
                              {p.availability || 'Unknown'}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              className="secondary"
                              style={{ padding: '3px 8px', fontSize: '10px' }}
                              onClick={e => {
                                e.stopPropagation();
                                setInspectProduct(p);
                              }}
                            >
                              Inspect
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', padding: '24px', color: '#8898aa' }}>
                          No records extracted in this run.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="table-card" style={{ padding: '48px', textAlign: 'center', color: '#8595aa' }}>
              <Package size={28} style={{ margin: '0 auto 10px', color: '#8595aa' }} />
              <b>Select an extraction run</b>
              <p style={{ fontSize: '11px', margin: '4px 0 0' }}>Click a run on the left to view and export its scraped items.</p>
            </div>
          )}
        </div>
      </div>

      <ProductDetailModal
        product={inspectProduct}
        onClose={() => setInspectProduct(null)}
      />
    </div>
  );
}
