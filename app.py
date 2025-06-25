"""
GPU Cloud Platform Flask Application
Main application entry point with unified API responses and RBAC
"""
import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from api import APIResponse, api_response, require_permission, init_rbac
from database import init_database
from messaging import RedisManager, MessageType
from vm_manager import LibvirtManager, VMSpec
from network import OVSManager
from metrics import MetricsCollector

load_dotenv()

logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

CORS(app, origins=["*"])

database_url = os.getenv('DATABASE_URL', 'sqlite:///gpu_cloud.db')
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

try:
    init_database(database_url)
    init_rbac(database_url)
    
    redis_manager = RedisManager(redis_url)
    redis_manager.connect()
    
    libvirt_manager = LibvirtManager()
    ovs_manager = OVSManager()
    metrics_collector = MetricsCollector(libvirt_manager, redis_manager)
    
    logger.info("All services initialized successfully")
    
except Exception as e:
    logger.error(f"Failed to initialize services: {e}")
    redis_manager = None
    libvirt_manager = None
    ovs_manager = None
    metrics_collector = None

@app.route('/api/health', methods=['GET'])
@api_response
def health_check():
    """Health check endpoint with service status"""
    services = {
        "database": "healthy" if database_url else "unavailable",
        "redis": "healthy" if redis_manager else "unavailable", 
        "libvirt": "healthy" if libvirt_manager else "unavailable",
        "ovs": "healthy" if ovs_manager else "unavailable"
    }
    
    overall_status = "healthy" if all(status == "healthy" for status in services.values()) else "degraded"
    
    return APIResponse.success({
        "status": overall_status,
        "services": services,
        "version": "1.0.0"
    }, f"System status: {overall_status}")

@app.route('/api/vms', methods=['GET'])
@require_permission('vm:read')
@api_response
def list_vms():
    """List VMs for current tenant"""
    from database import db_session
    from database.models import VMInstance
    from api.rbac import get_current_tenant_id
    
    tenant_id = get_current_tenant_id()
    
    with db_session() as session:
        vms = session.query(VMInstance).filter_by(tenant_id=tenant_id).all()
        
        vm_list = []
        for vm in vms:
            vm_data = {
                "id": vm.id,
                "uuid": vm.uuid,
                "name": vm.name,
                "status": vm.status,
                "memory_gb": vm.memory_gb,
                "vcpus": vm.vcpus,
                "disk_gb": vm.disk_gb,
                "gpu_enabled": vm.gpu_enabled,
                "created_at": vm.created_at.isoformat() if vm.created_at else None
            }
            vm_list.append(vm_data)
        
        return APIResponse.paginated(
            data=vm_list,
            page=1,
            per_page=len(vm_list),
            total=len(vm_list)
        )

@app.route('/api/vms', methods=['POST'])
@require_permission('vm:create')
@api_response
def create_vm():
    """Create a new VM"""
    data = request.get_json()
    
    if not data:
        raise ValueError("Request body is required")
    
    required_fields = ['name', 'memory_gb', 'vcpus', 'disk_gb']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    
    from database import db_session
    from database.models import VMInstance
    from api.rbac import get_current_user, get_current_tenant_id
    
    current_user = get_current_user()
    tenant_id = get_current_tenant_id()
    
    vm_spec = VMSpec(
        name=data['name'],
        memory_gb=data['memory_gb'],
        vcpus=data['vcpus'],
        disk_size_gb=data['disk_gb'],
        gpu_passthrough=data.get('gpu_passthrough', False),
        cpu_pinning=data.get('cpu_pinning', False),
        hugepages=data.get('hugepages', False),
        tenant_id=str(tenant_id)
    )
    
    try:
        if libvirt_manager:
            import asyncio
            vm_uuid = asyncio.run(libvirt_manager.create_vm(vm_spec))
        else:
            import uuid
            vm_uuid = str(uuid.uuid4())
        
        with db_session() as session:
            vm_instance = VMInstance(
                uuid=vm_uuid,
                name=data['name'],
                status='creating',
                memory_gb=data['memory_gb'],
                vcpus=data['vcpus'],
                disk_gb=data['disk_gb'],
                gpu_enabled=data.get('gpu_passthrough', False),
                cpu_pinning=data.get('cpu_pinning', False),
                hugepages=data.get('hugepages', False),
                tenant_id=tenant_id,
                owner_id=current_user.id
            )
            
            session.add(vm_instance)
            session.commit()
            
            if redis_manager:
                redis_manager.publish_message(
                    MessageType.VM_CREATED,
                    {
                        "vm_uuid": vm_uuid,
                        "vm_name": data['name'],
                        "tenant_id": tenant_id
                    },
                    tenant_id=str(tenant_id)
                )
            
            return {
                "vm_id": vm_instance.id,
                "vm_uuid": vm_uuid,
                "name": data['name'],
                "status": "creating"
            }
    
    except Exception as e:
        logger.error(f"Failed to create VM: {e}")
        raise Exception(f"VM creation failed: {str(e)}")

