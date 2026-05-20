class CacheManager {
  constructor(idbCache) {
    this.idb = idbCache;
    this.memory = new Map();
    this.maxMemory = 100;
    this.warmingPromise = null;
    this.staleTime = 5 * 60 * 1000;
    this.backgroundUpdateInterval = null;
    this.stats = {
      hits: 0,
      misses: 0,
      updates: 0
    };
  }

  async warmCache(apiBase) {
    if (this.warmingPromise) return this.warmingPromise;
    
    this.warmingPromise = this._doWarming(apiBase);
    return this.warmingPromise;
  }

  async _doWarming(apiBase) {
    try {
      const [emailsRes, rulesRes] = await Promise.all([
        fetch(`${apiBase}/emails?limit=50`),
        fetch(`${apiBase}/rules`)
      ]);
      
      if (emailsRes.ok) {
        const data = await emailsRes.json();
        if (data.emails) {
          await this.idb.cacheEmails(data.emails);
        }
      }
      
      if (rulesRes.ok) {
        const data = await rulesRes.json();
        if (data.rules) {
          await this.idb.cacheRules(data.rules);
        }
      }
      
      return true;
    } catch (error) {
      return false;
    }
  }

  async getEmail(id) {
    const memKey = `email:${id}`;
    
    if (this.memory.has(memKey)) {
      this.stats.hits++;
      return this.memory.get(memKey);
    }
    
    const cached = await this.idb.getEmail(id);
    if (cached) {
      this.stats.hits++;
      this._addToMemory(memKey, cached);
      return cached;
    }
    
    this.stats.misses++;
    return null;
  }

  async getEmailsByCategory(category) {
    const cached = await this.idb.getEmailsByCategory(category);
    if (cached && cached.length > 0) {
      this.stats.hits++;
      return cached;
    }
    
    this.stats.misses++;
    return [];
  }

  async getEmailsByAccount(accountId) {
    return this.idb.getEmailsByAccount(accountId);
  }

  async staleWhileRevalidate(key, fetcher, apiFetcher) {
    const memKey = `email:${key}`;
    const cached = this.memory.get(memKey) || (await this.idb.getEmail(key));
    
    if (cached) {
      this._revalidateInBackground(key, fetcher, apiFetcher);
      return cached;
    }
    
    if (apiFetcher) {
      return apiFetcher(key);
    }
    
    return null;
  }

  async _revalidateInBackground(key, idbFetcher, apiFetcher) {
    if (!apiFetcher) return;
    
    try {
      const fresh = await apiFetcher(key);
      if (fresh) {
        await idbFetcher(fresh);
        this.stats.updates++;
      }
    } catch (error) {}
  }

  _addToMemory(key, value) {
    if (this.memory.size >= this.maxMemory) {
      const firstKey = this.memory.keys().next().value;
      this.memory.delete(firstKey);
    }
    this.memory.set(key, value);
  }

  async invalidate(pattern) {
    const tx = this.idb.db.transaction('emails', 'readwrite');
    const store = tx.objectStore('emails');
    
    return new Promise((resolve, reject) => {
      const request = store.openCursor();
      let count = 0;
      
      request.onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          if (pattern.test(cursor.value.id)) {
            cursor.delete();
            count++;
          }
          cursor.continue();
        } else {
          this.memory.clear();
          resolve(count);
        }
      };
      request.onerror = () => reject(request.error);
    });
  }

  async invalidateAll() {
    await this.idb.clearEmailCache();
    this.memory.clear();
  }

  startBackgroundUpdates(apiBase, interval = 60000) {
    if (this.backgroundUpdateInterval) {
      clearInterval(this.backgroundUpdateInterval);
    }
    
    this.backgroundUpdateInterval = setInterval(async () => {
      if (navigator.onLine) {
        await this._doWarming(apiBase);
      }
    }, interval);
  }

  stopBackgroundUpdates() {
    if (this.backgroundUpdateInterval) {
      clearInterval(this.backgroundUpdateInterval);
      this.backgroundUpdateInterval = null;
    }
  }

  getStats() {
    const total = this.stats.hits + this.stats.misses;
    return {
      ...this.stats,
      hitRate: total > 0 ? (this.stats.hits / total * 100).toFixed(1) + '%' : '0%',
      memoryItems: this.memory.size
    };
  }
}

window.CacheManager = CacheManager;
