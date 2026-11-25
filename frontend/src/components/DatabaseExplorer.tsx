import React, { useEffect, useState } from 'react';
import { Database, Table, Package, Clock, Activity, Download, RefreshCw, LayoutDashboard, Trash2 } from 'lucide-react';
import { request, downloadCsv, type DatabaseOverview, type TableMetadata, type Site, type ExtractionRun } from '../api';
import { DatabaseOverviewView } from './DatabaseOverviewView';
import { DatabaseTablesView } from './DatabaseTablesView';
import { ProductsManagementView } from './ProductsManagementView';
import { RecentScrapedDataView } from './RecentScrapedDataView';
import { ExtractionRunsView } from './ExtractionRunsView';
import { ConfirmDeleteModal } from './ConfirmDeleteModal';

interface Props {
  sites: Site[];
  onNotify: (msg: string, type: 'success' | 'error') => void;
  refreshKey?: number;
}

type ExplorerTab = 'overview' | 'tables' | 'products' | 'recent' | 'runs';

export function DatabaseExplorer({ sites, onNotify, refreshKey = 0 }: Props) {
  const [activeTab, setActiveTab] = useState<ExplorerTab>('overview');
  const [overview, setOverview] = useState<DatabaseOverview | null>(null);
  const [tables, setTables] = useState<TableMetadata[]>([]);
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [exportingAll, setExportingAll] = useState(false);
  const [targetRunFilter, setTargetRunFilter] = useState<number | null>(null);

  // Delete modal state
  const [deleteModal, setDeleteModal] = useState<{
    open: boolean;
    target: 'all' | string;   // 'all' or a table name
    confirmText: string;
    title: string;
    description: string;
  }>({ open: false, target: 'all', confirmText: '', title: '', description: '' });
  const [deleting, setDeleting] = useState(false);

  async function loadData() {
    setLoading(true);
    try {
      const [ov, tbls, rns] = await Promise.all([
        request<DatabaseOverview>('/api/database/overview'),
        request<TableMetadata[]>('/api/database/tables'),
        request<ExtractionRun[]>('/api/extraction/runs'),
      ]);
      setOverview(ov);
      setTables(tbls);
      setRuns(rns);
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Failed to load database information', 'error');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [refreshKey]);

  async function handleExportAllCsv() {
    setExportingAll(true);
    try {
      const filename = await downloadCsv('/api/products/export', 'products_export.csv');
      onNotify(`Downloaded ${filename} successfully!`, 'success');
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Export failed', 'error');
    } finally {
      setExportingAll(false);
    }
  }

  function handleFilterByRunInProducts(runId: number) {
    setTargetRunFilter(runId);
    setActiveTab('products');
  }

  /** Open the confirmation modal for a specific table or for all tables */
  function askDelete(target: 'all' | string) {
    if (target === 'all') {
      setDeleteModal({
        open: true,
        target: 'all',
        confirmText: 'DELETE ALL',
        title: 'Clear Entire Database',
        description:
          'All rows in every table will be permanently deleted: products, extraction_runs, scraper_configs, capture_runs, sites, and more. ' +
          'The table schemas are preserved but all data will be lost.',
      });
    } else {
      setDeleteModal({
        open: true,
        target,
        confirmText: target.toUpperCase(),
        title: `Clear Table: ${target}`,
        description:
          `All ${tables.find(t => t.name === target)?.row_count.toLocaleString() ?? ''} row(s) in the "${target}" table will be permanently deleted. ` +
          'The table schema and other tables are not affected.',
      });
    }
  }

  async function handleDeleteConfirmed() {
    setDeleting(true);
    setDeleteModal(m => ({ ...m, open: false }));
    try {
      let res: any;
      if (deleteModal.target === 'all') {
        res = await request<any>('/api/database/all', { method: 'DELETE' });
        onNotify(`Cleared all data: ${res.total_rows_deleted} row(s) deleted across ${Object.keys(res.tables_cleared).length} tables.`, 'success');
      } else {
        res = await request<any>(`/api/database/tables/${deleteModal.target}`, { method: 'DELETE' });
        onNotify(`Table "${deleteModal.target}" cleared: ${res.rows_deleted} row(s) deleted.`, 'success');
      }
      await loadData();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Delete failed', 'error');
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div>
      {/* Confirmation Modal */}
      <ConfirmDeleteModal
        isOpen={deleteModal.open}
        title={deleteModal.title}
        description={deleteModal.description}
        confirmText={deleteModal.confirmText}
        onConfirm={handleDeleteConfirmed}
        onCancel={() => setDeleteModal(m => ({ ...m, open: false }))}
      />

      {/* Module Header */}
      <div className="welcome">
        <div>
          <div className="eyebrow">SQLITE DATA MANAGEMENT</div>
          <h1>Database Explorer</h1>
          <p>Inspect raw SQLite tables, explore scraped product inventories, and export clean CSV datasets.</p>
        </div>

        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button className="primary" onClick={handleExportAllCsv} disabled={exportingAll}>
            <Download size={16} /> {exportingAll ? 'Exporting...' : 'Export All CSV'}
          </button>
          <button className="secondary" onClick={() => void loadData()} disabled={loading} title="Refresh database">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button
            onClick={() => askDelete('all')}
            disabled={deleting}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '0 14px', height: '38px', borderRadius: '8px',
              background: '#fef2f2', color: '#dc2626',
              border: '1.5px solid #fecaca', fontWeight: 700,
              fontSize: '12px', cursor: 'pointer',
            }}
            title="Clear all data from every table"
          >
            <Trash2 size={14} /> Clear All Data
          </button>
        </div>
      </div>

      {/* Subnavigation Tabs */}
      <div className="subnav">
        <button
          className={`subnav-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <LayoutDashboard size={15} /> Overview
        </button>

        <button
          className={`subnav-btn ${activeTab === 'products' ? 'active' : ''}`}
          onClick={() => { setTargetRunFilter(null); setActiveTab('products'); }}
        >
          <Package size={15} /> Products
          <span className="badge teal">
            {overview ? overview.total_products.toLocaleString() : '...'}
          </span>
        </button>

        <button
          className={`subnav-btn ${activeTab === 'recent' ? 'active' : ''}`}
          onClick={() => setActiveTab('recent')}
        >
          <Clock size={15} /> Recent Scraped Data
        </button>

        <button
          className={`subnav-btn ${activeTab === 'runs' ? 'active' : ''}`}
          onClick={() => setActiveTab('runs')}
        >
          <Activity size={15} /> Extraction Runs
          <span className="badge blue">{runs.length}</span>
        </button>

        <button
          className={`subnav-btn ${activeTab === 'tables' ? 'active' : ''}`}
          onClick={() => setActiveTab('tables')}
        >
          <Table size={15} /> All Tables
          <span className="badge">{tables.length}</span>
        </button>
      </div>

      {/* Subview Content */}
      {activeTab === 'overview' && (
        <DatabaseOverviewView
          overview={overview}
          loading={loading}
          onSelectTab={setActiveTab}
          onExportAll={handleExportAllCsv}
          exporting={exportingAll}
          onDeleteTable={askDelete}
          deleting={deleting}
        />
      )}

      {activeTab === 'tables' && (
        <DatabaseTablesView
          tables={tables}
          initialTable="products"
          onDeleteTable={askDelete}
          deleting={deleting}
        />
      )}

      {activeTab === 'products' && (
        <ProductsManagementView
          sites={sites}
          runs={runs}
          initialRunId={targetRunFilter}
          onNotify={onNotify}
        />
      )}

      {activeTab === 'recent' && (
        <RecentScrapedDataView
          onNotify={onNotify}
          onFilterByRunInProducts={handleFilterByRunInProducts}
        />
      )}

      {activeTab === 'runs' && (
        <ExtractionRunsView
          runs={runs}
          loading={loading}
          onRefresh={() => void loadData()}
          onViewRun={handleFilterByRunInProducts}
          onNotify={onNotify}
        />
      )}
    </div>
  );
}
