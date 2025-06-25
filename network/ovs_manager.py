"""
Open vSwitch Flow Management
Dynamic flow rule generation with interface UUID resolution and tenant isolation
"""
import subprocess
import json
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)

@dataclass
class FlowRule:
    """Represents an OVS flow rule"""
    table: int
    priority: int
    match: str
    actions: str
    cookie: Optional[str] = None

class OVSManager:
    """Advanced Open vSwitch flow management with dynamic table allocation"""
    
    def __init__(self, bridge_name: str = "br-tenant"):
        self.bridge_name = bridge_name
        self.interface_cache = {}
        self.cache_ttl = 300
        self.table_allocation = {
            "ingress": 0,
            "tenant_isolation": 10,
            "security_groups": 20,
            "forwarding": 30,
            "egress": 40
        }
    
    def get_interface_uuid(self, interface_name: str, retry_count: int = 3) -> Optional[str]:
        """
        Resolve interface UUID from interface name with caching and retry logic
        
        Args:
            interface_name: Name of the network interface
            retry_count: Number of retry attempts
            
        Returns:
            Interface UUID or None if resolution fails
        """
        cache_key = interface_name
        current_time = time.time()
        
        if cache_key in self.interface_cache:
            cached_uuid, timestamp = self.interface_cache[cache_key]
            if current_time - timestamp < self.cache_ttl:
                return cached_uuid
        
        for attempt in range(retry_count):
            try:
                cmd = ["ovs-vsctl", "--format=json", "list", "Interface", interface_name]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if data.get("data") and len(data["data"]) > 0:
                        interface_data = data["data"][0]
                        uuid_index = data["headings"].index("_uuid")
                        interface_uuid = interface_data[uuid_index][1]
                        
                        self.interface_cache[cache_key] = (interface_uuid, current_time)
                        logger.info(f"Resolved interface {interface_name} to UUID {interface_uuid}")
                        return interface_uuid
                
                logger.warning(f"Attempt {attempt + 1}: Failed to resolve interface {interface_name}")
                time.sleep(1)
                
            except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
                logger.error(f"Error resolving interface UUID for {interface_name}: {e}")
                time.sleep(1)
        
        logger.error(f"Failed to resolve interface UUID for {interface_name} after {retry_count} attempts")
        return None
    
    def generate_tenant_isolation_flows(self, tenant_id: str, vlan_id: int) -> List[FlowRule]:
        """
        Generate flow rules for tenant isolation using VLAN tagging
        
        Args:
            tenant_id: Unique tenant identifier
            vlan_id: VLAN ID for tenant isolation
            
        Returns:
            List of flow rules for tenant isolation
        """
        flows = []
        table = self.table_allocation["tenant_isolation"]
        cookie = f"tenant:{tenant_id}"
        
        flows.append(FlowRule(
            table=table,
            priority=1000,
            match=f"dl_vlan={vlan_id}",
            actions=f"resubmit(,{self.table_allocation['security_groups']})",
            cookie=cookie
        ))
        
        flows.append(FlowRule(
            table=table,
            priority=500,
            match=f"in_port=LOCAL,dl_vlan={vlan_id}",
            actions=f"resubmit(,{self.table_allocation['forwarding']})",
            cookie=cookie
        ))
        
        flows.append(FlowRule(
            table=table,
            priority=100,
            match=f"dl_vlan={vlan_id}",
            actions="drop",
            cookie=cookie
        ))
        
        return flows
    
    def generate_security_group_flows(self, tenant_id: str, security_rules: List[Dict]) -> List[FlowRule]:
        """
        Generate security group flow rules for network access control
        
        Args:
            tenant_id: Tenant identifier
            security_rules: List of security rule dictionaries
            
        Returns:
            List of security group flow rules
        """
        flows = []
        table = self.table_allocation["security_groups"]
        cookie = f"security:{tenant_id}"
        
        for rule in security_rules:
            protocol = rule.get("protocol", "tcp")
            port_range = rule.get("port_range", "any")
            source_cidr = rule.get("source_cidr", "0.0.0.0/0")
            action = rule.get("action", "allow")
            
            if action == "allow":
                match_conditions = []
                
                if protocol != "any":
                    if protocol == "tcp":
                        match_conditions.append("tcp")
                    elif protocol == "udp":
                        match_conditions.append("udp")
                    elif protocol == "icmp":
                        match_conditions.append("icmp")
                
                if port_range != "any" and protocol in ["tcp", "udp"]:
                    if "-" in str(port_range):
                        start_port, end_port = map(int, str(port_range).split("-"))
                        match_conditions.append(f"tp_dst={start_port}..{end_port}")
                    else:
                        match_conditions.append(f"tp_dst={port_range}")
                
                if source_cidr != "0.0.0.0/0":
                    match_conditions.append(f"nw_src={source_cidr}")
                
                match_str = ",".join(match_conditions) if match_conditions else "ip"
                
                flows.append(FlowRule(
                    table=table,
                    priority=1000,
                    match=match_str,
                    actions=f"resubmit(,{self.table_allocation['forwarding']})",
                    cookie=cookie
                ))
        
        flows.append(FlowRule(
            table=table,
            priority=1,
            match="ip",
            actions="drop",
            cookie=cookie
        ))
        
        return flows
    
    def generate_forwarding_flows(self, tenant_id: str, vm_interfaces: List[Dict]) -> List[FlowRule]:
        """
        Generate forwarding flow rules for VM communication
        
        Args:
            tenant_id: Tenant identifier
            vm_interfaces: List of VM interface configurations
            
        Returns:
            List of forwarding flow rules
        """
        flows = []
        table = self.table_allocation["forwarding"]
        cookie = f"forwarding:{tenant_id}"
        
        for interface in vm_interfaces:
            vm_mac = interface.get("mac_address")
            vm_ip = interface.get("ip_address")
            port_name = interface.get("port_name")
            
            if not all([vm_mac, vm_ip, port_name]):
                continue
            
            interface_uuid = self.get_interface_uuid(port_name)
            if not interface_uuid:
                logger.warning(f"Could not resolve UUID for interface {port_name}")
                continue
            
            flows.append(FlowRule(
                table=table,
                priority=1000,
                match=f"dl_dst={vm_mac}",
                actions=f"output:{interface_uuid}",
                cookie=cookie
            ))
            
            flows.append(FlowRule(
                table=table,
                priority=1000,
                match=f"nw_dst={vm_ip}",
                actions=f"mod_dl_dst:{vm_mac},output:{interface_uuid}",
                cookie=cookie
            ))
        
        flows.append(FlowRule(
            table=table,
            priority=500,
            match="arp",
            actions="flood",
            cookie=cookie
        ))
        
        return flows
    
    def install_flows(self, flows: List[FlowRule]) -> bool:
        """
        Install flow rules on the OVS bridge
        
        Args:
            flows: List of flow rules to install
            
        Returns:
            True if all flows installed successfully, False otherwise
        """
        success_count = 0
        
        for flow in flows:
            try:
                flow_spec = f"table={flow.table},priority={flow.priority},{flow.match},actions={flow.actions}"
                
                if flow.cookie:
                    flow_spec = f"cookie={flow.cookie},{flow_spec}"
                
                cmd = ["ovs-ofctl", "add-flow", self.bridge_name, flow_spec]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    success_count += 1
                    logger.debug(f"Installed flow: {flow_spec}")
                else:
                    logger.error(f"Failed to install flow: {flow_spec}, error: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                logger.error(f"Timeout installing flow: {flow}")
            except Exception as e:
                logger.error(f"Error installing flow {flow}: {e}")
        
        logger.info(f"Installed {success_count}/{len(flows)} flows successfully")
        return success_count == len(flows)
    
    def remove_flows_by_cookie(self, cookie: str) -> bool:
        """
        Remove flows by cookie value
        
        Args:
            cookie: Cookie value to match for flow removal
            
        Returns:
            True if removal successful, False otherwise
        """
        try:
            cmd = ["ovs-ofctl", "del-flows", self.bridge_name, f"cookie={cookie}/-1"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info(f"Removed flows with cookie: {cookie}")
                return True
            else:
                logger.error(f"Failed to remove flows with cookie {cookie}: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error removing flows with cookie {cookie}: {e}")
            return False
    
    def debug_flows(self, table: Optional[int] = None) -> Dict:
        """
        Debug utility to dump and analyze flow rules
        
        Args:
            table: Specific table to debug (optional)
            
        Returns:
            Dictionary containing flow analysis
        """
        try:
            cmd = ["ovs-ofctl", "dump-flows", self.bridge_name]
            if table is not None:
                cmd.append(f"table={table}")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return {"error": f"Failed to dump flows: {result.stderr}"}
            
            flows_output = result.stdout.strip().split('\n')[1:]
            
            flow_analysis = {
                "total_flows": len(flows_output),
                "flows_by_table": {},
                "flows_by_cookie": {},
                "flows": []
            }
            
            for flow_line in flows_output:
                flow_match = re.search(r'table=(\d+).*cookie=(0x[0-9a-fA-F]+)', flow_line)
                if flow_match:
                    table_num = int(flow_match.group(1))
                    cookie = flow_match.group(2)
                    
                    flow_analysis["flows_by_table"][table_num] = flow_analysis["flows_by_table"].get(table_num, 0) + 1
                    flow_analysis["flows_by_cookie"][cookie] = flow_analysis["flows_by_cookie"].get(cookie, 0) + 1
                
                flow_analysis["flows"].append(flow_line.strip())
            
            return flow_analysis
            
        except Exception as e:
            logger.error(f"Error debugging flows: {e}")
            return {"error": str(e)}
    
    def setup_tenant_network(self, tenant_id: str, vlan_id: int, 
                           security_rules: List[Dict], vm_interfaces: List[Dict]) -> bool:
        """
        Complete tenant network setup with isolation, security, and forwarding
        
        Args:
            tenant_id: Unique tenant identifier
            vlan_id: VLAN ID for tenant isolation
            security_rules: Security group rules
            vm_interfaces: VM network interface configurations
            
        Returns:
            True if setup successful, False otherwise
        """
        try:
            all_flows = []
            
            all_flows.extend(self.generate_tenant_isolation_flows(tenant_id, vlan_id))
            all_flows.extend(self.generate_security_group_flows(tenant_id, security_rules))
            all_flows.extend(self.generate_forwarding_flows(tenant_id, vm_interfaces))
            
            success = self.install_flows(all_flows)
            
            if success:
                logger.info(f"Successfully set up network for tenant {tenant_id}")
            else:
                logger.error(f"Failed to set up network for tenant {tenant_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error setting up tenant network for {tenant_id}: {e}")
            return False
    
    def cleanup_tenant_network(self, tenant_id: str) -> bool:
        """
        Clean up all flows for a tenant
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            True if cleanup successful, False otherwise
        """
        cookies_to_remove = [
            f"tenant:{tenant_id}",
            f"security:{tenant_id}",
            f"forwarding:{tenant_id}"
        ]
        
        success = True
        for cookie in cookies_to_remove:
            if not self.remove_flows_by_cookie(cookie):
                success = False
        
        if success:
            logger.info(f"Successfully cleaned up network for tenant {tenant_id}")
        else:
            logger.error(f"Failed to clean up network for tenant {tenant_id}")
        
        return success
