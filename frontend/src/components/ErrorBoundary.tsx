import { Component, ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('PriceTruth UI uncaught render error:', error, errorInfo)
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '40px', maxWidth: '600px', margin: '40px auto', background: '#fff', borderRadius: '14px', border: '1px solid #fecaca', boxShadow: '0 4px 20px rgba(0,0,0,0.06)', fontFamily: 'sans-serif' }}>
          <h2 style={{ color: '#dc2626', marginTop: 0 }}>Something went wrong rendering this view</h2>
          <p style={{ color: '#4b5563', fontSize: '14px', lineHeight: 1.6 }}>
            {this.state.error?.message || 'An unexpected rendering error occurred.'}
          </p>
          <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
            <button
              style={{ background: '#17634c', color: '#fff', border: 'none', padding: '10px 18px', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
              onClick={() => {
                this.setState({ hasError: false, error: null })
                window.location.reload()
              }}
            >
              Reload Page
            </button>
            <button
              style={{ background: '#f3f4f6', color: '#374151', border: '1px solid #d1d5db', padding: '10px 18px', borderRadius: '8px', cursor: 'pointer' }}
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Dismiss
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
