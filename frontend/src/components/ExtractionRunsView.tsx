import React, { useState } from 'react';
import { Activity, Download, RefreshCw, Hash, Globe2, Clock, ArrowRight } from 'lucide-react';
import { downloadCsv, type ExtractionRun } from '../api';

interface Props {
  runs: ExtractionRun[];
  loading: boolean;
  onRefresh: () => void;
  onViewRun: (runId: number) => void;
  onNotify: (msg: string, type: 'success' | 'error') => void;
}

export function ExtractionRunsView({ runs, loading, onRefresh, onViewRun, onNotify }: Props) {
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  async function handleDownloadCsv(runId: number) {
    setDownloadingId(runId);
    try {
      const filename = await downloadCsv(`/api/extraction/runs/${runId}/export?format=csv`, `extraction_${runId}.csv`);
      onNotify(`Downloaded ${filename} successfully!`, 'success');
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Download failed', 'error');
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div>
      <div className="section-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2>Extraction Runs History</h2>
            <span className="badge blue">{runs.length} runs completed</span>
          </div>
          <p>Chronological audit log of all crawler sessions and their data outputs</p>
        </div>

        <div className="table-tools">
          <button className="secondary" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>RUN ID</th>
              <th>START URL</th>
              <th>CONFIG VERSION</th>
              <th>PAGES CRAWLED</th>
              <th>PRODUCTS EXTRACTED</th>
              <th>SCRAPED TIMESTAMP</th>
              <th style={{ textAlign: 'right' }}>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {loading && runs.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '36px' }}>
                  <RefreshCw className="animate-spin" size={20} style={{ margin: '0 auto 8px' }} />
                  <p style={{ margin: 0 }}>Loading extraction runs...</p>
                </td>
              </tr>
            ) : runs.length > 0 ? (
              runs.map(run => (
                <tr key={run.id}>
                  <td>
                    <span className="badge blue" style={{ gap: '3px' }}>
                      <Hash size={11} /> Run #{run.id}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Globe2 size={13} color="#188b8d" />
                      <b style={{ color: '#17263a', fontSize: '12px' }}>{run.start_url}</b>
                    </div>
                  </td>
                  <td>
                    <span className="badge teal">Config #{run.config_id}</span>
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, color: '#334458' }}>{run.pages_crawled} page(s)</span>
                  </td>
                  <td>
                    <span className="badge green" style={{ fontSize: '11px', fontWeight: 700 }}>
                      {run.record_count.toLocaleString()} products
                    </span>
                  </td>
                  <td>
                    <small style={{ color: '#8898aa', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Clock size={12} /> {new Date(run.created_at).toLocaleString()}
                    </small>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: '6px' }}>
                      <button
                        className="secondary"
                        style={{ padding: '5px 10px', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                        onClick={() => onViewRun(run.id)}
                      >
                        Products <ArrowRight size={12} />
                      </button>

                      <button
                        className="primary"
                        style={{ padding: '5px 10px', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                        onClick={() => handleDownloadCsv(run.id)}
                        disabled={downloadingId === run.id}
                      >
                        <Download size={12} /> {downloadingId === run.id ? '...' : 'CSV'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={7}>
                  <div className="empty">
                    <div className="empty-icon"><Activity /></div>
                    <b>No extraction runs found</b>
                    <p>Scrape a website to generate extraction runs and product records.</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
