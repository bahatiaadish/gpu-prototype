"""
Advanced libvirt VM lifecycle management with GPU passthrough
"""
import libvirt
import xml.etree.ElementTree as ET
from xml.dom import minidom
import yaml
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import psutil
import uuid

logger = logging.getLogger(__name__)

@dataclass
class HostConfig:
    """Host-specific configuration for VM resources"""
    cpu_cores: List[int]
    hugepages_1g: int
    hugepages_2m: int
    gpu_devices: List[Dict[str, str]]
    network_interfaces: List[Dict[str, str]]
    numa_nodes: List[Dict[str, any]]

@dataclass
class VMSpec:
    """VM specification for creation"""
    name: str
    memory_gb: int
    vcpus: int
    disk_size_gb: int
    gpu_passthrough: bool = False
    cpu_pinning: bool = False
    hugepages: bool = False
    network_isolation: bool = True
    tenant_id: str = None

class LibvirtManager:
    """Advanced libvirt operations with hardware optimization"""
    
    def __init__(self, uri: str = "qemu:///system", config_path: str = "./config/host-config.yaml"):
        self.uri = uri
        self.conn = None
        self.host_config = self._load_host_config(config_path)
        self._connect()
    
    def _connect(self):
        """Establish libvirt connection with error handling"""
        try:
            self.conn = libvirt.open(self.uri)
            logger.info(f"Connected to libvirt at {self.uri}")
        except libvirt.libvirtError as e:
            logger.error(f"Failed to connect to libvirt: {e}")
            raise
    
    def _load_host_config(self, config_path: str) -> HostConfig:
        """Load host-specific configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
            
            return HostConfig(
                cpu_cores=config_data.get('cpu_cores', list(range(psutil.cpu_count()))),
                hugepages_1g=config_data.get('hugepages_1g', 0),
                hugepages_2m=config_data.get('hugepages_2m', 0),
                gpu_devices=config_data.get('gpu_devices', []),
                network_interfaces=config_data.get('network_interfaces', []),
                numa_nodes=config_data.get('numa_nodes', [])
            )
        except FileNotFoundError:
            logger.warning(f"Host config not found at {config_path}, using defaults")
            return HostConfig(
                cpu_cores=list(range(psutil.cpu_count())),
                hugepages_1g=0,
                hugepages_2m=0,
                gpu_devices=[],
                network_interfaces=[],
                numa_nodes=[]
            )
    
    def generate_vm_xml(self, vm_spec: VMSpec) -> str:
        """Generate optimized libvirt XML with advanced features"""
        
        domain = ET.Element('domain', type='kvm')
        
        name = ET.SubElement(domain, 'name')
        name.text = vm_spec.name
        
        uuid_elem = ET.SubElement(domain, 'uuid')
        uuid_elem.text = str(uuid.uuid4())
        
        memory = ET.SubElement(domain, 'memory', unit='GiB')
        memory.text = str(vm_spec.memory_gb)
        
        current_memory = ET.SubElement(domain, 'currentMemory', unit='GiB')
        current_memory.text = str(vm_spec.memory_gb)
        
        vcpu = ET.SubElement(domain, 'vcpu', placement='static')
        vcpu.text = str(vm_spec.vcpus)
        
        if vm_spec.cpu_pinning:
            self._add_cpu_pinning(domain, vm_spec)
        
        if vm_spec.hugepages:
            self._add_hugepages_config(domain, vm_spec)
        
        os_elem = ET.SubElement(domain, 'os')
        os_type = ET.SubElement(os_elem, 'type', arch='x86_64', machine='pc-q35-6.2')
        os_type.text = 'hvm'
        
        boot = ET.SubElement(os_elem, 'boot', dev='hd')
        
        features = ET.SubElement(domain, 'features')
        ET.SubElement(features, 'acpi')
        ET.SubElement(features, 'apic')
        ET.SubElement(features, 'pae')
        
        if vm_spec.gpu_passthrough:
            hyperv = ET.SubElement(features, 'hyperv')
            ET.SubElement(hyperv, 'relaxed', state='on')
            ET.SubElement(hyperv, 'vapic', state='on')
            ET.SubElement(hyperv, 'spinlocks', state='on', retries='8191')
            
            kvm = ET.SubElement(features, 'kvm')
            ET.SubElement(kvm, 'hidden', state='on')
        
        devices = ET.SubElement(domain, 'devices')
        
        self._add_disk_config(devices, vm_spec)
        self._add_network_config(devices, vm_spec)
        
        if vm_spec.gpu_passthrough:
            self._add_gpu_passthrough(devices, vm_spec)
        
        self._add_console_config(devices)
        
        rough_string = ET.tostring(domain, 'unicode')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
    
    def _add_cpu_pinning(self, domain: ET.Element, vm_spec: VMSpec):
        """Add CPU pinning configuration for performance isolation"""
        cpu = ET.SubElement(domain, 'cpu', mode='host-passthrough', check='none')
        
        numa = ET.SubElement(cpu, 'numa')
        
        allocated_cores = self.host_config.cpu_cores[:vm_spec.vcpus]
        
        cell = ET.SubElement(numa, 'cell', 
                           id='0', 
                           cpus=','.join(map(str, allocated_cores)),
                           memory=str(vm_spec.memory_gb * 1024 * 1024))
        
        cputune = ET.SubElement(domain, 'cputune')
        for i, core in enumerate(allocated_cores):
            vcpupin = ET.SubElement(cputune, 'vcpupin', vcpu=str(i), cpuset=str(core))
    
    def _add_hugepages_config(self, domain: ET.Element, vm_spec: VMSpec):
        """Configure hugepages for memory performance"""
        memoryBacking = ET.SubElement(domain, 'memoryBacking')
        hugepages = ET.SubElement(memoryBacking, 'hugepages')
        
        if self.host_config.hugepages_1g > 0:
            page = ET.SubElement(hugepages, 'page', size='1048576', unit='KiB')
        elif self.host_config.hugepages_2m > 0:
            page = ET.SubElement(hugepages, 'page', size='2048', unit='KiB')
    
    def _add_disk_config(self, devices: ET.Element, vm_spec: VMSpec):
        """Add high-performance disk configuration"""
        disk = ET.SubElement(devices, 'disk', type='file', device='disk')
        
        driver = ET.SubElement(disk, 'driver', 
                             name='qemu', 
                             type='qcow2',
                             cache='none',
                             io='native',
                             discard='unmap')
        
        source = ET.SubElement(disk, 'source', 
                             file=f'/var/lib/libvirt/images/{vm_spec.name}.qcow2')
        
        target = ET.SubElement(disk, 'target', dev='vda', bus='virtio')
        boot = ET.SubElement(disk, 'boot', order='1')
    
    def _add_network_config(self, devices: ET.Element, vm_spec: VMSpec):
        """Add network interface with OVS integration"""
        interface = ET.SubElement(devices, 'interface', type='bridge')
        
        source = ET.SubElement(interface, 'source', bridge='br-tenant')
        model = ET.SubElement(interface, 'model', type='virtio')
        
        if vm_spec.tenant_id:
            vlan = ET.SubElement(interface, 'vlan')
            tag = ET.SubElement(vlan, 'tag', id=str(hash(vm_spec.tenant_id) % 4094 + 1))
    
    def _add_gpu_passthrough(self, devices: ET.Element, vm_spec: VMSpec):
        """Add GPU passthrough configuration"""
        for gpu in self.host_config.gpu_devices:
            hostdev = ET.SubElement(devices, 'hostdev', 
                                  mode='subsystem', 
                                  type='pci', 
                                  managed='yes')
            
            source = ET.SubElement(hostdev, 'source')
            address = ET.SubElement(source, 'address',
                                  domain=gpu['domain'],
                                  bus=gpu['bus'],
                                  slot=gpu['slot'],
                                  function=gpu['function'])
    
    def _add_console_config(self, devices: ET.Element):
        """Add console and graphics configuration"""
        serial = ET.SubElement(devices, 'serial', type='pty')
        target = ET.SubElement(serial, 'target', type='isa-serial', port='0')
        
        console = ET.SubElement(devices, 'console', type='pty')
        target = ET.SubElement(console, 'target', type='serial', port='0')
        
        graphics = ET.SubElement(devices, 'graphics', 
                               type='vnc', 
                               port='-1', 
                               autoport='yes',
                               listen='0.0.0.0')
    
    async def create_vm(self, vm_spec: VMSpec) -> str:
        """Create and start a new VM"""
        try:
            xml_config = self.generate_vm_xml(vm_spec)
            
            await self._create_disk_image(vm_spec)
            
            domain = self.conn.defineXML(xml_config)
            domain.create()
            
            logger.info(f"Successfully created VM: {vm_spec.name}")
            return domain.UUIDString()
            
        except libvirt.libvirtError as e:
            logger.error(f"Failed to create VM {vm_spec.name}: {e}")
            raise
    
    async def _create_disk_image(self, vm_spec: VMSpec):
        """Create qcow2 disk image for VM"""
        disk_path = f"/var/lib/libvirt/images/{vm_spec.name}.qcow2"
        
        cmd = [
            "qemu-img", "create", "-f", "qcow2",
            "-o", "cluster_size=2M,lazy_refcounts=on",
            disk_path, f"{vm_spec.disk_size_gb}G"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Failed to create disk image: {stderr.decode()}")
    
    def get_vm_status(self, vm_name: str) -> Dict:
        """Get comprehensive VM status information"""
        try:
            domain = self.conn.lookupByName(vm_name)
            
            state, reason = domain.state()
            info = domain.info()
            
            return {
                "name": vm_name,
                "uuid": domain.UUIDString(),
                "state": self._state_to_string(state),
                "memory_kb": info[1],
                "memory_used_kb": info[2],
                "vcpus": info[3],
                "cpu_time_ns": info[4],
                "autostart": domain.autostart(),
                "persistent": domain.isPersistent(),
                "xml_config": domain.XMLDesc()
            }
            
        except libvirt.libvirtError as e:
            logger.error(f"Failed to get VM status for {vm_name}: {e}")
            return None
    
    def _state_to_string(self, state: int) -> str:
        """Convert libvirt state integer to string"""
        states = {
            libvirt.VIR_DOMAIN_NOSTATE: "no_state",
            libvirt.VIR_DOMAIN_RUNNING: "running",
            libvirt.VIR_DOMAIN_BLOCKED: "blocked",
            libvirt.VIR_DOMAIN_PAUSED: "paused",
            libvirt.VIR_DOMAIN_SHUTDOWN: "shutdown",
            libvirt.VIR_DOMAIN_SHUTOFF: "shutoff",
            libvirt.VIR_DOMAIN_CRASHED: "crashed",
            libvirt.VIR_DOMAIN_PMSUSPENDED: "suspended"
        }
        return states.get(state, "unknown")
    
    def list_active_vms(self) -> List[Dict]:
        """List all active VMs with their status"""
        try:
            active_domains = self.conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE)
            
            vms = []
            for domain in active_domains:
                vm_info = self.get_vm_status(domain.name())
                if vm_info:
                    vms.append(vm_info)
            
            return vms
            
        except libvirt.libvirtError as e:
            logger.error(f"Failed to list active VMs: {e}")
            return []
    
    def close(self):
        """Close libvirt connection"""
        if self.conn:
            self.conn.close()
            logger.info("Closed libvirt connection")
