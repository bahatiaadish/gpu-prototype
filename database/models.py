"""
SQLAlchemy Models for GPU Cloud Platform
Comprehensive data models with relationships and constraints
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float, JSON, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, Dict, Any, Set

Base = declarative_base()

user_roles = Table('user_roles', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id'), primary_key=True)
)

role_permissions = Table('role_permissions', Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id'), primary_key=True)
)

class Tenant(Base):
    """Multi-tenant organization model"""
    __tablename__ = 'tenants'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(50), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    resource_quota = Column(JSON, default=lambda: {})
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    users = relationship("User", back_populates="tenant")
    vm_instances = relationship("VMInstance", back_populates="tenant")
    networks = relationship("Network", back_populates="tenant")

class User(Base):
    """User model with RBAC integration"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    tenant = relationship("Tenant", back_populates="users")
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    vm_instances = relationship("VMInstance", back_populates="owner")
    
    def get_permissions(self) -> Set[str]:
        """Get all permissions for this user across all roles"""
        permissions = set()
        for role in self.roles:
            permissions.update(perm.name for perm in role.permissions)
        return permissions
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission"""
        return permission in self.get_permissions()

class Role(Base):
    """Role-based access control roles"""
    __tablename__ = 'roles'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(255))
    is_system_role = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

class Permission(Base):
    """Granular permissions for RBAC"""
    __tablename__ = 'permissions'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    resource = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    description = Column(String(255))
    
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

class VMInstance(Base):
    """Virtual Machine instance model"""
    __tablename__ = 'vm_instances'
    
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default='creating')
    memory_gb = Column(Integer, nullable=False)
    vcpus = Column(Integer, nullable=False)
    disk_gb = Column(Integer, nullable=False)
    
    gpu_enabled = Column(Boolean, default=False)
    gpu_type = Column(String(50))
    cpu_pinning = Column(Boolean, default=False)
    hugepages = Column(Boolean, default=False)
    
    network_id = Column(Integer, ForeignKey('networks.id'))
    private_ip = Column(String(15))
    public_ip = Column(String(15))
    
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    tenant = relationship("Tenant", back_populates="vm_instances")
    owner = relationship("User", back_populates="vm_instances")
    network = relationship("Network", back_populates="vm_instances")
    metrics = relationship("VMMetric", back_populates="vm_instance")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    started_at = Column(DateTime)
    stopped_at = Column(DateTime)

class Network(Base):
    """Network configuration for tenant isolation"""
    __tablename__ = 'networks'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    cidr = Column(String(18), nullable=False)
    vlan_id = Column(Integer, unique=True)
    bridge_name = Column(String(50), default='br-tenant')
    
    is_public = Column(Boolean, default=False)
    allow_internet = Column(Boolean, default=True)
    security_groups = Column(JSON, default=lambda: [])
    
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    tenant = relationship("Tenant", back_populates="networks")
    vm_instances = relationship("VMInstance", back_populates="network")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class VMMetric(Base):
    """Time-series metrics for VM monitoring"""
    __tablename__ = 'vm_metrics'
    
    id = Column(Integer, primary_key=True)
    vm_instance_id = Column(Integer, ForeignKey('vm_instances.id'), nullable=False)
    
    cpu_usage_percent = Column(Float)
    memory_usage_percent = Column(Float)
    disk_usage_percent = Column(Float)
    network_rx_bytes = Column(Integer)
    network_tx_bytes = Column(Integer)
    
    gpu_usage_percent = Column(Float)
    gpu_memory_usage_percent = Column(Float)
    gpu_temperature = Column(Float)
    
    timestamp = Column(DateTime, default=func.now(), index=True)
    
    vm_instance = relationship("VMInstance", back_populates="metrics")

class HostNode(Base):
    """Physical host node information"""
    __tablename__ = 'host_nodes'
    
    id = Column(Integer, primary_key=True)
    hostname = Column(String(100), unique=True, nullable=False)
    ip_address = Column(String(15), nullable=False)
    
    cpu_cores = Column(Integer, nullable=False)
    memory_gb = Column(Integer, nullable=False)
    disk_gb = Column(Integer, nullable=False)
    gpu_count = Column(Integer, default=0)
    gpu_types = Column(JSON, default=lambda: [])
    
    allocated_cpu_cores = Column(Integer, default=0)
    allocated_memory_gb = Column(Integer, default=0)
    allocated_disk_gb = Column(Integer, default=0)
    allocated_gpus = Column(Integer, default=0)
    
    status = Column(String(20), default='active')
    last_heartbeat = Column(DateTime)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
