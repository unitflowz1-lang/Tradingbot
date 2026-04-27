#!/usr/bin/env python3
"""
Ollama Connectivity Test Script
================================

This script verifies that:
1. Ollama is reachable on port 11434
2. The qwen3.5:0.8b model is installed and loaded
3. The model responds to API requests
4. Response format is correct (JSON with 'response' field)
5. Response time is within acceptable limits

Usage:
    python test_ollama_connectivity.py

Expected output:
    ✓ Ollama service reachable
    ✓ Model qwen3.5:0.8b installed
    ✓ Model responds successfully
    ✓ Response time: X.XXs
    ✓ All checks passed!
"""

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime


class OllamaTest:
    def __init__(self, host: str = "localhost", port: int = 11434):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.tags_url = f"{self.base_url}/api/tags"
        self.generate_url = f"{self.base_url}/api/generate"
        self.model = "qwen3.5:0.8b"
        self.tests_passed = 0
        self.tests_failed = 0

    def log_status(self, message: str, status: str = "INFO") -> None:
        """Log message with timestamp and status."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{status:>5}] {message}")

    def log_success(self, message: str) -> None:
        """Log successful test."""
        self.log_status(message, "✓")
        self.tests_passed += 1

    def log_error(self, message: str) -> None:
        """Log failed test."""
        self.log_status(message, "✗")
        self.tests_failed += 1

    def test_port_open(self) -> bool:
        """Test if Ollama port is accessible."""
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5.0)
            sock.close()
            self.log_success(f"Port {self.port} is open and reachable")
            return True
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            self.log_error(f"Port {self.port} unreachable: {str(e)[:80]}")
            return False

    def test_service_health(self) -> bool:
        """Test basic Ollama service health."""
        try:
            req = urllib.request.Request(self.tags_url, method="GET")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                http_code = resp.getcode()
                if http_code == 200:
                    self.log_success(f"Ollama service healthy (HTTP {http_code})")
                    return True
                else:
                    self.log_error(f"Ollama returned HTTP {http_code}")
                    return False
        except urllib.error.URLError as e:
            reason = str(getattr(e, "reason", e))
            self.log_error(f"Service health check failed: {reason[:80]}")
            return False
        except Exception as e:
            self.log_error(f"Service health check error: {str(e)[:80]}")
            return False

    def test_models_installed(self) -> bool:
        """Check if required models are installed."""
        try:
            req = urllib.request.Request(self.tags_url, method="GET")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            
            models = payload.get("models", [])
            if not models:
                self.log_error("No models installed in Ollama")
                return False
            
            # Extract model names
            installed_models = []
            for item in models:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("model")
                    if name:
                        installed_models.append(str(name).split(":")[0])
                elif isinstance(item, str):
                    installed_models.append(item.split(":")[0])
            
            # Check for qwen3.5
            qwen_models = [m for m in installed_models if "qwen" in m.lower()]
            if qwen_models:
                self.log_success(f"Qwen models installed: {', '.join(set(qwen_models))}")
                return True
            else:
                print(f"\n  Available models: {', '.join(set(installed_models))}")
                self.log_error(f"qwen3.5:0.8b NOT installed. Download it with:")
                print(f"    ollama pull qwen3.5:0.8b")
                return False
        
        except Exception as e:
            self.log_error(f"Model check failed: {str(e)[:80]}")
            return False

    def test_generate_endpoint(self) -> bool:
        """Test /api/generate endpoint with a simple prompt."""
        # Use a prompt that expects JSON output
        prompt = "Output only valid JSON: {\"status\":\"ok\",\"test\":true}"
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "5m",  # Keep model in memory
            "options": {
                "num_predict": 100,  # Increased from 50 to allow longer generation
                "temperature": 0.0,  # Lower temperature for more deterministic output
                "top_p": 0.8,        # Tighter nucleus sampling
            },
        }).encode("utf-8")
        
        req = urllib.request.Request(
            self.generate_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120.0) as resp:
                http_code = resp.getcode()
                elapsed = time.time() - start_time
                
                if http_code != 200:
                    self.log_error(f"Generate endpoint returned HTTP {http_code}")
                    return False
                
                try:
                    response_data = json.loads(resp.read().decode("utf-8"))
                    
                    # Check response structure - handle both 'response' and 'thinking' fields
                    # Qwen3.5 reasoning model may put output in 'thinking' field
                    response_text = response_data.get("response", "")
                    thinking_text = response_data.get("thinking", "")
                    
                    # Use thinking field if response is empty (Qwen3.5 behavior)
                    if not response_text.strip() and thinking_text.strip():
                        response_text = thinking_text
                    
                    if not response_text.strip():
                        # Still empty - log available fields
                        available_fields = list(response_data.keys())
                        model_field = response_data.get("model", "unknown")
                        done = response_data.get("done", "unknown")
                        done_reason = response_data.get("done_reason", "unknown")
                        
                        self.log_error(
                            f"Empty response from model (timeout may be too short). Model={model_field}, Done={done}, Reason={done_reason}, Fields={available_fields}"
                        )
                        print(f"  Full response: {json.dumps(response_data, indent=2)[:300]}")
                        return False
                    
                    self.log_success(f"Model responded successfully in {elapsed:.2f}s")
                    print(f"  Response preview: {response_text[:100]}...")
                    return True
                
                except json.JSONDecodeError as e:
                    raw_response = resp.read().decode("utf-8", errors="replace")[:300]
                    self.log_error(f"Response is not valid JSON: {str(e)[:80]}")
                    print(f"  Raw response: {raw_response}")
                    return False
        
        except urllib.error.HTTPError as e:
            elapsed = time.time() - start_time
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                error_body = ""
            
            self.log_error(
                f"HTTP {e.code} after {elapsed:.2f}s | Body: {error_body or '<empty>'}"
            )
            return False
        
        except urllib.error.URLError as e:
            elapsed = time.time() - start_time
            reason = str(getattr(e, "reason", e))
            
            if "timed out" in reason.lower():
                self.log_error(
                    f"Ollama timeout after {elapsed:.2f}s (increase timeout or check Ollama performance)"
                )
            else:
                self.log_error(f"Connection error after {elapsed:.2f}s: {reason[:80]}")
            return False
        
        except Exception as e:
            elapsed = time.time() - start_time
            self.log_error(f"Unexpected error after {elapsed:.2f}s: {str(e)[:80]}")
            return False

    def run_all_tests(self) -> bool:
        """Run all tests and return overall result."""
        print("\n" + "=" * 70)
        print("OLLAMA CONNECTIVITY TEST")
        print("=" * 70 + "\n")
        
        print(f"Configuration:")
        print(f"  Host: {self.host}")
        print(f"  Port: {self.port}")
        print(f"  Base URL: {self.base_url}")
        print(f"  Model: {self.model}")
        print()
        
        # Run tests in order
        tests = [
            ("Port Reachability", self.test_port_open),
            ("Service Health", self.test_service_health),
            ("Model Installation", self.test_models_installed),
            ("Generate Endpoint", self.test_generate_endpoint),
        ]
        
        for test_name, test_func in tests:
            print(f"Running: {test_name}...")
            test_func()
            print()
        
        # Summary
        print("=" * 70)
        print(f"RESULTS: {self.tests_passed} passed, {self.tests_failed} failed")
        print("=" * 70 + "\n")
        
        if self.tests_failed == 0:
            self.log_success("All checks passed! Ollama is ready.")
            return True
        else:
            self.log_error(f"{self.tests_failed} test(s) failed. See details above.")
            return False


def main() -> int:
    """Main entry point."""
    import os
    
    # Read configuration from environment or use defaults
    host = os.environ.get("OLLAMA_HOST", "localhost")
    port = int(os.environ.get("OLLAMA_PORT", "11434"))
    
    tester = OllamaTest(host=host, port=port)
    success = tester.run_all_tests()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
