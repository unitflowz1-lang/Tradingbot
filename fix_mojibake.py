with open("main.py", "rb") as f: content = f.read()
replacements = [(b"\xc3\xa2\xe2\x82\xac", b"-"), (b"\xc3\xa2\xe2\x82", b"-"), (b"\xc3\xa2\xc2\x9d\xce\x9c", b""), (b"\xc3\xa2\xc2\x9c\xc2\x85", b"[OK]"), (b"\xc3\xa2\xca\x9a\xc2\xa1", b"[BOLT]")]
for old, new in replacements: content = content.replace(old, new)
with open("main.py", "wb") as f: f.write(content)
print("Fixed all mojibake characters")
