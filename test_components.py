#!/usr/bin/env python3
"""
Component validation script for GPU Cloud Platform
Tests all major components without external dependencies
"""
import sys
import os

def test_imports():
    """Test all module imports"""
    print("Testing module imports...")
    
    try:
        from api import APIResponse, api_response
        from database.models import Base, User, VMInstance
        from vm_manager import LibvirtManager, VMSpec
        from network import OVSManager
        from messaging import RedisManager, MessageType
        from metrics import MetricsCollector
        print("✅ All imports successful")
        return True
    except Exception as e:
        print(f"❌ Import error: {e}")
        return False

def test_api_responses():
    """Test API response formats"""
    print("Testing API response formats...")
    
    try:
        from api import APIResponse
        
        success_resp = APIResponse.success({'test': 'data'}, 'Test message')
        error_resp = APIResponse.error('Test error', 'TEST_ERROR')
        paginated_resp = APIResponse.paginated([1, 2, 3], 1, 10, 3)
        
        assert success_resp['status'] == 'success'
        assert success_resp['data'] == {'test': 'data'}
        assert success_resp['error'] is None
        
        assert error_resp['status'] == 'error'
        assert error_resp['data'] is None
        assert error_resp['error']['code'] == 'TEST_ERROR'
        
        assert 'meta' in paginated_resp
        assert paginated_resp['meta']['pagination']['total'] == 3
        
        print("✅ API Response formats working correctly")
        return True
    except Exception as e:
        print(f"❌ API Response error: {e}")
        return False

def test_database_models():
    """Test database model definitions"""
    print("Testing database models...")
    
    try:
        from database.models import User, VMInstance, Tenant, Role, Permission
        
        assert hasattr(User, 'get_permissions')
        assert hasattr(User, 'has_permission')
        assert hasattr(VMInstance, 'tenant_id')
        assert hasattr(VMInstance, 'owner_id')
        
        print("✅ Database models defined correctly")
        return True
    except Exception as e:
        print(f"❌ Database model error: {e}")
        return False

def test_vm_spec():
    """Test VM specification creation"""
    print("Testing VM specification...")
    
    try:
        from vm_manager import VMSpec
        
        vm_spec = VMSpec(
            name='test-vm',
            memory_gb=8,
            vcpus=4,
            disk_size_gb=50,
            gpu_passthrough=True,
            cpu_pinning=True,
            hugepages=True
        )
        
        assert vm_spec.name == 'test-vm'
        assert vm_spec.memory_gb == 8
        assert vm_spec.gpu_passthrough == True
        assert vm_spec.cpu_pinning == True
        
        print("✅ VM specification working correctly")
        return True
    except Exception as e:
        print(f"❌ VM specification error: {e}")
        return False

def test_flask_app():
    """Test Flask application startup"""
    print("Testing Flask application...")
    
    os.environ['DATABASE_URL'] = 'sqlite:///test.db'
    os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
    
    try:
        from app import app
        
        with app.test_client() as client:
            response = client.get('/api/health')
            print(f"Health endpoint status: {response.status_code}")
            
            import json
            data = json.loads(response.data)
            
            assert 'status' in data
            assert 'data' in data
            assert data['status'] in ['success', 'error']
            
            response = client.get('/api/nonexistent')
            assert response.status_code == 404
            data = json.loads(response.data)
            assert data['status'] == 'error'
            
        print("✅ Flask application working correctly")
        return True
    except Exception as e:
        print(f"❌ Flask application error: {e}")
        return False

def main():
    """Run all component tests"""
    print("🚀 GPU Cloud Platform Component Validation")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_api_responses,
        test_database_models,
        test_vm_spec,
        test_flask_app
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All components validated successfully!")
        return 0
    else:
        print("❌ Some components failed validation")
        return 1

if __name__ == '__main__':
    sys.exit(main())
