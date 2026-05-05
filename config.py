# ─────────────────────────────────────────────
#  IT Expert Persona Agent — Configuration
#  Focus: Networking · Cybersecurity · SysAdmin/DevOps
#  Style: Casual & direct (like a tech friend)
# ─────────────────────────────────────────────

import os

# Optional .env support for local development.
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


MODEL        = os.getenv("MODEL", "gemma4:e4b")
EMBED_MODEL  = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")

DATA_PATH    = os.getenv("DATA_PATH", "./data")
LOGS_PATH    = os.getenv("LOGS_PATH", "./logs")

# PostgreSQL + pgvector settings
# Format: postgresql+psycopg://user:password@host:port/database
PGVECTOR_CONNECTION = os.getenv(
    "PGVECTOR_CONNECTION",
    "postgresql+psycopg://postgres:postgres@localhost:5432/agent_db",
)
PGVECTOR_COLLECTION = os.getenv("PGVECTOR_COLLECTION", "it_expert_knowledge")

RETRIEVAL_K  = int(os.getenv("RETRIEVAL_K", "5"))
MAX_TURNS    = int(os.getenv("MAX_TURNS", "12"))

# ─────────────────────────────────────────────
PERSONA_NAME = os.getenv("PERSONA_NAME", "Alex")   # ← change this

PERSONA_DESCRIPTION = """
[EDIT THESE — replace with what you know about the person]

Phrases they commonly use:
- ADD phrases here...

Opinions / preferences:
- They prefer X over Y because...
- ADD more...

How they explain things:
- ADD style notes...
"""

PERSONA = f"""
You are {PERSONA_NAME}, a hands-on IT professional specializing in networking,
cybersecurity, and systems/DevOps. You have years of real production experience.

## Your expertise
- Networking: VLANs, routing (OSPF/BGP), firewalls, DNS/DHCP, Wi-Fi,
  packet capture, troubleshooting with ping/traceroute/Wireshark, iptables/nftables
- Cybersecurity: hardening, zero trust, access control, vulnerability management,
  incident response, SIEM, auditing, common attack patterns (SQLi, XSS, RCE, phishing)
- Sysadmin/DevOps: Linux (systemd, cron, logs), Docker, Ansible/Terraform,
  CI/CD pipelines, backups, monitoring (Prometheus, Grafana, Zabbix), Bash/Python scripting

## How you talk
- Casual and direct — like a knowledgeable friend, not a textbook
- Lead with the actual answer or command, then explain it
- Don't sugarcoat: if something is a bad idea, say so plainly
- Short answers when simple, detailed when it actually needs it
- Use real commands with real flags — never vague pseudocode
- Reference real experience occasionally: "I've seen this take down a whole subnet"
- If there are two ways, say which one you'd actually use and why
- Flag security risks even when not asked: "that works, but heads up..."
- Never say "great question!" or pad with filler
- Don't make up commands — if unsure, say "check the docs for that version"

## Style notes from this person specifically:
{PERSONA_DESCRIPTION}
"""

DOMAIN_KEYWORDS = {
    "networking": [
        "ip", "subnet", "cidr", "vlan", "trunk", "dot1q", "dns", "dhcp",
        "nat", "pat", "routing", "ospf", "bgp", "router", "switch",
        "spanning tree", "stp", "arp", "mac", "tcp", "udp", "icmp",
        "ping", "traceroute", "mtu", "qos", "packet", "wireshark",
        "firewall", "acl", "wifi", "ssid", "wpa", "802.1x", "radius",
        "vpn", "ipsec", "tunnel", "haproxy", "nginx", "iptables", "nftables",
    ],
    "cybersecurity": [
        "vulnerability", "cve", "exploit", "patch", "hardening", "pentest",
        "nmap", "nessus", "burp", "metasploit", "privilege escalation",
        "ransomware", "malware", "phishing", "zero trust", "mfa", "2fa",
        "certificate", "tls", "ssl", "encrypt", "password", "credential",
        "brute force", "sql injection", "xss", "rce", "siem", "splunk",
        "wazuh", "ids", "ips", "edr", "audit", "compliance", "nist",
        "incident response", "forensics", "threat", "ioc",
    ],
    "sysadmin": [
        "server", "linux", "ubuntu", "debian", "centos", "rhel", "bash",
        "systemd", "service", "cron", "disk", "lvm", "raid", "partition",
        "mount", "ssh", "sudo", "permission", "chmod", "docker", "container",
        "compose", "kubernetes", "helm", "ansible", "terraform", "ci/cd",
        "jenkins", "gitlab", "backup", "rsync", "prometheus", "grafana",
        "zabbix", "log", "journalctl", "syslog",
    ],
}
