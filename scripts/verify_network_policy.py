#!/usr/bin/env python3
"""Empirical Kubernetes NetworkPolicy Simulator and Manifest Challenge Harness.

Parses rendered manifests from `kubectl kustomize k8s/overlays/prod`,
`kubectl kustomize k8s/overlays/dev`, and `kubectl kustomize k8s/base`.
Simulates Kubernetes NetworkPolicy ingress/egress evaluation semantics.
Verifies all required allowed, blocked, and edge-case paths.
Checks CoreDNS egress rules against selector corruption and label pollution.
"""

from __future__ import annotations

import ipaddress
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class NetworkEndpoint:
    name: str
    namespace: str
    labels: dict[str, str] = field(default_factory=dict)
    ip: str | None = None
    namespace_labels: dict[str, str] = field(default_factory=dict)

    def matches_pod_selector(self, target_ns: str, selector: dict[str, Any]) -> bool:
        if self.namespace != target_ns:
            return False
        match_labels = selector.get("matchLabels", {})
        for k, v in match_labels.items():
            if self.labels.get(k) != str(v):
                return False
        return True

    def matches_namespace_selector(self, selector: dict[str, Any]) -> bool:
        match_labels = selector.get("matchLabels", {})
        for k, v in match_labels.items():
            if self.namespace_labels.get(k) != str(v):
                return False
        return True

    def matches_ip_block(self, ip_block: dict[str, Any]) -> bool:
        if not self.ip:
            return False
        try:
            target_ip = ipaddress.ip_address(self.ip)
            cidr = ipaddress.ip_network(ip_block["cidr"])
            if target_ip not in cidr:
                return False
            for exc in ip_block.get("except", []):
                exc_net = ipaddress.ip_network(exc)
                if target_ip in exc_net:
                    return False
            return True
        except ValueError:
            return False


def _port_matches(
    rule_ports: list[dict[str, Any]] | None, port: int, protocol: str
) -> bool:
    if not rule_ports:
        # Empty/omitted ports means all ports & protocols
        return True
    for p in rule_ports:
        proto = p.get("protocol", "TCP").upper()
        p_num = p.get("port")
        if proto == protocol.upper() and (p_num is None or int(p_num) == port):
            return True
    return False


def _peer_matches_egress(
    policy_ns: str, peer: dict[str, Any], dest: NetworkEndpoint
) -> bool:
    has_pod_sel = "podSelector" in peer
    has_ns_sel = "namespaceSelector" in peer
    has_ip_block = "ipBlock" in peer

    if has_ip_block:
        return dest.matches_ip_block(peer["ipBlock"])

    if has_pod_sel and has_ns_sel:
        # AND condition
        return dest.matches_namespace_selector(
            peer["namespaceSelector"]
        ) and dest.matches_pod_selector(dest.namespace, peer["podSelector"])

    if has_ns_sel:
        return dest.matches_namespace_selector(peer["namespaceSelector"])

    if has_pod_sel:
        return dest.matches_pod_selector(policy_ns, peer["podSelector"])

    # Empty peer selector matches everything
    return True


def _peer_matches_ingress(
    policy_ns: str, peer: dict[str, Any], src: NetworkEndpoint
) -> bool:
    has_pod_sel = "podSelector" in peer
    has_ns_sel = "namespaceSelector" in peer
    has_ip_block = "ipBlock" in peer

    if has_ip_block:
        return src.matches_ip_block(peer["ipBlock"])

    if has_pod_sel and has_ns_sel:
        # AND condition
        return src.matches_namespace_selector(
            peer["namespaceSelector"]
        ) and src.matches_pod_selector(src.namespace, peer["podSelector"])

    if has_ns_sel:
        return src.matches_namespace_selector(peer["namespaceSelector"])

    if has_pod_sel:
        return src.matches_pod_selector(policy_ns, peer["podSelector"])

    return True


