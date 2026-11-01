import React, { useState } from 'react'
import { supabase, setAccessToken } from '../lib/supabaseClient'

interface AuthModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (user: any) => void
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [tab, setTab] = useState<'signin' | 'signup'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successNotice, setSuccessNotice] = useState<string | null>(null)

  if (!isOpen) return null

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setErrorMessage(null)
    setSuccessNotice(null)

    try {
      if (tab === 'signup') {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              full_name: fullName,
              name: fullName,
            },
          },
        })
        if (error) throw error

        if (data.session) {
          setAccessToken(data.session.access_token)
          onSuccess(data.user)
          onClose()
        } else if (data.user) {
          setSuccessNotice('Account registered! If confirmation is required, please check your inbox, or sign in.')
          setTab('signin')
        }
      } else {
        const { data, error } = await supabase.auth.signInWithPassword({
          email,
          password,
        })
        if (error) throw error

        if (data.session) {
          setAccessToken(data.session.access_token)
          onSuccess(data.user)
          onClose()
        }
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Authentication error. Please check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(15, 23, 42, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: '16px',
    }}>
      <div
        className="auth-modal"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#ffffff',
          borderRadius: '16px',
          width: '100%',
          maxWidth: '440px',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
          overflow: 'hidden',
          border: '1px solid #e2e8f0',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '24px 24px 16px',
          borderBottom: '1px solid #f1f5f9',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>
              {tab === 'signin' ? 'Sign In to PriceTruth' : 'Create Free Account'}
            </h3>
            <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: '#64748b' }}>
              {tab === 'signin' ? 'Manage your alerts, tracked products & price drops' : 'Track prices across 7 platforms with custom alerts'}
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '1.5rem',
              color: '#94a3b8',
              cursor: 'pointer',
              lineHeight: 1,
              padding: '4px',
            }}
          >
            ×
          </button>
        </div>

        {/* Tab switch */}
        <div style={{ display: 'flex', borderBottom: '1px solid #f1f5f9' }}>
          <button
            onClick={() => { setTab('signin'); setErrorMessage(null); }}
            style={{
              flex: 1,
              padding: '12px',
              border: 'none',
              background: tab === 'signin' ? '#ffffff' : '#f8fafc',
              fontWeight: tab === 'signin' ? 600 : 500,
              color: tab === 'signin' ? '#2563eb' : '#64748b',
              borderBottom: tab === 'signin' ? '2px solid #2563eb' : 'none',
              cursor: 'pointer',
            }}
          >
            Sign In
          </button>
          <button
            onClick={() => { setTab('signup'); setErrorMessage(null); }}
            style={{
              flex: 1,
              padding: '12px',
              border: 'none',
              background: tab === 'signup' ? '#ffffff' : '#f8fafc',
              fontWeight: tab === 'signup' ? 600 : 500,
              color: tab === 'signup' ? '#2563eb' : '#64748b',
              borderBottom: tab === 'signup' ? '2px solid #2563eb' : 'none',
              cursor: 'pointer',
            }}
          >
            Create Account
          </button>
        </div>

        {/* Body form */}
        <form onSubmit={handleAuth} style={{ padding: '24px' }}>
          {errorMessage && (
            <div style={{
              background: '#fef2f2',
              border: '1px solid #fecaca',
              color: '#dc2626',
              borderRadius: '8px',
              padding: '10px 12px',
              fontSize: '0.85rem',
              marginBottom: '16px',
            }}>
              {errorMessage}
            </div>
          )}

          {successNotice && (
            <div style={{
              background: '#f0fdf4',
              border: '1px solid #bbf7d0',
              color: '#16a34a',
              borderRadius: '8px',
              padding: '10px 12px',
              fontSize: '0.85rem',
              marginBottom: '16px',
            }}>
              {successNotice}
            </div>
          )}

          {tab === 'signup' && (
            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                Full Name
              </label>
              <input
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="e.g. Rahul Sharma"
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.95rem',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          )}

          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: '8px',
                border: '1px solid #cbd5e1',
                fontSize: '0.95rem',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              minLength={6}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: '8px',
                border: '1px solid #cbd5e1',
                fontSize: '0.95rem',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: '#2563eb',
              color: '#ffffff',
              fontWeight: 600,
              fontSize: '0.95rem',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
              transition: 'background-color 0.2s',
            }}
          >
            {loading ? 'Please wait...' : tab === 'signin' ? 'Sign In' : 'Sign Up'}
          </button>

          <p style={{ margin: '16px 0 0', fontSize: '0.75rem', color: '#94a3b8', textAlign: 'center' }}>
            Powered by Supabase Auth with isolated user data stored in your local database.
          </p>
        </form>
      </div>
    </div>
  )
}
