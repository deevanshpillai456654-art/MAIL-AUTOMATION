class OfflineManager {
  constructor() {
    this.isOnline = navigator.onLine;
    this.listeners = new Map();
    this.statusListeners = new Map();
    this.syncStatus = 'idle';
    this.lastOnline = null;
    this.lastOffline = null;
    
    this._init();
  }

  _init() {
    window.addEventListener('online', () => this._handleOnline());
    window.addEventListener('offline', () => this._handleOffline());
    
    if ('serviceWorker' in navigator) {
      this._registerServiceWorker();
    }
    
    if ('serviceWorker' in navigator && 'SyncManager' in window) {
      this._registerBackgroundSync();
    }
  }

  _handleOnline() {
    this.isOnline = true;
    this.lastOnline = Date.now();
    this._emit('online');
    this._emitStatus('reconnected');
  }

  _handleOffline() {
    this.isOnline = false;
    this.lastOffline = Date.now();
    this._emit('offline');
    this._emitStatus('offline');
  }

  _emit(event) {
    const handlers = this.listeners.get(event) || [];
    handlers.forEach(handler => handler({ status: event, timestamp: Date.now(), isOnline: this.isOnline }));
  }

  _emitStatus(status) {
    this.syncStatus = status;
    const payload = { status, timestamp: Date.now(), isOnline: this.isOnline };
    const handlers = [
      ...(this.statusListeners.get(status) || []),
      ...(this.statusListeners.get('change') || [])
    ];
    handlers.forEach(handler => handler(payload));
  }

  _registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(err => {
        console.warn('Service worker registration failed:', err);
      });
    }
  }

  async _registerBackgroundSync() {
    try {
      const registration = await navigator.serviceWorker.ready;
      if ('sync' in registration) {
        await registration.sync.register('email-sync');
      }
    } catch (err) {
      console.warn('Background sync registration failed:', err);
    }
  }

  on(event, handler) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(handler);
    
    return () => {
      const handlers = this.listeners.get(event);
      const index = handlers.indexOf(handler);
      if (index > -1) handlers.splice(index, 1);
    };
  }

  onStatusChange(handler) {
    const id = Date.now();
    if (!this.statusListeners.has('change')) {
      this.statusListeners.set('change', []);
    }
    this.statusListeners.get('change').push(handler);
    
    return () => {
      const handlers = this.statusListeners.get('change');
      const index = handlers.indexOf(handler);
      if (index > -1) handlers.splice(index, 1);
    };
  }

  getStatus() {
    return {
      isOnline: this.isOnline,
      syncStatus: this.syncStatus,
      lastOnline: this.lastOnline,
      lastOffline: this.lastOffline,
      timestamp: Date.now()
    };
  }

  setSyncStatus(status) {
    this.syncStatus = status;
    this._emitStatus(status);
  }

  supportsOffline() {
    return 'indexedDB' in window && navigator.onLine !== undefined;
  }

  supportsBackgroundSync() {
    return 'serviceWorker' in navigator && 'SyncManager' in window;
  }

  async checkConnectivity() {
    if (!navigator.onLine) return false;
    
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      
      const response = await fetch('/api/v1/health', {
        method: 'HEAD',
        signal: controller.signal,
        cache: 'no-store'
      });
      
      clearTimeout(timeout);
      return response.ok;
    } catch {
      return false;
    }
  }
}

window.OfflineManager = OfflineManager;