class NetworkPolicySimulator:
    def __init__(self, manifests: list[dict[str, Any]], overlay_name: str):
        self.overlay_name = overlay_name
        self.manifests = manifests
        self.policies: list[dict[str, Any]] = [
            m for m in manifests if m and m.get("kind") == "NetworkPolicy"
        ]
        self.workloads = self._extract_workloads()

    def _extract_workloads(self) -> dict[str, NetworkEndpoint]:
        endpoints: dict[str, NetworkEndpoint] = {}
        for m in self.manifests:
            if not m:
                continue
            kind = m.get("kind")
            metadata = m.get("metadata", {})
            name = metadata.get("name")
            ns = metadata.get("namespace", "rahbar")

            labels = {}
            if kind in ("Deployment", "StatefulSet", "Job"):
                labels = (
                    m.get("spec", {})
                    .get("template", {})
                    .get("metadata", {})
                    .get("labels", {})
                )
            elif kind == "CronJob":
                labels = (
                    m.get("spec", {})
                    .get("jobTemplate", {})
                    .get("spec", {})
                    .get("template", {})
                    .get("metadata", {})
                    .get("labels", {})
                )

            if labels and "app" in labels:
                app_name = labels["app"]
                if app_name not in endpoints:
                    endpoints[app_name] = NetworkEndpoint(
                        name=name,
                        namespace=ns,
                        labels=labels,
                        namespace_labels={
                            "name": ns,
                            "kubernetes.io/metadata.name": ns,
                        },
                    )

        # Standard external/infrastructure endpoints
        endpoints["ingress-nginx"] = NetworkEndpoint(
            name="ingress-controller",
            namespace="ingress-nginx",
            labels={"app.kubernetes.io/name": "ingress-nginx"},
            namespace_labels={
                "name": "ingress-nginx",
                "kubernetes.io/metadata.name": "ingress-nginx",
            },
        )
        endpoints["coredns"] = NetworkEndpoint(
            name="coredns",
            namespace="kube-system",
            labels={"k8s-app": "kube-dns"},
            namespace_labels={
                "name": "kube-system",
                "kubernetes.io/metadata.name": "kube-system",
            },
        )
        endpoints["ollama-host"] = NetworkEndpoint(
            name="ollama-host",
            namespace="host",
            ip="192.168.49.1",
        )
        endpoints["external-ip"] = NetworkEndpoint(
            name="external-internet",
            namespace="external",
            ip="8.8.8.8",
        )
        endpoints["rogue-rahbar-pod"] = NetworkEndpoint(
            name="rogue-pod",
            namespace="rahbar",
            labels={"app": "rogue", "app.kubernetes.io/part-of": "rahbar"},
            namespace_labels={
                "name": "rahbar",
                "kubernetes.io/metadata.name": "rahbar",
            },
        )
        endpoints["foreign-ns-pod"] = NetworkEndpoint(
            name="foreign-pod",
            namespace="untrusted-namespace",
            labels={"app": "attacker"},
            namespace_labels={
                "name": "untrusted-namespace",
                "kubernetes.io/metadata.name": "untrusted-namespace",
            },
        )
        return endpoints

    def is_pod_egress_isolated(self, pod: NetworkEndpoint) -> bool:
        if pod.namespace != "rahbar":
            return False
        for p in self.policies:
            policy_ns = p.get("metadata", {}).get("namespace", "rahbar")
            if policy_ns != pod.namespace:
                continue
            selector = p.get("spec", {}).get("podSelector", {})
            if pod.matches_pod_selector(policy_ns, selector):
                ptypes = p.get("spec", {}).get("policyTypes", [])
                if "Egress" in ptypes or ("egress" in p.get("spec", {}) and not ptypes):
                    return True
        return False

    def is_pod_ingress_isolated(self, pod: NetworkEndpoint) -> bool:
        if pod.namespace != "rahbar":
            return False
        for p in self.policies:
            policy_ns = p.get("metadata", {}).get("namespace", "rahbar")
            if policy_ns != pod.namespace:
                continue
            selector = p.get("spec", {}).get("podSelector", {})
            if pod.matches_pod_selector(policy_ns, selector):
                ptypes = p.get("spec", {}).get("policyTypes", [])
                if "Ingress" in ptypes or (
                    "ingress" in p.get("spec", {}) and not ptypes
                ):
                    return True
        return False

    def is_egress_allowed(
        self, src: NetworkEndpoint, dest: NetworkEndpoint, port: int, protocol: str
    ) -> tuple[bool, list[str]]:
        if not self.is_pod_egress_isolated(src):
            return True, ["non-isolated-egress"]

        matching_policies = []
        for p in self.policies:
            policy_ns = p.get("metadata", {}).get("namespace", "rahbar")
            if policy_ns != src.namespace:
                continue
            selector = p.get("spec", {}).get("podSelector", {})
            if not src.matches_pod_selector(policy_ns, selector):
                continue
            # Policy selects src
            egress_rules = p.get("spec", {}).get("egress", [])
            for rule in egress_rules:
                if not _port_matches(rule.get("ports"), port, protocol):
                    continue
                to_peers = rule.get("to")
                if not to_peers:
                    # Allowed to all
                    matching_policies.append(p["metadata"]["name"])
                    break
                for peer in to_peers:
                    if _peer_matches_egress(policy_ns, peer, dest):
                        matching_policies.append(p["metadata"]["name"])
                        break
        return len(matching_policies) > 0, matching_policies

    def is_ingress_allowed(
        self, src: NetworkEndpoint, dest: NetworkEndpoint, port: int, protocol: str
    ) -> tuple[bool, list[str]]:
        if not self.is_pod_ingress_isolated(dest):
            return True, ["non-isolated-ingress"]

        matching_policies = []
        for p in self.policies:
            policy_ns = p.get("metadata", {}).get("namespace", "rahbar")
            if policy_ns != dest.namespace:
                continue
            selector = p.get("spec", {}).get("podSelector", {})
            if not dest.matches_pod_selector(policy_ns, selector):
                continue
            # Policy selects dest
            ingress_rules = p.get("spec", {}).get("ingress", [])
            for rule in ingress_rules:
                if not _port_matches(rule.get("ports"), port, protocol):
                    continue
                from_peers = rule.get("from")
                if not from_peers:
                    # Allowed from all
                    matching_policies.append(p["metadata"]["name"])
                    break
                for peer in from_peers:
                    if _peer_matches_ingress(policy_ns, peer, src):
                        matching_policies.append(p["metadata"]["name"])
                        break
        return len(matching_policies) > 0, matching_policies

    def simulate_connection(
        self, src_key: str, dest_key: str, port: int, protocol: str = "TCP"
    ) -> dict[str, Any]:
        src = self.workloads[src_key]
        dest = self.workloads[dest_key]

        eg_allowed, eg_pols = self.is_egress_allowed(src, dest, port, protocol)
        in_allowed, in_pols = self.is_ingress_allowed(src, dest, port, protocol)

        return {
            "source": src_key,
            "destination": dest_key,
            "port": port,
            "protocol": protocol,
            "allowed": eg_allowed and in_allowed,
            "egress_allowed": eg_allowed,
            "egress_policies": eg_pols,
            "ingress_allowed": in_allowed,
            "ingress_policies": in_pols,
        }

    def check_dns_egress_rules(self) -> list[str]:
        """Verify that CoreDNS egress rules are clean and impervious to selector trap."""
        issues = []
        for p in self.policies:
            p_name = p["metadata"]["name"]
            egress = p.get("spec", {}).get("egress", [])
            for rule_idx, rule in enumerate(egress):
                to_peers = rule.get("to", [])
                for peer_idx, peer in enumerate(to_peers):
                    ns_sel = peer.get("namespaceSelector", {})
                    ns_labels = ns_sel.get("matchLabels", {})
                    if ns_labels.get("kubernetes.io/metadata.name") == "kube-system":
                        # This is a DNS egress rule!
                        if "podSelector" in peer:
                            issues.append(
                                f"{p_name}: egress[{rule_idx}].to[{peer_idx}] has unexpected podSelector in kube-system egress"
                            )
                        # Check for label pollution
                        peer_str = str(peer)
                        if "env:" in peer_str or "'env':" in peer_str:
                            issues.append(
                                f"{p_name}: egress[{rule_idx}].to[{peer_idx}] has polluted 'env' label: {peer_str}"
                            )
                        # Check ports
                        ports = rule.get("ports", [])
                        port_protos = {
                            (p.get("port"), p.get("protocol", "TCP").upper())
                            for p in ports
                        }
                        if (53, "UDP") not in port_protos or (
                            53,
                            "TCP",
                        ) not in port_protos:
                            issues.append(
                                f"{p_name}: egress[{rule_idx}] missing UDP/TCP 53 ports (has {port_protos})"
                            )
        return issues


