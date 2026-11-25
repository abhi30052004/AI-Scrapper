import React from 'react';
import { Database, Package, Globe2, Activity, Clock, CheckCircle2, AlertCircle, Download, ArrowRight, Table, Trash2 } from 'lucide-react';
import type { DatabaseOverview } from '../api';

interface Props {
  overview: DatabaseOverview | null;
  loading: boolean;
  onSelectTab: (tab: 'overview' | 'tables' | 'products' | 'recent' | 'runs') => void;
  onExportAll: () => void;
  exporting: boolean;
  onDeleteTable: (target: 'all' | string) => void;
  deleting: boolean;
}

export function DatabaseOverviewView({
  overview,
  loading,
  onSelectTab,
  onExportAll,
  exporting,
  onDeleteTable,
  deleting,
}: Props) {
  if (loading && !overview) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: '#8595aa' }}>
        <Activity className="animate-spin" size={24} style={{ margin: '0 auto 12px' }} />
        <p>Loading database information...</p>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="alert">
        <b>Database connection failed:</b> Could not retrieve overview information from the backend.
      </div>
    );
  }

  const isConnected = overview.connection_status === 'connected';

  return (
    <div>
      {/* Database Status Banner */}
      <div style={{
        background: '#ffffff',
        border: '1px solid #e9edf3',
        borderRadius: '10px',
        padding: '16px 20px',
        marginBottom: '24px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '12px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div className="stat-icon" style={{ width: '40px', height: '40px' }}>
            <Database size={22} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <strong style={{ fontSize: '15px', color: '#17263a' }}>SQLite: {overview.database_name}</strong>
              <span className={`db-pill ${isConnected ? '' : 'disconnected'}`}>
                {isConnected ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                {isConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            <small style={{ color: '#8595aa', fontSize: '11px', display: 'block', marginTop: '2px' }}>
              Local storage engine • Size: {overview.database_size_formatted} • {overview.total_tables} managed tables
            </small>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button className="secondary" onClick={() => onSelectTab('tables')}>
            <Table size={15} /> Explore Tables
          </button>
          <button className="primary" onClick={onExportAll} disabled={exporting}>
            <Download size={15} /> {exporting ? 'Generating CSV...' : 'Export All Products CSV'}
          </button>
          <button
            onClick={() => onDeleteTable('all')}
            disabled={deleting}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '0 14px',
              height: '38px',
              borderRadius: '8px',
              background: '#fef2f2',
              color: '#dc2626',
              border: '1px solid #fecaca',
              fontWeight: 700,
              fontSize: '12px',
              cursor: 'pointer',
            }}
            title="Clear all data from every table"
          >
            <Trash2 size={14} /> Clear All DB
          </button>
        </div>
      </div>

      {/* Overview Stat Cards */}
      <div className="stats">
        <div className="stat">
          <div className="stat-top">
            <span>Total Products</span>
            <div className="stat-icon"><Package size={17} /></div>
          </div>
          <strong>{overview.total_products.toLocaleString()}</strong>
          <small>Indexed in SQLite database</small>
        </div>

        <div className="stat">
          <div className="stat-top">
            <span>Database Tables</span>
            <div className="stat-icon"><Table size={17} /></div>
          </div>
          <strong>{overview.total_tables}</strong>
          <small>Registered schema tables</small>
        </div>

        <div className="stat">
          <div className="stat-top">
            <span>Registered Websites</span>
            <div className="stat-icon"><Globe2 size={17} /></div>
          </div>
          <strong>{overview.total_sites}</strong>
          <small>Scraping target websites</small>
        </div>

        <div className="stat">
          <div className="stat-top">
            <span>Extraction Runs</span>
            <div className="stat-icon"><Activity size={17} /></div>
          </div>
          <strong>{overview.total_runs}</strong>
          <small>Executed crawler runs</small>
        </div>
      </div>

      {/* Latest Scraping & Quick Links */}
      <div className="bottom-grid" style={{ marginBottom: '28px' }}>
        <div className="info-card">
          <div className="info-icon blue"><Clock size={18} /></div>
          <div>
            <b>Latest Scraping Activity</b>
            <p style={{ marginTop: '4px', fontSize: '12px', color: '#334458', fontWeight: 600 }}>
              {overview.latest_scraping_timestamp
                ? new Date(overview.latest_scraping_timestamp).toLocaleString()
                : 'No extraction runs completed yet'}
            </p>
            <p style={{ fontSize: '11px', color: '#8595aa', marginTop: '4px' }}>
              Records are automatically extracted from DOM HTML and saved to SQLite with full lineage.
            </p>
          </div>
        </div>

        <div className="info-card">
          <div className="info-icon green"><Package size={18} /></div>
          <div>
            <b>Scraped Products Repository</b>
            <p style={{ fontSize: '11px', color: '#8595aa', marginTop: '4px' }}>
              Explore real product titles, prices, ratings, availability and URLs directly from local SQLite.
            </p>
            <button
              onClick={() => onSelectTab('products')}
              style={{
                marginTop: '10px',
                background: 'transparent',
                border: '0',
                padding: '0',
                color: '#137f83',
                fontWeight: 700,
                fontSize: '11px',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}
            >
              Open Products Management <ArrowRight size={13} />
            </button>
          </div>
        </div>
      </div>

      {/* Tables Breakdown */}
      <div className="section-head">
        <div>
          <h2>Available Database Tables</h2>
          <p>Real schema tables currently stored in {overview.database_name}</p>
        </div>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>TABLE NAME</th>
              <th>RECORD COUNT</th>
              <th>COLUMNS</th>
              <th>STORAGE ROLE</th>
              <th>ACTION</th>
            </tr>
          </thead>
          <tbody>
            {overview.tables.map(t => (
              <tr key={t.name}>
                <td>
                  <strong style={{ color: '#17263a', fontSize: '12px' }}>{t.name}</strong>
                </td>
                <td>
                  <span className="badge blue">{t.row_count.toLocaleString()} rows</span>
                </td>
                <td>
                  <span className="badge teal">{t.column_count} fields</span>
                </td>
                <td>
                  <small style={{ color: '#7a899c' }}>
                    {t.name === 'products' && 'Scraped items and extracted attributes'}
                    {t.name === 'sites' && 'Registered target website configurations'}
                    {t.name === 'extraction_runs' && 'Crawler executions and raw JSON'}
                    {t.name === 'scraper_configs' && 'AI-generated selector versions'}
                    {t.name === 'capture_runs' && 'DOM snapshots and screenshot artifacts'}
                    {t.name === 'repair_history' && 'Self-healing logs and audit reports'}
                    {t.name === 'change_reports' && 'Field diff comparisons across runs'}
                    {t.name === 'site_fields' && 'Target field requirements'}
                  </small>
                </td>
                <td>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    <button
                      className="secondary"
                      style={{ padding: '5px 10px', fontSize: '11px' }}
                      onClick={() => onSelectTab(t.name === 'products' ? 'products' : 'tables')}
                    >
                      View Table ↗
                    </button>
                    <button
                      onClick={() => onDeleteTable(t.name)}
                      disabled={deleting || t.row_count === 0}
                      style={{
                        padding: '5px 8px',
                        fontSize: '11px',
                        borderRadius: '6px',
                        border: '1px solid #fecaca',
                        background: '#fef2f2',
                        color: t.row_count === 0 ? '#94a3b8' : '#dc2626',
                        cursor: t.row_count === 0 ? 'not-allowed' : 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '3px',
                      }}
                      title={`Clear all rows in table '${t.name}'`}
                    >
                      <Trash2 size={12} /> Clear
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
