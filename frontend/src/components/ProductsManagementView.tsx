import React, { useEffect, useState } from 'react';
import { Package, Search, Download, RefreshCw, ChevronLeft, ChevronRight, Globe2, Hash, ArrowUpDown, ExternalLink, Info } from 'lucide-react';
import { request, downloadCsv, type Product, type ProductsResponse, type Site, type ExtractionRun } from '../api';
import { ProductDetailModal } from './ProductDetailModal';

interface Props {
  sites: Site[];
  runs: ExtractionRun[];
  initialRunId?: number | null;
  onNotify: (msg: string, type: 'success' | 'error') => void;
}

export function ProductsManagementView({ sites, runs, initialRunId, onNotify }: Props) {
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [limit] = useState(20);
  const [search, setSearch] = useState('');
  const [siteFilter, setSiteFilter] = useState<string>('all');
  const [runFilter, setRunFilter] = useState<string>(initialRunId ? String(initialRunId) : 'all');
  const [sortBy, setSortBy] = useState<string>('id');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

  async function loadProducts() {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(limit),
        sort_by: sortBy,
        sort_order: sortOrder,
      });

      if (search.trim()) params.append('search', search.trim());
      if (siteFilter !== 'all') params.append('site_id', siteFilter);
      if (runFilter !== 'all') params.append('run_id', runFilter);

      const res = await request<ProductsResponse>(`/api/products?${params.toString()}`);
      setProducts(res.products);
      setTotal(res.total);
      setTotalPages(res.total_pages);
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Failed to load products', 'error');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadProducts();
  }, [page, sortBy, sortOrder, siteFilter, runFilter]);

  // Handle Search submit
  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    void loadProducts();
  }

  function handleSort(column: string) {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortOrder('desc');
    }
  }

  async function handleExportCsv() {
    setExporting(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.append('search', search.trim());
      if (siteFilter !== 'all') params.append('site_id', siteFilter);
      if (runFilter !== 'all') params.append('run_id', runFilter);

      const queryStr = params.toString() ? `?${params.toString()}` : '';
      const filename = await downloadCsv(`/api/products/export${queryStr}`, 'products_export.csv');
      onNotify(`Downloaded ${filename} successfully!`, 'success');
    } catch (e) {
      onNotify(e instanceof Error ? e.message : 'Export failed', 'error');
    } finally {
      setExporting(false);
    }
  }

  return (
    <div>
      <div className="section-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2>Products Management</h2>
            <span className="badge teal">{total.toLocaleString()} total stored</span>
          </div>
          <p>Real product records extracted and saved in local SQLite storage</p>
        </div>

        <div className="table-tools">
          <button className="primary" onClick={handleExportCsv} disabled={exporting}>
            <Download size={15} /> {exporting ? 'Generating...' : 'Export Filtered CSV'}
          </button>
          <button className="secondary" onClick={() => void loadProducts()} disabled={loading}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="filter-bar">
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: '8px', flex: 1, minWidth: '220px' }}>
          <div className="search" style={{ flex: 1 }}>
            <Search size={16} />
            <input
              placeholder="Search product title, URL, or website..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>
          <button type="submit" className="secondary" style={{ padding: '0 12px', height: '34px' }}>
            Search
          </button>
        </form>

        {/* Website Filter */}
        <select
          className="filter-select"
          value={siteFilter}
          onChange={e => {
            setSiteFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="all">All Websites ({sites.length})</option>
          {sites.map(s => (
            <option key={s.id} value={String(s.id)}>
              {s.name}
            </option>
          ))}
        </select>

        {/* Run Filter */}
        <select
          className="filter-select"
          value={runFilter}
          onChange={e => {
            setRunFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="all">All Extraction Runs ({runs.length})</option>
          {runs.map(r => (
            <option key={r.id} value={String(r.id)}>
              Run #{r.id} ({r.record_count} items)
            </option>
          ))}
        </select>

        {(search || siteFilter !== 'all' || runFilter !== 'all') && (
          <button
            type="button"
            className="secondary"
            style={{ padding: '0 10px', height: '34px', fontSize: '11px' }}
            onClick={() => {
              setSearch('');
              setSiteFilter('all');
              setRunFilter('all');
              setPage(1);
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Products Table Card */}
      <div className="table-card" style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th onClick={() => handleSort('id')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  ID <ArrowUpDown size={11} />
                </div>
              </th>
              <th onClick={() => handleSort('title')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  PRODUCT TITLE <ArrowUpDown size={11} />
                </div>
              </th>
              <th onClick={() => handleSort('price')} style={{ cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  PRICE <ArrowUpDown size={11} />
                </div>
              </th>
              <th>RATING</th>
              <th>AVAILABILITY</th>
              <th>WEBSITE</th>
              <th>RUN ID</th>
              <th>SCRAPED</th>
              <th style={{ textAlign: 'right' }}>ACTION</th>
            </tr>
          </thead>
          <tbody>
            {loading && products.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', padding: '36px' }}>
                  <RefreshCw className="animate-spin" size={20} style={{ margin: '0 auto 8px' }} />
                  <p style={{ margin: 0 }}>Loading products from SQLite...</p>
                </td>
              </tr>
            ) : products.length > 0 ? (
              products.map(p => (
                <tr
                  key={p.id}
                  className="table-row-clickable"
                  onClick={() => setSelectedProduct(p)}
                >
                  <td>
                    <span className="badge" style={{ fontFamily: 'monospace' }}>#{p.id}</span>
                  </td>
                  <td style={{ maxWidth: '320px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div className="stat-icon" style={{ width: '28px', height: '28px', flexShrink: 0 }}>
                        <Package size={14} />
                      </div>
                      <div style={{ overflow: 'hidden' }}>
                        <b style={{ color: '#17263a', fontSize: '12px', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.title || ''}>
                          {p.title || 'Untitled'}
                        </b>
                        {p.product_url && (
                          <small style={{ color: '#8d9caa', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {p.product_url}
                          </small>
                        )}
                      </div>
                    </div>
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
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <Globe2 size={12} color="#188b8d" />
                      <span style={{ fontSize: '11px', color: '#334458', fontWeight: 600 }}>
                        {p.site_name || '—'}
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className="badge blue" style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                      <Hash size={10} /> {p.run_id}
                    </span>
                  </td>
                  <td>
                    <small style={{ color: '#8898aa' }}>
                      {p.scraped_at ? new Date(p.scraped_at).toLocaleDateString() : '—'}
                    </small>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      className="secondary"
                      style={{ padding: '4px 8px', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                      onClick={e => {
                        e.stopPropagation();
                        setSelectedProduct(p);
                      }}
                    >
                      <Info size={12} /> View
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={9}>
                  <div className="empty">
                    <div className="empty-icon"><Package /></div>
                    <b>No products found</b>
                    <p>
                      {search || siteFilter !== 'all' || runFilter !== 'all'
                        ? 'No products matched your search or filters.'
                        : 'No products have been extracted yet. Run an extraction to populate data.'}
                    </p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {/* Pagination Bar */}
        {total > 0 && (
          <div className="pagination-bar">
            <div>
              Showing <b>{((page - 1) * limit) + 1}</b> to <b>{Math.min(page * limit, total)}</b> of{' '}
              <b>{total.toLocaleString()}</b> products
            </div>

            <div className="pagination-actions">
              <button
                className="page-btn"
                disabled={page <= 1 || loading}
                onClick={() => setPage(p => Math.max(1, p - 1))}
              >
                <ChevronLeft size={14} /> Prev
              </button>
              <span>Page {page} of {totalPages}</span>
              <button
                className="page-btn"
                disabled={page >= totalPages || loading}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              >
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Product Details Drawer/Modal */}
      <ProductDetailModal
        product={selectedProduct}
        onClose={() => setSelectedProduct(null)}
      />
    </div>
  );
}