def render_overlay(overlay_path: str) -> tuple[list[dict[str, Any]], str]:
    res = subprocess.run(
        ["kubectl", "kustomize", overlay_path],
        capture_output=True,
        text=True,
        check=True,
    )
    docs = list(yaml.safe_load_all(res.stdout))
    return docs, res.stderr


def run_full_suite() -> bool:
    all_passed = True
    print("=" * 80)
    print("RAHBAR NetworkPolicy Empirical Simulator & Manifest Challenge Suite")
    print("=" * 80)

    for overlay_rel in ["k8s/overlays/dev", "k8s/overlays/prod", "k8s/base"]:
        print(f"\n[TARGET OVERLAY]: {overlay_rel}")
        docs, stderr = render_overlay(overlay_rel)
        if stderr.strip():
            print(f"  [FAIL] Unexpected stderr/warnings in {overlay_rel}:\n{stderr}")
            all_passed = False
        else:
            print("  [PASS] Clean render (0 stderr warnings)")

        sim = NetworkPolicySimulator(docs, overlay_rel)

        # 1. DNS Egress Audit
        dns_issues = sim.check_dns_egress_rules()
        if dns_issues:
            print("  [FAIL] DNS Egress rule issues detected:")
            for issue in dns_issues:
                print(f"    - {issue}")
            all_passed = False
        else:
            print(
                "  [PASS] CoreDNS egress rules clean (no podSelector, no env pollution, UDP+TCP 53 verified)"
            )

        # 2. Required Allowed Paths Matrix
        allowed_test_cases = [
            ("api", "chroma", 8000, "TCP", "API -> Chroma (vector query)"),
            ("api", "redis", 6379, "TCP", "API -> Redis (cache check & write)"),
            ("indexer", "chroma", 8000, "TCP", "Indexer -> Chroma (store vectors)"),
            ("indexer", "redis", 6379, "TCP", "Indexer -> Redis (cache invalidation)"),
            ("ingress-nginx", "ui", 8080, "TCP", "Ingress -> UI (frontend proxy)"),
            ("ingress-nginx", "api", 8000, "TCP", "Ingress -> API (api proxy)"),
            ("ui", "api", 8000, "TCP", "UI -> API (client query)"),
            ("ui", "coredns", 53, "UDP", "UI -> CoreDNS (UDP)"),
            ("ui", "coredns", 53, "TCP", "UI -> CoreDNS (TCP)"),
            ("api", "coredns", 53, "UDP", "API -> CoreDNS (UDP)"),
            ("api", "coredns", 53, "TCP", "API -> CoreDNS (TCP)"),
            ("chroma", "coredns", 53, "UDP", "Chroma -> CoreDNS (UDP)"),
            ("chroma", "coredns", 53, "TCP", "Chroma -> CoreDNS (TCP)"),
            ("redis", "coredns", 53, "UDP", "Redis -> CoreDNS (UDP)"),
            ("redis", "coredns", 53, "TCP", "Redis -> CoreDNS (TCP)"),
            ("indexer", "coredns", 53, "UDP", "Indexer -> CoreDNS (UDP)"),
            ("indexer", "coredns", 53, "TCP", "Indexer -> CoreDNS (TCP)"),
            ("api", "ollama-host", 11434, "TCP", "API -> Ollama Host (generation)"),
            (
                "indexer",
                "ollama-host",
                11434,
                "TCP",
                "Indexer -> Ollama Host (embedding)",
            ),
        ]

        print("  --- Allowed Paths Verification ---")
        for src, dst, port, proto, desc in allowed_test_cases:
            res = sim.simulate_connection(src, dst, port, proto)
            if not res["allowed"]:
                print(
                    f"  [FAIL] {desc} should be ALLOWED but was BLOCKED! Egress: {res['egress_allowed']}, Ingress: {res['ingress_allowed']}"
                )
                all_passed = False
            else:
                print(
                    f"  [PASS] {desc} -> ALLOWED (egress={res['egress_policies']}, ingress={res['ingress_policies']})"
                )

        # 3. Unauthorized Paths Matrix (MUST BE REJECTED)
        blocked_test_cases = [
            ("ui", "chroma", 8000, "TCP", "UI -> Chroma (unauthorized vector access)"),
            ("ui", "redis", 6379, "TCP", "UI -> Redis (unauthorized cache access)"),
            ("external-ip", "chroma", 8000, "TCP", "External -> Chroma"),
            ("external-ip", "redis", 6379, "TCP", "External -> Redis"),
            (
                "external-ip",
                "api",
                8000,
                "TCP",
                "External -> API (direct bypass of Ingress)",
            ),
            (
                "external-ip",
                "ui",
                8080,
                "TCP",
                "External -> UI (direct bypass of Ingress)",
            ),
            ("ingress-nginx", "chroma", 8000, "TCP", "Ingress -> Chroma (bypass API)"),
            ("ingress-nginx", "redis", 6379, "TCP", "Ingress -> Redis (bypass API)"),
            ("chroma", "redis", 6379, "TCP", "Chroma -> Redis (lateral movement)"),
            ("redis", "chroma", 8000, "TCP", "Redis -> Chroma (lateral movement)"),
            ("chroma", "api", 8000, "TCP", "Chroma -> API"),
            ("redis", "api", 8000, "TCP", "Redis -> API"),
            ("chroma", "ollama-host", 11434, "TCP", "Chroma -> Ollama Host"),
            ("redis", "ollama-host", 11434, "TCP", "Redis -> Ollama Host"),
            ("ui", "ollama-host", 11434, "TCP", "UI -> Ollama Host"),
            ("chroma", "external-ip", 443, "TCP", "Chroma -> External Internet"),
            ("redis", "external-ip", 443, "TCP", "Redis -> External Internet"),
            (
                "api",
                "external-ip",
                443,
                "TCP",
                "API -> External Internet (default-deny egress)",
            ),
            ("indexer", "external-ip", 443, "TCP", "Indexer -> External Internet"),
            ("rogue-rahbar-pod", "chroma", 8000, "TCP", "Rogue rahbar pod -> Chroma"),
            ("rogue-rahbar-pod", "redis", 6379, "TCP", "Rogue rahbar pod -> Redis"),
            ("rogue-rahbar-pod", "api", 8000, "TCP", "Rogue rahbar pod -> API"),
            (
                "foreign-ns-pod",
                "chroma",
                8000,
                "TCP",
                "Foreign namespace pod -> Chroma",
            ),
            ("foreign-ns-pod", "redis", 6379, "TCP", "Foreign namespace pod -> Redis"),
            ("foreign-ns-pod", "api", 8000, "TCP", "Foreign namespace pod -> API"),
            ("api", "rogue-rahbar-pod", 8080, "TCP", "API -> Rogue rahbar pod"),
            ("indexer", "ui", 8080, "TCP", "Indexer -> UI"),
        ]

        print("  --- Blocked Paths Verification (Default-Deny) ---")
        for src, dst, port, proto, desc in blocked_test_cases:
            res = sim.simulate_connection(src, dst, port, proto)
            if res["allowed"]:
                print(
                    f"  [FAIL] {desc} should be BLOCKED but was ALLOWED! Egress: {res['egress_policies']}, Ingress: {res['ingress_policies']}"
                )
                all_passed = False
            else:
                reason = []
                if not res["egress_allowed"]:
                    reason.append("blocked by source egress policy")
                if not res["ingress_allowed"]:
                    reason.append("blocked by dest ingress policy")
                print(f"  [PASS] {desc} -> BLOCKED ({' & '.join(reason)})")

        # 4. Port & Protocol Boundary Stress Tests (MUST BE REJECTED)
        boundary_test_cases = [
            ("api", "chroma", 8001, "TCP", "API -> Chroma on wrong port (8001)"),
            ("api", "chroma", 8000, "UDP", "API -> Chroma on wrong protocol (UDP)"),
            ("api", "redis", 6380, "TCP", "API -> Redis on wrong port (6380)"),
            ("api", "redis", 6379, "UDP", "API -> Redis on wrong protocol (UDP)"),
            (
                "indexer",
                "chroma",
                8001,
                "TCP",
                "Indexer -> Chroma on wrong port (8001)",
            ),
            ("indexer", "redis", 6380, "TCP", "Indexer -> Redis on wrong port (6380)"),
            ("ui", "api", 8080, "TCP", "UI -> API on wrong port (8080)"),
            ("ui", "coredns", 54, "UDP", "UI -> CoreDNS on wrong port (54)"),
            ("ui", "coredns", 80, "TCP", "UI -> CoreDNS on HTTP (80)"),
            (
                "api",
                "ollama-host",
                8000,
                "TCP",
                "API -> Ollama Host on wrong port (8000)",
            ),
        ]

        print("  --- Port & Protocol Boundary Stress Tests ---")
        for src, dst, port, proto, desc in boundary_test_cases:
            res = sim.simulate_connection(src, dst, port, proto)
            if res["allowed"]:
                print(f"  [FAIL] {desc} should be BLOCKED but was ALLOWED!")
                all_passed = False
            else:
                print(f"  [PASS] {desc} -> BLOCKED on boundary mismatch")

    print("\n" + "=" * 80)
    if all_passed:
        print("OVERALL SIMULATOR RESULT: 100% OF EMPIRICAL POLICY CHECKS PASSED")
    else:
        print("OVERALL SIMULATOR RESULT: POLICY FAILURES DETECTED")
    print("=" * 80)
    return all_passed


if __name__ == "__main__":
    success = run_full_suite()
    sys.exit(0 if success else 1)