@app.route('/api/vms/<vm_uuid>/metrics', methods=['GET'])
@require_permission('metrics:read')
@api_response
def get_vm_metrics(vm_uuid):
    """Get metrics for a specific VM"""
    from database import db_session
    from database.models import VMInstance, VMMetric
    from api.rbac import get_current_tenant_id
    
    tenant_id = get_current_tenant_id()
    
    with db_session() as session:
        vm = session.query(VMInstance).filter_by(
            uuid=vm_uuid, 
            tenant_id=tenant_id
        ).first()
        
        if not vm:
            raise FileNotFoundError("VM not found")
        
        metrics = session.query(VMMetric).filter_by(
            vm_instance_id=vm.id
        ).order_by(VMMetric.timestamp.desc()).limit(100).all()
        
        metrics_data = []
        for metric in metrics:
            metrics_data.append({
                "timestamp": metric.timestamp.isoformat(),
                "cpu_usage_percent": metric.cpu_usage_percent,
                "memory_usage_percent": metric.memory_usage_percent,
                "disk_usage_percent": metric.disk_usage_percent,
                "network_rx_bytes": metric.network_rx_bytes,
                "network_tx_bytes": metric.network_tx_bytes,
                "gpu_usage_percent": metric.gpu_usage_percent,
                "gpu_memory_usage_percent": metric.gpu_memory_usage_percent,
                "gpu_temperature": metric.gpu_temperature
            })
        
        return {
            "vm_uuid": vm_uuid,
            "vm_name": vm.name,
            "metrics": metrics_data
        }

@app.route('/api/networks', methods=['GET'])
@require_permission('network:read')
@api_response
def list_networks():
    """List networks for current tenant"""
    from database import db_session
    from database.models import Network
    from api.rbac import get_current_tenant_id
    
    tenant_id = get_current_tenant_id()
    
    with db_session() as session:
        networks = session.query(Network).filter_by(tenant_id=tenant_id).all()
        
        network_list = []
        for network in networks:
            network_data = {
                "id": network.id,
                "name": network.name,
                "cidr": network.cidr,
                "vlan_id": network.vlan_id,
                "is_public": network.is_public,
                "created_at": network.created_at.isoformat() if network.created_at else None
            }
            network_list.append(network_data)
        
        return network_list

@app.route('/api/debug/ovs-flows', methods=['GET'])
@require_permission('admin:system')
@api_response
def debug_ovs_flows():
    """Debug OVS flows (admin only)"""
    if not ovs_manager:
        raise ConnectionError("OVS manager not available")
    
    table = request.args.get('table', type=int)
    flow_analysis = ovs_manager.debug_flows(table)
    
    return flow_analysis

@app.route('/api/system/stats', methods=['GET'])
@require_permission('admin:system')
@api_response
def system_stats():
    """Get system statistics (admin only)"""
    stats = {}
    
    if redis_manager:
        stats["redis"] = redis_manager.get_system_stats()
    
    if libvirt_manager:
        try:
            active_vms = libvirt_manager.list_active_vms()
            stats["libvirt"] = {
                "active_vms": len(active_vms),
                "vm_states": {}
            }
            
            for vm in active_vms:
                state = vm.get("state", "unknown")
                stats["libvirt"]["vm_states"][state] = stats["libvirt"]["vm_states"].get(state, 0) + 1
                
        except Exception as e:
            stats["libvirt"] = {"error": str(e)}
    
    return stats

@app.errorhandler(404)
@api_response
def not_found(error):
    """Handle 404 errors with unified response"""
    return APIResponse.error(
        message="Endpoint not found",
        error_code="NOT_FOUND"
    ), 404

@app.errorhandler(500)
@api_response
def internal_error(error):
    """Handle 500 errors with unified response"""
    logger.error(f"Internal server error: {error}")
    return APIResponse.error(
        message="Internal server error",
        error_code="INTERNAL_ERROR"
    ), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Starting GPU Cloud Platform on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
