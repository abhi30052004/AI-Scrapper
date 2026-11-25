import React from 'react';
import { X, ExternalLink, Package, Globe, Hash, Clock, FileCode } from 'lucide-react';
import type { Product } from '../api';

interface Props {
  product: Product | null;
  onClose: () => void;
}

export function ProductDetailModal({ product, onClose }: Props) {
  if (!product) return null;

  const rawData = product.raw_data || (product.raw_data_json ? JSON.parse(product.raw_data_json) : null);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="detail-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <div className="stat-icon" style={{ width: '38px', height: '38px' }}>
              <Package size={20} />
            </div>
            <div>
              <div className="eyebrow">PRODUCT RECORD · #{product.id}</div>
              <h2>{product.title || 'Untitled Product'}</h2>
              <p style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Globe size={13} /> {product.site_name || 'Unknown source'}
              </p>
            </div>
          </div>
          <button className="icon-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="detail-grid">
          <div className="detail-item">
            <span>Price</span>
            <strong style={{ color: '#137f83', fontSize: '15px' }}>
              {product.price || '—'}
            </strong>
          </div>

          <div className="detail-item">
            <span>Availability</span>
            <strong>
              <span className={`badge ${product.availability?.toLowerCase().includes('in stock') ? 'green' : 'amber'}`}>
                {product.availability || 'Unknown'}
              </span>
            </strong>
          </div>

          <div className="detail-item">
            <span>Rating</span>
            <strong>{product.rating || '—'}</strong>
          </div>

          <div className="detail-item">
            <span>Extraction Run</span>
            <strong>
              <span className="badge blue" style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                <Hash size={11} /> Run #{product.run_id}
              </span>
            </strong>
          </div>

          <div className="detail-item full">
            <span>Product URL</span>
            {product.product_url ? (
              <a href={product.product_url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                {product.product_url} <ExternalLink size={13} />
              </a>
            ) : (
              <strong>—</strong>
            )}
          </div>

          <div className="detail-item full">
            <span>Scraped At</span>
            <strong style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Clock size={13} color="#8595aa" />
              {product.scraped_at ? new Date(product.scraped_at).toLocaleString() : '—'}
            </strong>
          </div>
        </div>

        {rawData && (
          <details style={{ marginTop: '12px', borderTop: '1px solid #edf1f6', paddingTop: '12px' }}>
            <summary style={{ cursor: 'pointer', fontSize: '11px', fontWeight: 700, color: '#536276', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FileCode size={14} /> View Raw Extracted JSON
            </summary>
            <pre style={{
              background: '#f7f9fb',
              padding: '12px',
              borderRadius: '7px',
              fontSize: '11px',
              maxHeight: '200px',
              overflow: 'auto',
              color: '#334458',
              marginTop: '8px'
            }}>
              {JSON.stringify(rawData, null, 2)}
            </pre>
          </details>
        )}

        <div className="modal-actions" style={{ marginTop: '20px' }}>
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
          {product.product_url && (
            <a href={product.product_url} target="_blank" rel="noreferrer" className="primary" style={{ textDecoration: 'none' }}>
              Open Product Page ↗
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
