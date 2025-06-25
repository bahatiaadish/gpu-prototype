# GPU Cloud Platform Prototype

A comprehensive self-service GPU cloud platform built from scratch, demonstrating advanced Python engineering skills for high-performance virtual machine provisioning, container orchestration, and on-demand compute clusters.

## 🏗️ Architecture Overview

This prototype showcases a production-ready, Python-first stack integrating:

- **Flask API** with unified response envelopes and hierarchical RBAC
- **libvirt/KVM** for VM lifecycle management with GPU passthrough
- **Open vSwitch** for software-defined networking and tenant isolation  
- **Redis** for messaging, task queues, and distributed coordination
- **SQLAlchemy + MariaDB** for data persistence and time-series metrics
- **WebSocket** server for real-time VM reconciliation reporting
- **Docker** containerization for microservices deployment

## 🚀 Key Technical Features

### Unified API Response System
- Standardized `api_response()` envelope across all endpoints
- Comprehensive exception handling with proper HTTP status codes
- Structured error responses with machine-readable error codes

### Hierarchical RBAC System
- JWT-based authentication with tenant isolation
- Permission-based access control (`vm:create`, `network:read`, etc.)
- Role hierarchy: `admin`, `tenant_admin`, `user`, `viewer`
- Database-backed with SQLAlchemy models

### Advanced VM Management
- **libvirt XML Generation** with CPU pinning, hugepages, NUMA topology
- **GPU Passthrough** with PCI device assignment and hypervisor optimization
- **High-Performance Storage** using qcow2 with cache=none, io=native
- **60-Second Reconciliation Loop** comparing libvirt vs database state

### Software-Defined Networking
- **Dynamic OVS Flow Management** without hardcoded table numbers
- **Interface UUID Resolution** with retry logic and graceful fallback
- **Tenant Isolation** using VLAN tagging and security groups
- **Flow Debugging Utilities** for troubleshooting network issues

### Time-Series Metrics Collection
- **VM Performance Monitoring**: CPU, memory, disk I/O, network traffic
- **GPU Metrics**: Usage, memory utilization, temperature (nvidia-smi)
- **Real-time Broadcasting** via Redis pub/sub and WebSocket
- **Database Storage** with timestamp indexing for efficient queries

### Redis Messaging & Task Queues
- **Pub/Sub Messaging** with message type enumeration
- **Lua Scripts** for atomic operations and rate limiting
- **Distributed Locking** for coordination across services
- **Task Queue** with priority-based processing

## 📁 Project Structure

```
gpu-prototype/
├── api/                    # API layer with response envelopes and RBAC
│   ├── __init__.py
│   ├── response_envelope.py   # Unified APIResponse class
│   └── rbac.py               # Role-based access control decorators
├── database/               # Data models and session management
│   ├── __init__.py
│   └── models.py            # SQLAlchemy models with relationships
├── vm_manager/             # Virtual machine lifecycle management
│   ├── __init__.py
│   ├── libvirt_manager.py   # VM creation with GPU passthrough
│   └── reconciliation_loop.py # WebSocket reconciliation service
├── network/                # Open vSwitch flow management
│   ├── __init__.py
│   └── ovs_manager.py       # Dynamic flow rule generation
├── messaging/              # Redis pub/sub and task queues
│   ├── __init__.py
│   └── redis_manager.py     # Advanced Redis operations with Lua
├── metrics/                # Performance monitoring
│   ├── __init__.py
│   └── metrics_collector.py # Time-series data collection
├── config/                 # Host configuration
│   └── host-config.yaml    # CPU, GPU, network, NUMA settings
├── tests/                  # Test suite
│   ├── __init__.py
│   └── test_api.py         # API endpoint and RBAC tests
├── docs/                   # GitHub Pages documentation
│   └── index.html          # Project showcase page
├── app.py                  # Flask application entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment configuration template
└── README.md              # This file
```

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.8+
- libvirt/KVM
- Redis Server
- MariaDB/MySQL
- Open vSwitch
- NVIDIA drivers (for GPU passthrough)

### Environment Configuration
```bash
cp .env.example .env
# Edit .env with your database and Redis credentials
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Database Setup
```bash
# The application will automatically create tables on first run
python app.py
```

### Host Configuration
Edit `config/host-config.yaml` to match your hardware:
- CPU cores available for VM allocation
- GPU devices for passthrough (PCI addresses)
- Network interfaces and NUMA topology
- Hugepages configuration

## 🚦 API Endpoints

### Health & System
- `GET /api/health` - Service health check
- `GET /api/system/stats` - System statistics (admin only)

### Virtual Machines
- `GET /api/vms` - List tenant VMs (requires `vm:read`)
- `POST /api/vms` - Create new VM (requires `vm:create`)
- `GET /api/vms/{uuid}/metrics` - VM performance metrics (requires `metrics:read`)

### Networking
- `GET /api/networks` - List tenant networks (requires `network:read`)

### Debugging
- `GET /api/debug/ovs-flows` - OVS flow analysis (admin only)

### Example VM Creation
```bash
curl -X POST http://localhost:5000/api/vms \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "gpu-workstation-01",
    "memory_gb": 16,
    "vcpus": 8,
    "disk_gb": 100,
    "gpu_passthrough": true,
    "cpu_pinning": true,
    "hugepages": true
  }'
```

## 🎯 Technical Highlights

This prototype demonstrates senior-level engineering capabilities:

1. **System Architecture**: Microservices design with clear separation of concerns
2. **Performance Optimization**: CPU pinning, hugepages, NUMA awareness
3. **Scalability**: Horizontal scaling patterns and distributed coordination
4. **Observability**: Comprehensive logging, metrics, and real-time monitoring
5. **Security**: Multi-tenant isolation, RBAC, and network segmentation
6. **Code Quality**: Type hints, comprehensive error handling, test coverage

## 📄 License

MIT License - See LICENSE file for details.

---

**Built with ❤️ for demonstrating advanced Python engineering skills in cloud infrastructure, virtualization, and distributed systems.**
