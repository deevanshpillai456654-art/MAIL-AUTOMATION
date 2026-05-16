const DB_NAME = 'AIEmailOrganizer';
const DB_VERSION = 1;
const STORES = {
  emails: 'emails',
  attachments: 'attachments',
  rules: 'rules',
  operations: 'operations',
  snapshots: 'snapshots'
};

class IndexedDBCache {
  constructor() {
    this.db = null;
    this.ready = this._init();
  }

  async _init() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      
      request.onerror = () => reject(request.error);
      
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        
        if (!db.objectStoreNames.contains(STORES.emails)) {
          const emailStore = db.createObjectStore(STORES.emails, { keyPath: 'id' });
          emailStore.createIndex('accountId', 'accountId', { unique: false });
          emailStore.createIndex('timestamp', 'timestamp', { unique: false });
          emailStore.createIndex('category', 'category', { unique: false });
          emailStore.createIndex('lastAccess', 'lastAccess', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.attachments)) {
          const attachStore = db.createObjectStore(STORES.attachments, { keyPath: 'id' });
          attachStore.createIndex('emailId', 'emailId', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.rules)) {
          const ruleStore = db.createObjectStore(STORES.rules, { keyPath: 'id' });
          ruleStore.createIndex('name', 'name', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.operations)) {
          const opStore = db.createObjectStore(STORES.operations, { keyPath: 'opId', autoIncrement: true });
          opStore.createIndex('timestamp', 'timestamp', { unique: false });
          opStore.createIndex('status', 'status', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.snapshots)) {
          const snapStore = db.createObjectStore(STORES.snapshots, { keyPath: 'id' });
          snapStore.createIndex('type', 'type', { unique: false });
          snapStore.createIndex('timestamp', 'timestamp', { unique: false });
        }
      };
      
      request.onsuccess = () => {
        this.db = request.result;
        resolve(this.db);
      };
    });
  }

  async ensureReady() {
    if (!this.db) {
      await this.ready;
    }
  }

  async _wrapRequest(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async cacheEmail(email) {
    await this.ensureReady();
    const entry = {
      ...email,
      lastAccess: Date.now(),
      cachedAt: Date.now()
    };
    return this._wrapRequest(this.db.transaction(STORES.emails, 'readwrite').objectStore(STORES.emails).put(entry));
  }

  async cacheEmails(emails) {
    await this.ensureReady();
    const tx = this.db.transaction(STORES.emails, 'readwrite');
    const store = tx.objectStore(STORES.emails);
    
    for (const email of emails) {
      store.put({
        ...email,
        lastAccess: Date.now(),
        cachedAt: Date.now()
      });
    }
    
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve(emails.length);
      tx.onerror = () => reject(tx.error);
    });
  }

  async getEmail(id) {
    await this.ensureReady();
    const store = this.db.transaction(STORES.emails, 'readonly').objectStore(STORES.emails);
    const email = await this._wrapRequest(store.get(id));
    
    if (email) {
      email.lastAccess = Date.now();
      this.db.transaction(STORES.emails, 'readwrite').objectStore(STORES.emails).put(email);
    }
    
    return email;
  }

  async getEmailsByAccount(accountId) {
    await this.ensureReady();
    const store = this.db.transaction(STORES.emails, 'readonly').objectStore(STORES.emails);
    const index = store.index('accountId');
    
    return new Promise((resolve, reject) => {
      const results = [];
      const request = index.getAll(accountId);
      
      request.onsuccess = () => {
        const emails = request.result.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        resolve(emails);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async getEmailsByCategory(category) {
    await this.ensureReady();
    const store = this.db.transaction(STORES.emails, 'readonly').objectStore(STORES.emails);
    const index = store.index('category');
    
    return new Promise((resolve, reject) => {
      const request = index.getAll(category);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async cacheAttachment(attachment) {
    await this.ensureReady();
    return this._wrapRequest(
      this.db.transaction(STORES.attachments, 'readwrite').objectStore(STORES.attachments).put(attachment)
    );
  }

  async getAttachment(id) {
    await this.ensureReady();
    return this._wrapRequest(
      this.db.transaction(STORES.attachments, 'readonly').objectStore(STORES.attachments).get(id)
    );
  }

  async cacheRules(rules) {
    await this.ensureReady();
    const tx = this.db.transaction(STORES.rules, 'readwrite');
    const store = tx.objectStore(STORES.rules);
    
    store.clear();
    for (const rule of rules) {
      store.put(rule);
    }
    
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve(rules.length);
      tx.onerror = () => reject(tx.error);
    });
  }

  async getRules() {
    await this.ensureReady();
    return this._wrapRequest(
      this.db.transaction(STORES.rules, 'readonly').objectStore(STORES.rules).getAll()
    );
  }

  async evictLRU(maxSize = 500, maxAgeMs = 7 * 24 * 60 * 60 * 1000) {
    await this.ensureReady();
    const store = this.db.transaction(STORES.emails, 'readwrite').objectStore(STORES.emails);
    const index = store.index('lastAccess');
    
    return new Promise((resolve, reject) => {
      let count = 0;
      const now = Date.now();
      
      const request = index.openCursor(null, 'next');
      request.onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          const email = cursor.value;
          if (email.lastAccess < now - maxAgeMs || count >= maxSize) {
            cursor.delete();
            count++;
          }
          cursor.continue();
        } else {
          resolve(count);
        }
      };
      request.onerror = () => reject(request.error);
    });
  }

  async clearEmailCache() {
    await this.ensureReady();
    return this._wrapRequest(
      this.db.transaction(STORES.emails, 'readwrite').objectStore(STORES.emails).clear()
    );
  }

  async getCacheStats() {
    await this.ensureReady();
    const store = this.db.transaction(STORES.emails, 'readonly').objectStore(STORES.emails);
    
    return new Promise((resolve, reject) => {
      const countReq = store.count();
      const allReq = store.getAll();
      
      let count = 0;
      let size = 0;
      
      countReq.onsuccess = () => { count = countReq.result; };
      allReq.onsuccess = () => {
        size = new Blob([JSON.stringify(allReq.result)]).size;
        resolve({ count, size, humanSize: this._formatBytes(size) });
      };
      allReq.onerror = () => reject(allReq.error);
    });
  }

  _formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  async encrypt(data, key) {
    if (!key) return data;
    const encoded = new TextEncoder().encode(JSON.stringify(data));
    const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['encrypt']);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, encoded);
    return { iv: Array.from(iv), data: Array.from(new Uint8Array(encrypted)) };
  }

  async decrypt(encrypted, key) {
    if (!key || !encrypted.data) return encrypted;
    const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['decrypt']);
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: new Uint8Array(encrypted.iv) },
      cryptoKey,
      new Uint8Array(encrypted.data)
    );
    return JSON.parse(new TextDecoder().decode(decrypted));
  }
}

window.IndexedDBCache = IndexedDBCache;
