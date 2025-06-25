"""
API Endpoint Tests
Testing unified response envelopes and RBAC functionality
"""
import pytest
import json
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from api import APIResponse

@pytest.fixture
def client():
    """Test client fixture"""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_health_check(client):
    """Test health check endpoint returns proper API response format"""
    response = client.get('/api/health')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'data' in data
    assert 'services' in data['data']

def test_api_response_success():
    """Test APIResponse success format"""
    response = APIResponse.success({"key": "value"}, "Test message")
    
    assert response['status'] == 'success'
    assert response['message'] == 'Test message'
    assert response['data'] == {"key": "value"}
    assert response['error'] is None

def test_api_response_error():
    """Test APIResponse error format"""
    response = APIResponse.error("Test error", "TEST_ERROR", {"detail": "info"})
    
    assert response['status'] == 'error'
    assert response['message'] == 'Test error'
    assert response['data'] is None
    assert response['error']['code'] == 'TEST_ERROR'
    assert response['error']['details'] == {"detail": "info"}

def test_api_response_paginated():
    """Test APIResponse paginated format"""
    data = [{"id": 1}, {"id": 2}]
    response = APIResponse.paginated(data, 1, 10, 2)
    
    assert response['status'] == 'success'
    assert response['data'] == data
    assert 'meta' in response
    assert response['meta']['pagination']['page'] == 1
    assert response['meta']['pagination']['total'] == 2

def test_unauthorized_access(client):
    """Test unauthorized access returns proper error"""
    response = client.get('/api/vms')
    assert response.status_code == 401
    
    data = json.loads(response.data)
    assert data['status'] == 'error'
    assert data['error']['code'] == 'AUTH_REQUIRED'

def test_vm_creation_validation(client):
    """Test VM creation with invalid data"""
    with patch('api.rbac.rbac_manager') as mock_rbac:
        mock_user = Mock()
        mock_user.has_permission.return_value = True
        mock_rbac.get_user_by_token.return_value = mock_user
        
        response = client.post('/api/vms', 
                             headers={'Authorization': 'Bearer test-token'},
                             json={})
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['status'] == 'error'
        assert 'Missing required field' in data['message']

def test_not_found_endpoint(client):
    """Test 404 error handling"""
    response = client.get('/api/nonexistent')
    assert response.status_code == 404
    
    data = json.loads(response.data)
    assert data['status'] == 'error'
    assert data['error']['code'] == 'NOT_FOUND'

if __name__ == '__main__':
    pytest.main([__file__])
