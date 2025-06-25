"""
Redis Messaging and Task Queue System
Advanced pub/sub with Lua scripts for atomic operations
"""
import redis
import json
import logging
import asyncio
from typing import Dict, List, Optional, Callable, Any, Tuple
from enum import Enum
import time
import uuid

logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Message types for Redis pub/sub"""
    VM_CREATED = "vm_created"
    VM_STARTED = "vm_started"
    VM_STOPPED = "vm_stopped"
    VM_DELETED = "vm_deleted"
    VM_METRICS = "vm_metrics"
    NETWORK_CREATED = "network_created"
    NETWORK_DELETED = "network_deleted"
    RECONCILIATION_REPORT = "reconciliation_report"
    SYSTEM_ALERT = "system_alert"

class RedisManager:
    """Advanced Redis operations with pub/sub and task queues"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis_client = None
        self.pubsub = None
        self.subscribers = {}
        self.task_queue = "gpu_cloud_tasks"
        self.result_prefix = "task_result:"
        self.rate_limit_prefix = "rate_limit:"
        
        self._lua_scripts = {
            "atomic_increment": """
                local key = KEYS[1]
                local increment = tonumber(ARGV[1])
                local ttl = tonumber(ARGV[2])
                
                local current = redis.call('GET', key)
                if current == false then
                    current = 0
                else
                    current = tonumber(current)
                end
                
                local new_value = current + increment
                redis.call('SET', key, new_value)
                redis.call('EXPIRE', key, ttl)
                
                return new_value
            """,
            
            "rate_limit_check": """
                local key = KEYS[1]
                local limit = tonumber(ARGV[1])
                local window = tonumber(ARGV[2])
                local current_time = tonumber(ARGV[3])
                
                local window_start = current_time - window
                
                redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
                
                local current_count = redis.call('ZCARD', key)
                
                if current_count < limit then
                    redis.call('ZADD', key, current_time, current_time)
                    redis.call('EXPIRE', key, window)
                    return {1, limit - current_count - 1}
                else
                    return {0, 0}
                end
            """,
            
            "distributed_lock": """
                local key = KEYS[1]
                local identifier = ARGV[1]
                local ttl = tonumber(ARGV[2])
                
                if redis.call('SET', key, identifier, 'NX', 'EX', ttl) then
                    return 1
                else
                    return 0
                end
            """,
            
            "release_lock": """
                local key = KEYS[1]
                local identifier = ARGV[1]
                
                if redis.call('GET', key) == identifier then
                    return redis.call('DEL', key)
                else
                    return 0
                end
            """
        }
    
    def connect(self):
        """Establish Redis connection and load Lua scripts"""
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.redis_client.ping()
            
            self.loaded_scripts = {}
            for script_name, script_code in self._lua_scripts.items():
                self.loaded_scripts[script_name] = self.redis_client.register_script(script_code)
            
            logger.info("Connected to Redis and loaded Lua scripts")
            
        except redis.RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    def publish_message(self, message_type: MessageType, data: Dict, tenant_id: Optional[str] = None):
        """
        Publish message to Redis pub/sub channel
        
        Args:
            message_type: Type of message being published
            data: Message payload data
            tenant_id: Optional tenant ID for tenant-specific channels
        """
        try:
            channel = f"gpu_cloud:{message_type.value}"
            if tenant_id:
                channel = f"tenant:{tenant_id}:{message_type.value}"
            
            message = {
                "type": message_type.value,
                "data": data,
                "timestamp": time.time(),
                "message_id": str(uuid.uuid4())
            }
            
            if tenant_id:
                message["tenant_id"] = tenant_id
            
            self.redis_client.publish(channel, json.dumps(message))
            logger.debug(f"Published message to {channel}: {message_type.value}")
            
        except Exception as e:
            logger.error(f"Error publishing message {message_type.value}: {e}")
    
    def subscribe_to_messages(self, message_types: List[MessageType], 
                            callback: Callable, tenant_id: Optional[str] = None):
        """
        Subscribe to specific message types
        
        Args:
            message_types: List of message types to subscribe to
            callback: Function to call when message received
            tenant_id: Optional tenant ID for tenant-specific subscriptions
        """
        try:
            if not self.pubsub:
                self.pubsub = self.redis_client.pubsub()
            
            channels = []
            for msg_type in message_types:
                channel = f"gpu_cloud:{msg_type.value}"
                if tenant_id:
                    channel = f"tenant:{tenant_id}:{msg_type.value}"
                channels.append(channel)
            
            self.pubsub.subscribe(*channels)
            
            subscription_id = str(uuid.uuid4())
            self.subscribers[subscription_id] = {
                "channels": channels,
                "callback": callback,
                "tenant_id": tenant_id
            }
            
            logger.info(f"Subscribed to channels: {channels}")
            return subscription_id
            
        except Exception as e:
            logger.error(f"Error subscribing to messages: {e}")
            return None
    
    async def listen_for_messages(self):
        """Listen for incoming pub/sub messages"""
        if not self.pubsub:
            logger.warning("No active subscriptions")
            return
        
        try:
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        channel = message['channel']
                        
                        for sub_id, subscriber in self.subscribers.items():
                            if channel in subscriber['channels']:
                                try:
                                    await subscriber['callback'](data)
                                except Exception as e:
                                    logger.error(f"Error in message callback: {e}")
                    
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in message: {message['data']}")
                        
        except Exception as e:
            logger.error(f"Error listening for messages: {e}")
    
    def enqueue_task(self, task_type: str, task_data: Dict, priority: int = 0) -> str:
        """
        Add task to Redis task queue
        
        Args:
            task_type: Type of task to execute
            task_data: Task parameters and data
            priority: Task priority (higher = more priority)
            
        Returns:
            Task ID for tracking
        """
        try:
            task_id = str(uuid.uuid4())
            
            task = {
                "id": task_id,
                "type": task_type,
                "data": task_data,
                "created_at": time.time(),
                "priority": priority,
                "status": "queued"
            }
            
            self.redis_client.zadd(self.task_queue, {json.dumps(task): priority})
            logger.info(f"Enqueued task {task_id}: {task_type}")
            
            return task_id
            
        except Exception as e:
            logger.error(f"Error enqueuing task: {e}")
            return None
    
    def dequeue_task(self) -> Optional[Dict]:
        """
        Get next task from queue (highest priority first)
        
        Returns:
            Task dictionary or None if queue empty
        """
        try:
            result = self.redis_client.zpopmax(self.task_queue)
            
            if result:
                task_json, priority = result[0]
                task = json.loads(task_json)
                task["status"] = "processing"
                
                logger.info(f"Dequeued task {task['id']}: {task['type']}")
                return task
            
            return None
            
        except Exception as e:
            logger.error(f"Error dequeuing task: {e}")
            return None
    
    def set_task_result(self, task_id: str, result: Dict, ttl: int = 3600):
        """
        Store task execution result
        
        Args:
            task_id: Task identifier
            result: Task execution result
            ttl: Result TTL in seconds
        """
        try:
            result_key = f"{self.result_prefix}{task_id}"
            
            result_data = {
                "task_id": task_id,
                "result": result,
                "completed_at": time.time()
            }
            
            self.redis_client.setex(result_key, ttl, json.dumps(result_data))
            logger.debug(f"Stored result for task {task_id}")
            
        except Exception as e:
            logger.error(f"Error storing task result: {e}")
    
    def get_task_result(self, task_id: str) -> Optional[Dict]:
        """
        Retrieve task execution result
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task result or None if not found
        """
        try:
            result_key = f"{self.result_prefix}{task_id}"
            result_json = self.redis_client.get(result_key)
            
            if result_json:
                return json.loads(result_json)
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving task result: {e}")
            return None
    
    def check_rate_limit(self, identifier: str, limit: int, window: int) -> Tuple[bool, int]:
        """
        Check rate limit using sliding window
        
        Args:
            identifier: Unique identifier for rate limiting
            limit: Maximum requests allowed
            window: Time window in seconds
            
        Returns:
            Tuple of (allowed, remaining_requests)
        """
        try:
            key = f"{self.rate_limit_prefix}{identifier}"
            current_time = time.time()
            
            result = self.loaded_scripts["rate_limit_check"](
                keys=[key],
                args=[limit, window, current_time]
            )
            
            allowed = bool(result[0])
            remaining = int(result[1])
            
            return allowed, remaining
            
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return False, 0
    
    def acquire_distributed_lock(self, lock_name: str, ttl: int = 30) -> Optional[str]:
        """
        Acquire distributed lock
        
        Args:
            lock_name: Name of the lock
            ttl: Lock TTL in seconds
            
        Returns:
            Lock identifier if acquired, None otherwise
        """
        try:
            identifier = str(uuid.uuid4())
            key = f"lock:{lock_name}"
            
            result = self.loaded_scripts["distributed_lock"](
                keys=[key],
                args=[identifier, ttl]
            )
            
            if result:
                logger.debug(f"Acquired lock {lock_name}")
                return identifier
            
            return None
            
        except Exception as e:
            logger.error(f"Error acquiring lock {lock_name}: {e}")
            return None
    
    def release_distributed_lock(self, lock_name: str, identifier: str) -> bool:
        """
        Release distributed lock
        
        Args:
            lock_name: Name of the lock
            identifier: Lock identifier from acquisition
            
        Returns:
            True if released successfully, False otherwise
        """
        try:
            key = f"lock:{lock_name}"
            
            result = self.loaded_scripts["release_lock"](
                keys=[key],
                args=[identifier]
            )
            
            if result:
                logger.debug(f"Released lock {lock_name}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error releasing lock {lock_name}: {e}")
            return False
    
    def get_system_stats(self) -> Dict:
        """Get Redis system statistics"""
        try:
            info = self.redis_client.info()
            
            stats = {
                "connected_clients": info.get("connected_clients", 0),
                "used_memory": info.get("used_memory", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "pubsub_channels": info.get("pubsub_channels", 0),
                "pubsub_patterns": info.get("pubsub_patterns", 0)
            }
            
            queue_length = self.redis_client.zcard(self.task_queue)
            stats["task_queue_length"] = queue_length
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return {}
    
    def close(self):
        """Close Redis connections"""
        try:
            if self.pubsub:
                self.pubsub.close()
            
            if self.redis_client:
                self.redis_client.close()
            
            logger.info("Closed Redis connections")
            
        except Exception as e:
            logger.error(f"Error closing Redis connections: {e}")
