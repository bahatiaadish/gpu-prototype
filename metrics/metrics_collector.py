"""
VM Metrics Collection System
Time-series performance monitoring with Redis pub/sub
"""
import asyncio
import logging
import time
import psutil
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class MetricsCollector:
    """Collects and stores VM performance metrics"""
    
    def __init__(self, libvirt_manager, redis_manager, collection_interval: int = 30):
        self.libvirt_manager = libvirt_manager
        self.redis_manager = redis_manager
        self.collection_interval = collection_interval
        self.running = False
    
    async def start_collection(self):
        """Start metrics collection loop"""
        self.running = True
        logger.info("Starting metrics collection")
        
        while self.running:
            try:
                await self.collect_and_store_metrics()
                await asyncio.sleep(self.collection_interval)
                
            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                await asyncio.sleep(10)
    
    def stop_collection(self):
        """Stop metrics collection"""
        self.running = False
        logger.info("Stopped metrics collection")
    
    async def collect_and_store_metrics(self):
        """Collect metrics for all active VMs and store in database"""
        try:
            active_vms = self.libvirt_manager.list_active_vms()
            
            from database import db_session
            from database.models import VMInstance, VMMetric
            from messaging import MessageType
            
            with db_session() as session:
                for vm_info in active_vms:
                    vm_uuid = vm_info["uuid"]
                    
                    db_vm = session.query(VMInstance).filter_by(uuid=vm_uuid).first()
                    if not db_vm:
                        continue
                    
                    metrics = await self.collect_vm_metrics(vm_info)
                    
                    if metrics:
                        vm_metric = VMMetric(
                            vm_instance_id=db_vm.id,
                            cpu_usage_percent=metrics.get("cpu_usage_percent"),
                            memory_usage_percent=metrics.get("memory_usage_percent"),
                            disk_usage_percent=metrics.get("disk_usage_percent"),
                            network_rx_bytes=metrics.get("network_rx_bytes"),
                            network_tx_bytes=metrics.get("network_tx_bytes"),
                            gpu_usage_percent=metrics.get("gpu_usage_percent"),
                            gpu_memory_usage_percent=metrics.get("gpu_memory_usage_percent"),
                            gpu_temperature=metrics.get("gpu_temperature"),
                            timestamp=datetime.utcnow()
                        )
                        
                        session.add(vm_metric)
                        
                        self.redis_manager.publish_message(
                            MessageType.VM_METRICS,
                            {
                                "vm_uuid": vm_uuid,
                                "vm_name": db_vm.name,
                                "metrics": metrics,
                                "timestamp": time.time()
                            },
                            tenant_id=str(db_vm.tenant_id)
                        )
                
                session.commit()
                logger.debug(f"Collected metrics for {len(active_vms)} VMs")
                
        except Exception as e:
            logger.error(f"Error collecting and storing metrics: {e}")
    
    async def collect_vm_metrics(self, vm_info: Dict) -> Optional[Dict]:
        """
        Collect comprehensive metrics for a single VM
        
        Args:
            vm_info: VM information from libvirt
            
        Returns:
            Dictionary of collected metrics
        """
        try:
            metrics = {}
            
            cpu_time_ns = vm_info.get("cpu_time_ns", 0)
            vcpus = vm_info.get("vcpus", 1)
            
            if hasattr(self, '_previous_cpu_time'):
                prev_cpu_time = self._previous_cpu_time.get(vm_info["uuid"], 0)
                prev_timestamp = self._previous_timestamp.get(vm_info["uuid"], time.time())
                
                current_time = time.time()
                time_delta = current_time - prev_timestamp
                cpu_delta = cpu_time_ns - prev_cpu_time
                
                if time_delta > 0:
                    cpu_usage = (cpu_delta / (time_delta * 1e9 * vcpus)) * 100
                    metrics["cpu_usage_percent"] = min(100.0, max(0.0, cpu_usage))
            else:
                self._previous_cpu_time = {}
                self._previous_timestamp = {}
                metrics["cpu_usage_percent"] = 0.0
            
            self._previous_cpu_time[vm_info["uuid"]] = cpu_time_ns
            self._previous_timestamp[vm_info["uuid"]] = time.time()
            
            memory_kb = vm_info.get("memory_kb", 0)
            memory_used_kb = vm_info.get("memory_used_kb", 0)
            
            if memory_kb > 0:
                metrics["memory_usage_percent"] = (memory_used_kb / memory_kb) * 100
            else:
                metrics["memory_usage_percent"] = 0.0
            
            disk_metrics = await self.collect_disk_metrics(vm_info)
            metrics.update(disk_metrics)
            
            network_metrics = await self.collect_network_metrics(vm_info)
            metrics.update(network_metrics)
            
            gpu_metrics = await self.collect_gpu_metrics(vm_info)
            metrics.update(gpu_metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error collecting metrics for VM {vm_info.get('name', 'unknown')}: {e}")
            return None
    
    async def collect_disk_metrics(self, vm_info: Dict) -> Dict:
        """Collect disk I/O metrics for VM"""
        try:
            vm_name = vm_info.get("name", "")
            disk_path = f"/var/lib/libvirt/images/{vm_name}.qcow2"
            
            try:
                disk_usage = psutil.disk_usage(disk_path)
                disk_usage_percent = (disk_usage.used / disk_usage.total) * 100
            except (FileNotFoundError, PermissionError):
                disk_usage_percent = 0.0
            
            return {
                "disk_usage_percent": disk_usage_percent
            }
            
        except Exception as e:
            logger.debug(f"Error collecting disk metrics: {e}")
            return {"disk_usage_percent": 0.0}
    
    async def collect_network_metrics(self, vm_info: Dict) -> Dict:
        """Collect network I/O metrics for VM"""
        try:
            vm_name = vm_info.get("name", "")
            
            if hasattr(self, '_previous_network_stats'):
                prev_stats = self._previous_network_stats.get(vm_name, {})
                prev_rx = prev_stats.get("rx_bytes", 0)
                prev_tx = prev_stats.get("tx_bytes", 0)
                prev_time = prev_stats.get("timestamp", time.time())
            else:
                self._previous_network_stats = {}
                prev_rx = prev_tx = 0
                prev_time = time.time()
            
            current_time = time.time()
            time_delta = current_time - prev_time
            
            current_rx = 0
            current_tx = 0
            
            try:
                net_stats = psutil.net_io_counters(pernic=True)
                for interface, stats in net_stats.items():
                    if vm_name in interface or interface.startswith('vnet'):
                        current_rx += stats.bytes_recv
                        current_tx += stats.bytes_sent
            except Exception:
                pass
            
            if time_delta > 0:
                rx_rate = max(0, (current_rx - prev_rx) / time_delta)
                tx_rate = max(0, (current_tx - prev_tx) / time_delta)
            else:
                rx_rate = tx_rate = 0
            
            self._previous_network_stats[vm_name] = {
                "rx_bytes": current_rx,
                "tx_bytes": current_tx,
                "timestamp": current_time
            }
            
            return {
                "network_rx_bytes": int(rx_rate),
                "network_tx_bytes": int(tx_rate)
            }
            
        except Exception as e:
            logger.debug(f"Error collecting network metrics: {e}")
            return {"network_rx_bytes": 0, "network_tx_bytes": 0}
    
    async def collect_gpu_metrics(self, vm_info: Dict) -> Dict:
        """Collect GPU metrics for VM (if GPU passthrough enabled)"""
        try:
            gpu_metrics = {
                "gpu_usage_percent": None,
                "gpu_memory_usage_percent": None,
                "gpu_temperature": None
            }
            
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.memory,temperature.gpu", 
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if lines and lines[0]:
                        gpu_data = lines[0].split(', ')
                        if len(gpu_data) >= 3:
                            gpu_metrics["gpu_usage_percent"] = float(gpu_data[0])
                            gpu_metrics["gpu_memory_usage_percent"] = float(gpu_data[1])
                            gpu_metrics["gpu_temperature"] = float(gpu_data[2])
                            
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ImportError, ValueError):
                pass
            
            return gpu_metrics
            
        except Exception as e:
            logger.debug(f"Error collecting GPU metrics: {e}")
            return {
                "gpu_usage_percent": None,
                "gpu_memory_usage_percent": None,
                "gpu_temperature": None
            }
