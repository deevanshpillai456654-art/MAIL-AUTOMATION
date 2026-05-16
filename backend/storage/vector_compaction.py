"""
Vector Compaction Engine & Recovery System

Features:
- Vector embedding compaction
- Clustering for similar vectors
- Dimensionality reduction option
- Storage budget management
- Query optimization
- Backup snapshots and corruption recovery
"""

import os
import json
import hashlib
import threading
import time
import logging
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

logger = logging.getLogger("storage.vector_compaction")


class CompactionMode(Enum):
    """Compaction strategies"""
    DEDUP = "dedup"
    CLUSTER = "cluster"
    REDUCE = "reduce"
    HYBRID = "hybrid"


@dataclass
class CompactionResult:
    """Result of compaction operation"""
    mode: CompactionMode
    original_count: int
    compacted_count: int
    removed_count: int
    saved_bytes: int
    duration_ms: float


@dataclass
class VectorCluster:
    """Cluster of similar vectors"""
    cluster_id: str
    centroid: Optional[any] = None
    vectors: List[str] = field(default_factory=list)
    representative: Optional[str] = None


@dataclass
class VectorSnapshot:
    """Backup snapshot of vector data"""
    snapshot_id: str
    created_at: float
    vector_count: int
    index_path: str
    metadata_path: str
    checksum: str
    size_bytes: int


@dataclass
class CorruptionReport:
    """Report of detected corruption"""
    snapshot_id: str
    detected_at: float
    corrupted_entries: List[str]
    severity: str
    recovery_action: str


@dataclass
class CompactionStats:
    """Compaction statistics"""
    total_compactions: int = 0
    vectors_removed: int = 0
    clusters_created: int = 0
    storage_saved_bytes: int = 0
    last_compaction_time: float = 0


