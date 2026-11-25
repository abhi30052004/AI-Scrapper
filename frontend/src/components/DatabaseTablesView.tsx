import React, { useEffect, useState } from 'react';
import { Table, RefreshCw, ChevronLeft, ChevronRight, Hash, Key, Trash2 } from 'lucide-react';
import { request, type TableMetadata, type TableDataResponse } from '../api';

interface Props {
  tables: TableMetadata[];
  initialTable?: string;
  onDeleteTable?: (target: 'all' | string) => void;
  deleting?: boolean;
}

export function DatabaseTablesView({ tables, initialTable, onDeleteTable, deleting }: Props) {
  const [selectedTable, setSelectedTable] = useState<string>(initialTable || (tables[0]?.name || 'products'));
  const [tableData, setTableData] = useState<TableDataResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [limit] = useState(20);
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  async function loadTable(tableName: string, pageNum: number, sortCol?: string | null, order?: 'asc' | 'desc') {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        page: String(pageNum),
        limit: String(limit),
        sort_order: order || sortOrder,
      });
      if (sortCol) params.append('sort_by', sortCol);

      const res = await request<TableDataResponse>(`/api/database/tables/${tableName}?${params.toString()}`);
      setTableData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load table records');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (selectedTable) {
      void loadTable(selectedTable, page, sortBy, sortOrder);
    }
  }, [selectedTable, page, sortBy, sortOrder]);

  function handleSelectTable(tableName: string) {
    setSelectedTable(tableName);
    setPage(1);
    setSortBy(null);
  }

  function handleSort(columnName: string) {
    if (sortBy === columnName) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(columnName);
      setSortOrder('desc');
    }
  }

  const currentMeta = tables.find(t => t.name === selectedTable);

  return (
    <div className="tables-layout">
      {/* Sidebar with existing tables */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div className="section-head" style={{ marginBottom: '6px' }}>
          <div>
            <h2 style={{ fontSize: '14px' }}>Schema Tables</h2>
            <p style={{ fontSize: '10px' }}>Select table to inspect</p>
          </div>
        </div>

        {tables.map(t => (
          <button
            key={t.name}
            className={`table-pill ${selectedTable === t.name ? 'active' : ''}`}
            onClick={() => handleSelectTable(t.name)}
          >
            <Table size={14} />
            <span style={{ flex: 1, textAlign: 'left', wordBreak: 'break-all' }}>{t.name}</span>
            <span className="badge" style={{ fontSize: '9px' }}>{t.row_count}</span>
          </button>
        ))}
      </div>

      {/* Main Table Viewer */}
      <div style={{ minWidth: 0 }}>
        <div className="section-head">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h2>{selectedTable}</h2>
              {currentMeta && (
                <span className="badge teal">{currentMeta.row_count.toLocaleString()} total rows</span>
              )}
            </div>
            <p>Direct inspection of SQLite records with column schemas</p>
          </div>

          <div className="table-tools" style={{ display: 'flex', gap: '8px' }}>
            <button
              className="secondary"
              onClick={() => void loadTable(selectedTable, page, sortBy, sortOrder)}
              disabled={loading}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
            {onDeleteTable && (
              <button
                onClick={() => onDeleteTable(selectedTable)}
                disabled={deleting || (currentMeta?.row_count ?? 0) === 0}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '0 12px',
                  height: '34px',
                  borderRadius: '6px',
                  background: '#fef2f2',
                  color: (currentMeta?.row_count ?? 0) === 0 ? '#94a3b8' : '#dc2626',
                  border: '1px solid #fecaca',
                  fontWeight: 600,
                  fontSize: '12px',
                  cursor: (currentMeta?.row_count ?? 0) === 0 ? 'not-allowed' : 'pointer',
                }}
                title={`Delete all rows in '${selectedTable}'`}
              >
                <Trash2 size={13} /> Clear Table
              </button>
            )}
          </div>
        </div>

        {/* Columns summary banner */}
        {tableData && tableData.columns.length > 0 && (
          <div style={{
            background: '#ffffff',
            border: '1px solid #e8edf3',
            borderRadius: '8px',
            padding: '10px 14px',
            marginBottom: '14px',
            fontSize: '11px',
            color: '#6c7d93',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '8px',
            alignItems: 'center'
          }}>
            <span style={{ fontWeight: 700, color: '#334458' }}>Schema ({tableData.columns.length} columns):</span>
            {tableData.columns.map(c => (
              <span key={c.name} className="badge" style={{ background: '#f0f4f9', fontSize: '10px', gap: '4px' }}>
                {c.primary_key && <Key size={10} color="#188b8d" />}
                <strong>{c.name}</strong>
                <span style={{ color: '#8d9baa' }}>({c.type})</span>
              </span>
            ))}
          </div>
        )}

        {error && <div className="alert"><b>Error loading table:</b> {error}</div>}

        {/* Data Table */}
        <div className="table-card" style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                {tableData?.columns.map(col => (
                  <th
                    key={col.name}
                    onClick={() => handleSort(col.name)}
                    style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
                    title={`Click to sort by ${col.name}`}
                  >
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      {col.primary_key && <Hash size={11} color="#137f83" />}
                      {col.name.toUpperCase()}
                      {sortBy === col.name && (
                        <span style={{ color: '#137f83' }}>{sortOrder === 'asc' ? '▲' : '▼'}</span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && !tableData && (
                <tr>
                  <td colSpan={10} style={{ textAlign: 'center', padding: '36px' }}>
                    <RefreshCw className="animate-spin" size={20} style={{ margin: '0 auto 8px' }} />
                    <p style={{ margin: 0 }}>Reading records from SQLite...</p>
                  </td>
                </tr>
              )}

              {tableData && tableData.records.length > 0 ? (
                tableData.records.map((row, idx) => (
                  <tr key={idx}>
                    {tableData.columns.map(col => {
                      const val = row[col.name];
                      const valStr = val === null || val === undefined ? '—' : typeof val === 'object' ? JSON.stringify(val) : String(val);
                      return (
                        <td key={col.name} style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          <span title={valStr}>{valStr}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))
              ) : (
                !loading && (
                  <tr>
                    <td colSpan={tableData?.columns.length || 5}>
                      <div className="empty" style={{ padding: '32px' }}>
                        <b>No records found</b>
                        <p style={{ margin: '4px 0 0' }}>Table '{selectedTable}' is currently empty.</p>
                      </div>
                    </td>
                  </tr>
                )
              )}
            </tbody>
          </table>

          {/* Pagination */}
          {tableData && tableData.total_records > 0 && (
            <div className="pagination-bar">
              <div>
                Showing <b>{((tableData.page - 1) * tableData.limit) + 1}</b> to{' '}
                <b>{Math.min(tableData.page * tableData.limit, tableData.total_records)}</b> of{' '}
                <b>{tableData.total_records.toLocaleString()}</b> records
              </div>

              <div className="pagination-actions">
                <button
                  className="page-btn"
                  disabled={tableData.page <= 1 || loading}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                >
                  <ChevronLeft size={14} /> Prev
                </button>
                <span>Page {tableData.page} of {tableData.total_pages}</span>
                <button
                  className="page-btn"
                  disabled={tableData.page >= tableData.total_pages || loading}
                  onClick={() => setPage(p => Math.min(tableData.total_pages, p + 1))}
                >
                  Next <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
