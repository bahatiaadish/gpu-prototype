"""
GPU Cloud Platform API Module
Unified response envelopes and RBAC decorators
"""
from .response_envelope import APIResponse, api_response
from .rbac import require_permission, require_roles, init_rbac

__all__ = ['APIResponse', 'api_response', 'require_permission', 'require_roles', 'init_rbac']