class VectorCompactionEngine:
    """
    Vector embedding compaction and optimization.
    
    Features:
    - Deduplication of identical vectors
    - Clustering for similar vectors
    - Dimensionality reduction (PCA/SVD)
    - Storage budget management
    """
    
    def __init__(
        self,
        storage_root: str = "./data/storage/vectors",
        max_storage_gb: float = 10.0,
        compaction_threshold: float = 0.8,
        cluster_similarity_threshold: float = 0.95
    ):
        self.storage_root = Path(storage_root)
        self.max_storage_bytes = int(max_storage_gb * 1024 * 1024 * 1024)
        self.compaction_threshold = compaction_threshold
        self.cluster_similarity_threshold = cluster_similarity_threshold
        
        self._ensure_directories()
        
        self._vectors: Dict[str, any] = {}
        self._email_index: Dict[int, str] = {}
        self._clusters: Dict[str, VectorCluster] = {}
        
        self._np_available = False
        self._try_import_numpy()
        
        self._stats = CompactionStats()
        self._lock = threading.Lock()
        
        self._load_data()
        
        logger.info(f"Vector compaction engine initialized (max_storage={max_storage_gb}GB)")
    
    def _ensure_directories(self):
        """Create storage directories"""
        dirs = ["index", "metadata", "clusters", "temp"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)
    
    def _try_import_numpy(self):
        """Try to import numpy"""
        try:
            import numpy as np
            self._np = np
            self._np_available = True
            logger.info("NumPy available for vector operations")
        except ImportError:
            logger.warning("NumPy not available - using fallback")
    
    def _load_data(self):
        """Load existing vector data"""
        import json
        
        meta_file = self.storage_root / "metadata" / "vectors.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r") as f:
                    data = json.load(f)
                    self._vectors = data.get("vectors", {})
                    self._email_index = data.get("email_index", {})
                logger.info(f"Loaded {len(self._vectors)} vectors")
            except Exception as e:
                logger.error(f"Failed to load vectors: {e}")
    
    def _save_data(self):
        """Save vector data"""
        import json
        
        meta_file = self.storage_root / "metadata" / "vectors.json"
        
        try:
            data = {
                "vectors": self._vectors,
                "email_index": self._email_index,
                "updated_at": time.time()
            }
            
            with open(meta_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save vectors: {e}")
    
    def add_vector(
        self,
        email_id: int,
        vector_data: List[float],
        model: str = "default"
    ) -> str:
        """Add a vector"""
        with self._lock:
            if self._np_available:
                vector = self._np.array(vector_data)
            else:
                vector = vector_data
            
            vec_key = self._vector_key(vector)
            entry_id = f"vec_{hashlib.sha256(vec_key.encode()).hexdigest()[:16]}"
            
            self._vectors[entry_id] = {
                "email_id": email_id,
                "vector": vector_data if not self._np_available else vector.tolist(),
                "model": model,
                "created_at": time.time()
            }
            self._email_index[email_id] = entry_id
            
            if len(self._vectors) % 10 == 0:
                self._save_data()
            
            return entry_id
    
    def _vector_key(self, vector) -> str:
        """Generate key for vector"""
        if self._np_available:
            return hashlib.sha256(vector.tobytes()).hexdigest()
        else:
            return hashlib.sha256(str(vector).encode()).hexdigest()
    
    def compact(
        self,
        mode: CompactionMode = CompactionMode.DEDUP
    ) -> CompactionResult:
        """Compact vectors based on mode"""
        start_time = time.time()
        original_count = len(self._vectors)
        
        with self._lock:
            if mode == CompactionMode.DEDUP:
                removed = self._compact_deduplicate()
            elif mode == CompactionMode.CLUSTER:
                removed = self._compact_cluster()
            elif mode == CompactionMode.REDUCE:
                removed = self._compact_reduce()
            else:
                removed = self._compact_hybrid()
            
            compacted_count = len(self._vectors)
            saved_bytes = (original_count - compacted_count) * 384 * 4
            
            self._stats.total_compactions += 1
            self._stats.vectors_removed += removed
            self._stats.last_compaction_time = time.time()
            
            self._save_data()
        
        duration_ms = (time.time() - start_time) * 1000
        
        return CompactionResult(
            mode=mode,
            original_count=original_count,
            compacted_count=compacted_count,
            removed_count=removed,
            saved_bytes=saved_bytes,
            duration_ms=duration_ms
        )
    
    def _compact_deduplicate(self) -> int:
        """Remove duplicate vectors"""
        seen = {}
        to_remove = []
        
        for entry_id, data in self._vectors.items():
            vec_key = self._vector_key(self._np.array(data["vector"]) if self._np_available else data["vector"])
            
            if vec_key in seen:
                to_remove.append(entry_id)
            else:
                seen[vec_key] = entry_id
        
        for entry_id in to_remove:
            email_id = self._vectors[entry_id]["email_id"]
            del self._vectors[entry_id]
            if email_id in self._email_index:
                del self._email_index[email_id]
        
        logger.info(f"Deduplication: removed {len(to_remove)} duplicate vectors")
        return len(to_remove)
    
    def _compact_cluster(self) -> int:
        """Cluster similar vectors"""
        if not self._np_available:
            return 0
        
        vectors = []
        entry_ids = []
        
        for entry_id, data in self._vectors.items():
            vectors.append(self._np.array(data["vector"]))
            entry_ids.append(entry_id)
        
        if len(vectors) < 2:
            return 0
        
        vectors_array = self._np.vstack(vectors)
        
        from sklearn.cluster import KMeans
        
        n_clusters = max(1, len(vectors) // 10)
        
        try:
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            labels = kmeans.fit_predict(vectors_array)
            
            cluster_map = {}
            for i, entry_id in enumerate(entry_ids):
                label = int(labels[i])
                if label not in cluster_map:
                    cluster_map[label] = []
                cluster_map[label].append(entry_id)
            
            self._clusters = {
                f"cluster_{k}": VectorCluster(
                    cluster_id=f"cluster_{k}",
                    centroid=kmeans.cluster_centers_[k].tolist(),
                    vectors=vlist,
                    representative=vlist[0]
                )
                for k, vlist in cluster_map.items()
            }
            
            self._stats.clusters_created = len(self._clusters)
            
            self._save_clusters()
            
            logger.info(f"Created {len(self._clusters)} clusters")
            return 0
            
        except Exception as e:
            logger.error(f"Clustering failed: {e}")
            return 0
    
    def _compact_reduce(self) -> int:
        """Reduce vector dimensions"""
        if not self._np_available:
            return 0
        
        try:
            from sklearn.decomposition import PCA
            
            vectors = [self._np.array(data["vector"]) for data in self._vectors.values()]
            vectors_array = self._np.vstack(vectors)
            
            target_dim = min(128, vectors_array.shape[1])
            pca = PCA(n_components=target_dim)
            reduced = pca.fit_transform(vectors_array)
            
            for i, entry_id in enumerate(self._vectors.keys()):
                self._vectors[entry_id]["vector"] = reduced[i].tolist()
                self._vectors[entry_id]["reduced_dim"] = target_dim
            
            self._save_data()
            
            saved = vectors_array.shape[1] - target_dim
            logger.info(f"Reduced dimensions: {saved} bytes per vector")
            return 0
            
        except Exception as e:
            logger.error(f"Dimension reduction failed: {e}")
            return 0
    
    def _compact_hybrid(self) -> int:
        """Hybrid compaction (dedup + cluster)"""
        removed = self._compact_deduplicate()
        self._compact_cluster()
        return removed
    
    def get_storage_usage(self) -> Dict:
        """Get storage usage information"""
        vector_count = len(self._vectors)
        vector_size = vector_count * 384 * 4
        
        return {
            "vector_count": vector_count,
            "storage_bytes": vector_size,
            "max_storage_bytes": self.max_storage_bytes,
            "usage_percent": (vector_size / self.max_storage_bytes) * 100,
            "clusters": len(self._clusters)
        }
    
    def _save_clusters(self):
        """Save cluster data"""
        import json
        cluster_file = self.storage_root / "clusters" / "clusters.json"
        
        try:
            data = {
                "clusters": {
                    k: {
                        "cluster_id": v.cluster_id,
                        "centroid": v.centroid,
                        "vectors": v.vectors,
                        "representative": v.representative
                    }
                    for k, v in self._clusters.items()
                }
            }
            
            with open(cluster_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save clusters: {e}")
    
    def get_stats(self) -> CompactionStats:
        """Get compaction statistics"""
        with self._lock:
            return CompactionStats(
                total_compactions=self._stats.total_compactions,
                vectors_removed=self._stats.vectors_removed,
                clusters_created=self._stats.clusters_created,
                storage_saved_bytes=self._stats.storage_saved_bytes,
                last_compaction_time=self._stats.last_compaction_time
            )


class VectorRecoverySystem:
    """
    Vector backup and recovery system.
    
    Features:
    - Backup snapshots
    - Corruption detection
    - Recovery from backup
    - Reconstruction from partial data
    - Integrity verification
    """
    
    def __init__(
        self,
        storage_root: str = "./data/storage/vectors",
        max_snapshots: int = 10
    ):
        self.storage_root = Path(storage_root)
        self.max_snapshots = max_snapshots
        
        self._ensure_directories()
        
        self._snapshots: Dict[str, VectorSnapshot] = {}
        self._corruption_history: List[CorruptionReport] = []
        self._lock = threading.Lock()
        
        self._load_snapshots()
        
        logger.info(f"Vector recovery system initialized (max_snapshots={max_snapshots})")
    
    def _ensure_directories(self):
        """Create storage directories"""
        dirs = ["snapshots", "recovery"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)
    
    def create_snapshot(self) -> VectorSnapshot:
        """Create a backup snapshot"""
        import json
        import hashlib
        
        snapshot_id = f"snap_{int(time.time())}"
        
        snapshot_dir = self.storage_root / "snapshots" / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        index_path = snapshot_dir / "index.bin"
        metadata_path = snapshot_dir / "metadata.json"
        
        meta_file = self.storage_root / "metadata" / "vectors.json"
        if meta_file.exists():
            shutil.copy2(meta_file, metadata_path)
        
        index_file = self.storage_root / "index" / "vectors.bin"
        if index_file.exists():
            shutil.copy2(index_file, index_path)
            size_bytes = index_file.stat().st_size
            checksum = hashlib.sha256(index_file.read_bytes()).hexdigest()
        else:
            size_bytes = 0
            checksum = ""
        
        snapshot = VectorSnapshot(
            snapshot_id=snapshot_id,
            created_at=time.time(),
            vector_count=0,
            index_path=str(index_path),
            metadata_path=str(metadata_path),
            checksum=checksum,
            size_bytes=size_bytes
        )
        
        with self._lock:
            self._snapshots[snapshot_id] = snapshot
            self._cleanup_old_snapshots()
            self._save_snapshot_index()
        
        logger.info(f"Created snapshot: {snapshot_id}")
        
        return snapshot
    
    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore from a snapshot"""
        with self._lock:
            if snapshot_id not in self._snapshots:
                return False
            
            snapshot = self._snapshots[snapshot_id]
        
        try:
            snapshot_dir = self.storage_root / "snapshots" / snapshot_id
            
            index_src = snapshot_dir / "index.bin"
            index_dst = self.storage_root / "index" / "vectors.bin"
            if index_src.exists():
                shutil.copy2(index_src, index_dst)
            
            meta_src = snapshot_dir / "metadata.json"
            meta_dst = self.storage_root / "metadata" / "vectors.json"
            if meta_src.exists():
                shutil.copy2(meta_src, meta_dst)
            
            logger.info(f"Restored from snapshot: {snapshot_id}")
            return True
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False
    
    def verify_snapshot(self, snapshot_id: str) -> bool:
        """Verify snapshot integrity"""
        import hashlib
        
        with self._lock:
            if snapshot_id not in self._snapshots:
                return False
            
            snapshot = self._snapshots[snapshot_id]
        
        snapshot_dir = self.storage_root / "snapshots" / snapshot_id
        index_file = snapshot_dir / "index.bin"
        
        if not index_file.exists():
            return False
        
        current_checksum = hashlib.sha256(index_file.read_bytes()).hexdigest()
        
        return current_checksum == snapshot.checksum
    
    def detect_corruption(self) -> Optional[CorruptionReport]:
        """Detect corruption in current data"""
        import json
        
        meta_file = self.storage_root / "metadata" / "vectors.json"
        
        if not meta_file.exists():
            return None
        
        try:
            with open(meta_file, "r") as f:
                data = json.load(f)
            
            vectors = data.get("vectors", {})
            
            corrupted = []
            for entry_id, vec_data in vectors.items():
                if "vector" not in vec_data:
                    corrupted.append(entry_id)
                elif not isinstance(vec_data["vector"], list):
                    corrupted.append(entry_id)
            
            if corrupted:
                report = CorruptionReport(
                    snapshot_id="current",
                    detected_at=time.time(),
                    corrupted_entries=corrupted,
                    severity="medium" if len(corrupted) < 10 else "high",
                    recovery_action="restore_latest"
                )
                
                with self._lock:
                    self._corruption_history.append(report)
                
                logger.warning(f"Detected {len(corrupted)} corrupted entries")
                return report
            
            return None
            
        except Exception as e:
            logger.error(f"Corruption detection failed: {e}")
            return None
    
    def recover_from_partial(self) -> bool:
        """Attempt to reconstruct from partial data"""
        import json
        
        meta_file = self.storage_root / "metadata" / "vectors.json"
        
        if not meta_file.exists():
            return False
        
        try:
            with open(meta_file, "r") as f:
                data = json.load(f)
            
            vectors = data.get("vectors", {})
            
            valid_entries = {}
            for entry_id, vec_data in vectors.items():
                if isinstance(vec_data, dict) and "vector" in vec_data:
                    if isinstance(vec_data["vector"], list):
                        valid_entries[entry_id] = vec_data
            
            if valid_entries:
                data["vectors"] = valid_entries
                
                with open(meta_file, "w") as f:
                    json.dump(data, f)
                
                logger.info(f"Recovered {len(valid_entries)} valid entries")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Partial recovery failed: {e}")
            return False
    
    def get_latest_snapshot(self) -> Optional[VectorSnapshot]:
        """Get the latest snapshot"""
        with self._lock:
            if not self._snapshots:
                return None
            
            return max(self._snapshots.values(), key=lambda s: s.created_at)
    
    def list_snapshots(self) -> List[VectorSnapshot]:
        """List all snapshots"""
        with self._lock:
            return sorted(self._snapshots.values(), key=lambda s: s.created_at, reverse=True)
    
    def _cleanup_old_snapshots(self):
        """Remove old snapshots beyond max"""
        if len(self._snapshots) <= self.max_snapshots:
            return
        
        sorted_snapshots = sorted(
            self._snapshots.items(),
            key=lambda x: x[1].created_at,
            reverse=True
        )
        
        for snapshot_id, _ in sorted_snapshots[self.max_snapshots:]:
            del self._snapshots[snapshot_id]
            
            snapshot_dir = self.storage_root / "snapshots" / snapshot_id
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)
    
    def _load_snapshots(self):
        """Load snapshot index"""
        import json
        
        index_file = self.storage_root / "snapshots" / "index.json"
        
        if index_file.exists():
            try:
                with open(index_file, "r") as f:
                    data = json.load(f)
                    for item in data.get("snapshots", []):
                        self._snapshots[item["snapshot_id"]] = VectorSnapshot(**item)
                logger.info(f"Loaded {len(self._snapshots)} snapshots")
            except Exception as e:
                logger.error(f"Failed to load snapshots: {e}")
    
    def _save_snapshot_index(self):
        """Save snapshot index"""
        import json
        
        index_file = self.storage_root / "snapshots" / "index.json"
        
        try:
            data = {
                "snapshots": [
                    {
                        "snapshot_id": s.snapshot_id,
                        "created_at": s.created_at,
                        "vector_count": s.vector_count,
                        "index_path": s.index_path,
                        "metadata_path": s.metadata_path,
                        "checksum": s.checksum,
                        "size_bytes": s.size_bytes
                    }
                    for s in self._snapshots.values()
                ]
            }
            
            with open(index_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save snapshot index: {e}")


compaction_engine = VectorCompactionEngine()
vector_recovery = VectorRecoverySystem()