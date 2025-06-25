"""
Unified API Response Envelope System
Enforces consistent response format across all endpoints
"""
from typing import Any, Dict, Optional, Union
from flask import jsonify
from functools import wraps
import traceback
import logging

logger = logging.getLogger(__name__)

class APIResponse:
    """Standardized API response envelope for all endpoints"""
    
    @staticmethod
    def success(data: Any = None, message: str = "Success", meta: Optional[Dict] = None) -> Dict:
        """Generate successful response envelope
        
        Args:
            data: Response payload data
            message: Success message
            meta: Additional metadata (pagination, etc.)
            
        Returns:
            Standardized success response dictionary
        """
        response = {
            "status": "success",
            "message": message,
            "data": data,
            "error": None
        }
        if meta:
            response["meta"] = meta
        return response
    
    @staticmethod
    def error(message: str, error_code: str = "GENERIC_ERROR", 
              details: Optional[Dict] = None, status_code: int = 400) -> Dict:
        """Generate error response envelope
        
        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            details: Additional error details
            status_code: HTTP status code
            
        Returns:
            Standardized error response dictionary
        """
        response = {
            "status": "error",
            "message": message,
            "data": None,
            "error": {
                "code": error_code,
                "details": details or {}
            }
        }
        return response
    
    @staticmethod
    def paginated(data: list, page: int, per_page: int, total: int, 
                  message: str = "Success") -> Dict:
        """Generate paginated response envelope
        
        Args:
            data: List of items for current page
            page: Current page number
            per_page: Items per page
            total: Total number of items
            message: Success message
            
        Returns:
            Standardized paginated response dictionary
        """
        return APIResponse.success(
            data=data,
            message=message,
            meta={
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "pages": (total + per_page - 1) // per_page,
                    "has_next": page * per_page < total,
                    "has_prev": page > 1
                }
            }
        )

def api_response(f):
    """
    Decorator to enforce unified API response envelope across all endpoints
    
    Automatically wraps endpoint responses in APIResponse format and handles exceptions
    with proper error responses and logging.
    
    Usage:
        @app.route('/api/endpoint')
        @api_response
        def my_endpoint():
            return {"key": "value"}  # Automatically wrapped in success envelope
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            
            if isinstance(result, tuple) and len(result) == 2:
                data, status_code = result
                if isinstance(data, dict) and "status" in data:
                    return jsonify(data), status_code
                else:
                    return jsonify(APIResponse.success(data)), status_code
            
            elif isinstance(result, dict) and "status" in result:
                return jsonify(result)
            
            else:
                return jsonify(APIResponse.success(result))
                
        except ValueError as e:
            logger.warning(f"Validation error in {f.__name__}: {str(e)}")
            return jsonify(APIResponse.error(
                message=str(e),
                error_code="VALIDATION_ERROR"
            )), 400
            
        except PermissionError as e:
            logger.warning(f"Permission denied in {f.__name__}: {str(e)}")
            return jsonify(APIResponse.error(
                message="Access denied",
                error_code="PERMISSION_DENIED"
            )), 403
            
        except FileNotFoundError as e:
            logger.warning(f"Resource not found in {f.__name__}: {str(e)}")
            return jsonify(APIResponse.error(
                message="Resource not found",
                error_code="NOT_FOUND"
            )), 404
            
        except ConnectionError as e:
            logger.error(f"Connection error in {f.__name__}: {str(e)}")
            return jsonify(APIResponse.error(
                message="Service temporarily unavailable",
                error_code="SERVICE_UNAVAILABLE"
            )), 503
            
        except Exception as e:
            logger.error(f"Unexpected error in {f.__name__}: {str(e)}")
            logger.error(traceback.format_exc())
            
            error_details = {}
            if logger.isEnabledFor(logging.DEBUG):
                error_details["trace_id"] = id(e)
                error_details["traceback"] = traceback.format_exc()
            
            return jsonify(APIResponse.error(
                message="Internal server error",
                error_code="INTERNAL_ERROR",
                details=error_details
            )), 500
    
    return decorated_function
