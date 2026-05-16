const SNAPSHOT_STORE = 'snapshots';

class SnapshotStore {
  constructor(db) {
    this.db = db;
    this.currentVersion = 2;
  }

  async saveSnapshot(type, data) {
    const snapshot = {
      id: `${type}_${Date.now()}`,
      type,
      version: this.currentVersion,
      timestamp: Date.now(),
      compressed: typeof CompressionStream !== 'undefined',
      data: await this._compress(data)
    };
    
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(SNAPSHOT_STORE, 'readwrite');
      const request = tx.objectStore(SNAPSHOT_STORE).put(snapshot);
      
      request.onsuccess = () => resolve(snapshot);
      request.onerror = () => reject(request.error);
    });
  }

  async saveIncrementalSnapshot(type, baseSnapshotId, delta) {
    const snapshot = {
      id: `${type}_incremental_${Date.now()}`,
      type,
      version: this.currentVersion,
      timestamp: Date.now(),
      compressed: typeof CompressionStream !== 'undefined',
      baseSnapshotId,
      delta: await this._compress(delta),
      isIncremental: true
    };
    
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(SNAPSHOT_STORE, 'readwrite');
      const request = tx.objectStore(SNAPSHOT_STORE).put(snapshot);
      
      request.onsuccess = () => resolve(snapshot);
      request.onerror = () => reject(request.error);
    });
  }

  async getSnapshot(type) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(SNAPSHOT_STORE, 'readonly');
      const store = tx.objectStore(SNAPSHOT_STORE);
      const index = store.index('type');
      const request = index.getAll(type);
      
      request.onsuccess = () => {
        const snapshots = request.result.sort((a, b) => b.timestamp - a.timestamp);
        const latest = snapshots[0];
        
        if (!latest) {
          resolve(null);
          return;
        }
        
        this._decompress(latest).then(resolve);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async getSnapshotWithBase(type, snapshotId) {
    const incremental = await this._getSnapshotById(snapshotId);
    if (!incremental || !incremental.isIncremental) {
      return this._decompress(incremental);
    }
    
    const base = await this._getSnapshotById(incremental.baseSnapshotId);
    if (!base) {
      throw new Error('Base snapshot not found');
    }
    
    const baseData = await this._decompress(base);
    const delta = await this._decompress({ data: incremental.delta, compressed: incremental.compressed });
    
    return this._applyDelta(baseData, delta);
  }

  async _getSnapshotById(id) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(SNAPSHOT_STORE, 'readonly');
      const request = tx.objectStore(SNAPSHOT_STORE).get(id);
      
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async _compress(data) {
    const json = JSON.stringify(data);
    
    if (typeof TextEncoder !== 'undefined' && typeof CompressionStream !== 'undefined') {
      const encoded = new TextEncoder().encode(json);
      const cs = new CompressionStream('deflate');
      const writer = cs.writable.getWriter();
      await writer.write(encoded);
      await writer.close();
      const reader = cs.readable.getReader();
      
      const chunks = [];
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
      }
      
      const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
      const result = new Uint8Array(totalLength);
      let offset = 0;
      for (const chunk of chunks) {
        result.set(chunk, offset);
        offset += chunk.length;
      }
      
      return Array.from(result);
    }
    
    return json;
  }

  async _decompress(snapshot) {
    if (!snapshot.compressed) {
      return typeof snapshot.data === 'string' ? JSON.parse(snapshot.data) : snapshot.data;
    }
    
    if (typeof TextDecoder !== 'undefined' && typeof DecompressionStream !== 'undefined' && Array.isArray(snapshot.data)) {
      const bytes = new Uint8Array(snapshot.data);
      const cs = new DecompressionStream('deflate');
      const writer = cs.writable.getWriter();
      await writer.write(bytes);
      await writer.close();
      const reader = cs.readable.getReader();
      
      const chunks = [];
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
      }
      
      const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
      const result = new Uint8Array(totalLength);
      let offset = 0;
      for (const chunk of chunks) {
        result.set(chunk, offset);
        offset += chunk.length;
      }
      
      return JSON.parse(new TextDecoder().decode(result));
    }
    
    return snapshot.data;
  }

  _applyDelta(base, delta) {
    if (delta.added) {
      for (const [key, value] of Object.entries(delta.added)) {
        base[key] = value;
      }
    }
    
    if (delta.modified) {
      for (const [key, value] of Object.entries(delta.modified)) {
        if (base[key] !== undefined) {
          base[key] = value;
        }
      }
    }
    
    if (delta.removed) {
      for (const key of delta.removed) {
        delete base[key];
      }
    }
    
    return base;
  }

  async encryptSnapshot(snapshot, key) {
    if (!key) return snapshot;
    
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM' },
      key,
      new TextEncoder().encode(JSON.stringify(snapshot.data))
    );
    
    return {
      ...snapshot,
      data: Array.from(new Uint8Array(encrypted)),
      encrypted: true
    };
  }

  async decryptSnapshot(snapshot, key) {
    if (!key || !snapshot.encrypted) return snapshot;
    
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM' },
      key,
      new Uint8Array(snapshot.data)
    );
    
    return {
      ...snapshot,
      data: JSON.parse(new TextDecoder().decode(decrypted)),
      encrypted: false
    };
  }

  async restoreSnapshot(type, snapshotId) {
    const snapshot = await this.getSnapshotWithBase(type, snapshotId);
    return snapshot;
  }

  async listSnapshots(type) {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(SNAPSHOT_STORE, 'readonly');
      const store = tx.objectStore(SNAPSHOT_STORE);
      const index = store.index('type');
      const request = index.getAll(type);
      
      request.onsuccess = () => {
        const snapshots = request.result
          .sort((a, b) => b.timestamp - a.timestamp)
          .map(s => ({
            id: s.id,
            timestamp: s.timestamp,
            version: s.version,
            isIncremental: s.isIncremental || false
          }));
        
        resolve(snapshots);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async deleteOldSnapshots(type, keepCount = 5) {
    const snapshots = await this.listSnapshots(type);
    
    if (snapshots.length <= keepCount) return 0;
    
    const toDelete = snapshots.slice(keepCount);
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(SNAPSHOT_STORE, 'readwrite');
      const store = tx.objectStore(SNAPSHOT_STORE);
      let deleted = 0;
      
      toDelete.forEach(s => {
        const request = store.delete(s.id);
        request.onsuccess = () => deleted++;
      });
      
      tx.oncomplete = () => resolve(deleted);
      tx.onerror = () => reject(tx.error);
    });
  }
}

window.SnapshotStore = SnapshotStore;
