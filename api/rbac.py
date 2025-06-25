"""
Hierarchical Role-Based Access Control (RBAC) System
Advanced permission management with tenant isolation and JWT authentication
"""
from functools import wraps
from flask import request, g, current_app
import jwt
from typing import List, Set, Optional
import logging

logger = logging.getLogger(__name__)

rbac_manager = None

class RBACManager:
    """Manages RBAC operations and database connections"""
    
    def __init__(self, database_url: str):
        from database import get_engine, get_session_factory
        self.engine = get_engine(database_url)
        self.SessionLocal = get_session_factory(self.engine)
    
    def get_user_by_token(self, token: str):
        """Decode JWT token and retrieve user with permissions"""
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
            
            with self.SessionLocal() as session:
                from database.models import User
                
                user = session.query(User).filter(
                    User.id == user_id,
                    User.is_active == True
                ).first()
                
                if user:
                    session.expunge(user)
                    return user
                    
        except jwt.InvalidTokenError:
            logger.warning("Invalid JWT token provided")
        except Exception as e:
            logger.error(f"Error retrieving user from token: {e}")
        
        return None
    
    def create_permission(self, name: str, resource: str, action: str, description: str = None):
        """Create a new permission"""
        with self.SessionLocal() as session:
            from database.models import Permission
            
            permission = Permission(
                name=name,
                resource=resource,
                action=action,
                description=description
            )
            session.add(permission)
            session.commit()
            return permission
    
    def seed_default_permissions(self):
        """Seed database with default permissions and roles"""
        with self.SessionLocal() as session:
            from database.models import Permission, Role, role_permissions
            
            default_permissions = [
                ("vm:create", "vm", "create", "Create virtual machines"),
                ("vm:read", "vm", "read", "View virtual machines"),
                ("vm:update", "vm", "update", "Modify virtual machines"),
                ("vm:delete", "vm", "delete", "Delete virtual machines"),
                ("vm:start", "vm", "start", "Start virtual machines"),
                ("vm:stop", "vm", "stop", "Stop virtual machines"),
                
                ("network:create", "network", "create", "Create networks"),
                ("network:read", "network", "read", "View networks"),
                ("network:update", "network", "update", "Modify networks"),
                ("network:delete", "network", "delete", "Delete networks"),
                
                ("metrics:read", "metrics", "read", "View performance metrics"),
                
                ("admin:users", "admin", "users", "Manage users"),
                ("admin:roles", "admin", "roles", "Manage roles"),
                ("admin:system", "admin", "system", "System administration"),
            ]
            
            for perm_name, resource, action, description in default_permissions:
                existing = session.query(Permission).filter_by(name=perm_name).first()
                if not existing:
                    permission = Permission(
                        name=perm_name,
                        resource=resource,
                        action=action,
                        description=description
                    )
                    session.add(permission)
            
            default_roles = [
                ("admin", "System Administrator", True),
                ("tenant_admin", "Tenant Administrator", False),
                ("user", "Regular User", False),
                ("viewer", "Read-only User", False),
            ]
            
            for role_name, description, is_system in default_roles:
                existing = session.query(Role).filter_by(name=role_name).first()
                if not existing:
                    role = Role(
                        name=role_name,
                        description=description,
                        is_system_role=is_system
                    )
                    session.add(role)
            
            session.commit()
            
            role_permission_mapping = {
                "admin": [p[0] for p in default_permissions],
                "tenant_admin": [
                    "vm:create", "vm:read", "vm:update", "vm:delete", "vm:start", "vm:stop",
                    "network:create", "network:read", "network:update", "network:delete",
                    "metrics:read"
                ],
                "user": [
                    "vm:create", "vm:read", "vm:start", "vm:stop",
                    "network:read", "metrics:read"
                ],
                "viewer": ["vm:read", "network:read", "metrics:read"]
            }
            
            for role_name, permission_names in role_permission_mapping.items():
                role = session.query(Role).filter_by(name=role_name).first()
                if role:
                    for perm_name in permission_names:
                        permission = session.query(Permission).filter_by(name=perm_name).first()
                        if permission and permission not in role.permissions:
                            role.permissions.append(permission)
            
            session.commit()
            logger.info("Default permissions and roles seeded successfully")

def init_rbac(database_url: str):
    """Initialize RBAC system"""
    global rbac_manager
    rbac_manager = RBACManager(database_url)
    rbac_manager.seed_default_permissions()

def require_permission(permission: str, tenant_isolated: bool = True):
    """
    Decorator to enforce permission-based access control
    
    Args:
        permission: Required permission (e.g., 'vm:create', 'network:read')
        tenant_isolated: Whether to enforce tenant isolation
    
    Usage:
        @app.route('/api/vms', methods=['POST'])
        @require_permission('vm:create')
        @api_response
        def create_vm():
            pass
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                return {
                    "status": "error",
                    "message": "Authentication required",
                    "error": {"code": "AUTH_REQUIRED"}
                }, 401
            
            token = auth_header.split(' ')[1]
            user = rbac_manager.get_user_by_token(token)
            
            if not user:
                return {
                    "status": "error",
                    "message": "Invalid or expired token",
                    "error": {"code": "INVALID_TOKEN"}
                }, 401
            
            if not user.has_permission(permission):
                logger.warning(f"User {user.username} denied access to {permission}")
                return {
                    "status": "error",
                    "message": "Insufficient permissions",
                    "error": {
                        "code": "PERMISSION_DENIED", 
                        "required": permission,
                        "user_permissions": list(user.get_permissions())
                    }
                }, 403
            
            g.current_user = user
            
            if tenant_isolated:
                g.tenant_id = user.tenant_id
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator

def require_roles(*roles: str):
    """
    Decorator to require specific roles
    
    Args:
        roles: Required role names
    
    Usage:
        @app.route('/api/admin/users')
        @require_roles('admin', 'tenant_admin')
        @api_response
        def manage_users():
            pass
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'current_user') or not g.current_user:
                return {
                    "status": "error",
                    "message": "Authentication required",
                    "error": {"code": "AUTH_REQUIRED"}
                }, 401
            
            user_roles = {role.name for role in g.current_user.roles}
            required_roles = set(roles)
            
            if not required_roles.intersection(user_roles):
                return {
                    "status": "error",
                    "message": "Insufficient role privileges",
                    "error": {
                        "code": "ROLE_REQUIRED", 
                        "required": list(required_roles),
                        "user_roles": list(user_roles)
                    }
                }, 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator

def get_current_user():
    """Get current authenticated user from Flask g context"""
    return getattr(g, 'current_user', None)

def get_current_tenant_id():
    """Get current tenant ID from Flask g context"""
    return getattr(g, 'tenant_id', None)
