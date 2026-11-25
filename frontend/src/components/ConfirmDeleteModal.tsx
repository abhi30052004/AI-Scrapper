import React, { useState } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';

interface Props {
  isOpen: boolean;
  title: string;
  description: string;
  confirmText: string;        // typed confirmation word
  onConfirm: () => void;
  onCancel: () => void;
  dangerous?: boolean;
}

/** Modal that requires the user to type a confirmation word before the action fires. */
export function ConfirmDeleteModal({
  isOpen,
  title,
  description,
  confirmText,
  onConfirm,
  onCancel,
  dangerous = true,
}: Props) {
  const [typed, setTyped] = useState('');

  if (!isOpen) return null;

  const matches = typed.trim().toLowerCase() === confirmText.toLowerCase();

  function handleConfirm() {
    if (!matches) return;
    setTyped('');
    onConfirm();
  }

  function handleCancel() {
    setTyped('');
    onCancel();
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(10,20,35,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        backdropFilter: 'blur(2px)',
      }}
      onClick={handleCancel}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: '14px',
          padding: '28px 30px',
          maxWidth: '440px',
          width: '90%',
          boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
          position: 'relative',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Close */}
        <button
          onClick={handleCancel}
          style={{ position: 'absolute', top: '14px', right: '14px', background: 'none', border: 'none', cursor: 'pointer', color: '#8595aa', padding: '4px' }}
        >
          <X size={18} />
        </button>

        {/* Icon + Title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '14px' }}>
          <div style={{
            width: '42px', height: '42px', borderRadius: '10px',
            background: dangerous ? '#fef2f2' : '#fff7ed',
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <AlertTriangle size={22} color={dangerous ? '#dc2626' : '#d97706'} />
          </div>
          <div>
            <strong style={{ fontSize: '15px', color: '#17263a', display: 'block' }}>{title}</strong>
            <small style={{ color: '#8595aa', fontSize: '11px' }}>This action cannot be undone</small>
          </div>
        </div>

        {/* Description */}
        <p style={{ fontSize: '12px', color: '#475569', lineHeight: 1.6, marginBottom: '18px' }}>
          {description}
        </p>

        {/* Confirm input */}
        <div style={{ marginBottom: '18px' }}>
          <label style={{ fontSize: '11px', fontWeight: 700, color: '#334458', display: 'block', marginBottom: '6px' }}>
            Type <code style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: '4px', color: '#dc2626' }}>{confirmText}</code> to confirm:
          </label>
          <input
            autoFocus
            type="text"
            value={typed}
            onChange={e => setTyped(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleConfirm(); }}
            placeholder={confirmText}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '9px 12px',
              border: `1.5px solid ${matches ? '#16a34a' : '#e2e8f0'}`,
              borderRadius: '8px',
              fontSize: '13px',
              outline: 'none',
              transition: 'border-color 0.15s',
              color: '#17263a',
            }}
          />
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            onClick={handleCancel}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: '1px solid #e2e8f0',
              background: '#f8fafc',
              color: '#475569',
              fontSize: '12px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!matches}
            style={{
              padding: '8px 18px',
              borderRadius: '8px',
              border: 'none',
              background: matches ? (dangerous ? '#dc2626' : '#d97706') : '#e2e8f0',
              color: matches ? '#fff' : '#94a3b8',
              fontSize: '12px',
              cursor: matches ? 'pointer' : 'not-allowed',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'background 0.15s',
            }}
          >
            <Trash2 size={13} /> Delete
          </button>
        </div>
      </div>
    </div>
  );
}
