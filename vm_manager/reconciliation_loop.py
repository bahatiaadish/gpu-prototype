"""
VM Reconciliation Loop
60-second synchronization between libvirt and database with WebSocket reporting
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
import websockets
import json

logger = logging.getLogger(__name__)

class VMReconciliationLoop:
    """Manages VM state reconciliation between libvirt and database"""
    
    def __init__(self, libvirt_manager, redis_manager, websocket_port=8765):
        self.libvirt_manager = libvirt_manager
        self.redis_manager = redis_manager
        self.websocket_port = websocket_port
        self.running = False
        self.connected_clients = set()
        self.reconciliation_interval = 60
    
    async def start_reconciliation(self):
        """Start the reconciliation loop and WebSocket server"""
        self.running = True
        logger.info("Starting VM reconciliation loop")
        
        websocket_task = asyncio.create_task(self.start_websocket_server())
        reconciliation_task = asyncio.create_task(self.reconciliation_loop())
        
        await asyncio.gather(websocket_task, reconciliation_task)
    
    async def stop_reconciliation(self):
        """Stop the reconciliation loop"""
        self.running = False
        logger.info("Stopped VM reconciliation loop")
    
    async def start_websocket_server(self):
        """Start WebSocket server for real-time updates"""
        async def handle_client(websocket, path):
            self.connected_clients.add(websocket)
            logger.info(f"WebSocket client connected: {websocket.remote_address}")
            
            try:
                await websocket.send(json.dumps({
                    "type": "connection",
                    "message": "Connected to VM reconciliation service",
                    "timestamp": time.time()
                }))
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self.handle_websocket_message(websocket, data)
                    except json.JSONDecodeError:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Invalid JSON format",
                            "timestamp": time.time()
                        }))
                        
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"WebSocket client disconnected: {websocket.remote_address}")
            finally:
                self.connected_clients.discard(websocket)
        
        start_server = websockets.serve(handle_client, "localhost", self.websocket_port)
        logger.info(f"WebSocket server started on port {self.websocket_port}")
        await start_server
    
    async def handle_websocket_message(self, websocket, data):
        """Handle incoming WebSocket messages"""
        message_type = data.get("type")
        
        if message_type == "ping":
            await websocket.send(json.dumps({
                "type": "pong",
                "timestamp": time.time()
            }))
        
        elif message_type == "subscribe":
            subscription_types = data.get("types", [])
            await websocket.send(json.dumps({
                "type": "subscription_confirmed",
                "subscribed_types": subscription_types,
                "timestamp": time.time()
            }))
    
    async def reconciliation_loop(self):
        """Main reconciliation loop - runs every 60 seconds"""
        while self.running:
            try:
                start_time = time.time()
                
                libvirt_vms = self.libvirt_manager.list_active_vms()
                
                from database import db_session
                from database.models import VMInstance
                
                with db_session() as session:
                    db_vms = session.query(VMInstance).all()
                    
                    reconciliation_report = await self.reconcile_vm_states(libvirt_vms, db_vms)
                    
                    await self.broadcast_reconciliation_report(reconciliation_report)
                
                elapsed_time = time.time() - start_time
                logger.info(f"Reconciliation completed in {elapsed_time:.2f}s")
                
                await asyncio.sleep(max(0, self.reconciliation_interval - elapsed_time))
                
            except Exception as e:
                logger.error(f"Error in reconciliation loop: {e}")
                await asyncio.sleep(10)
    
    async def reconcile_vm_states(self, libvirt_vms: List[Dict], db_vms: List) -> Dict:
        """Compare libvirt and database VM states"""
        reconciliation_report = {
            "timestamp": time.time(),
            "libvirt_count": len(libvirt_vms),
            "database_count": len(db_vms),
            "discrepancies": [],
            "updates": []
        }
        
        libvirt_by_uuid = {vm["uuid"]: vm for vm in libvirt_vms}
        db_by_uuid = {vm.uuid: vm for vm in db_vms}
        
        for uuid, libvirt_vm in libvirt_by_uuid.items():
            db_vm = db_by_uuid.get(uuid)
            
            if not db_vm:
                reconciliation_report["discrepancies"].append({
                    "type": "vm_in_libvirt_not_in_db",
                    "uuid": uuid,
                    "name": libvirt_vm["name"]
                })
            elif db_vm.status != libvirt_vm["state"]:
                reconciliation_report["updates"].append({
                    "type": "status_update",
                    "uuid": uuid,
                    "old_status": db_vm.status,
                    "new_status": libvirt_vm["state"]
                })
        
        for uuid, db_vm in db_by_uuid.items():
            if uuid not in libvirt_by_uuid:
                reconciliation_report["discrepancies"].append({
                    "type": "vm_in_db_not_in_libvirt",
                    "uuid": uuid,
                    "name": db_vm.name
                })
        
        return reconciliation_report
    
    async def broadcast_reconciliation_report(self, report: Dict):
        """Broadcast reconciliation report to all connected WebSocket clients"""
        if not self.connected_clients:
            return
        
        message = json.dumps({
            "type": "reconciliation_report",
            "data": report
        })
        
        disconnected_clients = set()
        
        for client in self.connected_clients:
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected_clients.add(client)
        
        self.connected_clients -= disconnected_clients

async def start_reconciliation_loop(libvirt_manager, redis_manager, websocket_port=8765):
    """Start the VM reconciliation loop"""
    loop = VMReconciliationLoop(libvirt_manager, redis_manager, websocket_port)
    await loop.start_reconciliation()
