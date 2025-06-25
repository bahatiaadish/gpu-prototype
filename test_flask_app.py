#!/usr/bin/env python3
"""
Flask Application Test Script
Tests core Flask functionality without external dependencies
"""
import os
import sys

def test_flask_app():
    """Test Flask application startup and basic endpoints"""
    print("Testing Flask application...")
    
    os.environ['DATABASE_URL'] = 'sqlite:///test.db'
    os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
    os.environ['FLASK_DEBUG'] = 'false'
    
    try:
        from app import app
        
        with app.test_client() as client:
            print("Testing /api/health endpoint...")
            response = client.get('/api/health')
            print(f"Status Code: {response.status_code}")
            
            import json
            data = json.loads(response.data)
            print(f"Response Keys: {list(data.keys())}")
            print(f"Response Status: {data.get('status')}")
            print(f"Response Data: {data.get('data', {})}")
            
            assert 'status' in data
            print(f"Available keys: {list(data.keys())}")
            
            assert data['status'] in ['success', 'error', 'degraded']
            
            print("\nTesting 404 error handling...")
            response = client.get('/api/nonexistent')
            assert response.status_code == 404
            data = json.loads(response.data)
            assert data['status'] == 'error'
            print("404 handling works correctly")
            
            print("\nTesting API response format consistency...")
            health_data = json.loads(client.get('/api/health').data)
            error_data = json.loads(client.get('/api/nonexistent').data)
            
            assert set(health_data.keys()) == set(error_data.keys())
            print("API response format is consistent")
            
        print("✅ Flask application test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Flask application test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run Flask application tests"""
    print("🚀 Flask Application Testing")
    print("=" * 40)
    
    if test_flask_app():
        print("\n🎉 Flask application is working correctly!")
        return 0
    else:
        print("\n❌ Flask application has issues")
        return 1

if __name__ == '__main__':
    sys.exit(main())
