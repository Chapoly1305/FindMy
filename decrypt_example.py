#!/usr/bin/env python3
import base64
import hashlib
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

def sha256(data):
    digest = hashlib.new("sha256")
    digest.update(data)
    return digest.digest()

# Input data
payload_b64 = "Lq8t7gME5Br0NRxMYSSPQgb0grFQBpcXNjMZTQpsWoljS/wgNh/2bLxJsxqoQDYSVZol67TX9b64RhZxr0kq7RusOr0nceTu6WcxBtP8PS10qPkdoxNXOg=="
private_key_b64 = "AQAB3GylkHEwlnh3VGOAIM/jW1DxiP5tTfoCHw=="

print("=" * 80)
print("Apple FindMy Payload Decryption - Step by Step")
print("=" * 80)

# Step 1: Decode the payload
data = base64.b64decode(payload_b64)
print(f"\n1. Decoded payload ({len(data)} bytes):")
print(f"   Hex: {data.hex()}")

# Step 2: Extract components from payload
timestamp_bytes = data[0:4]
timestamp = int.from_bytes(timestamp_bytes, 'big') + 978307200
print(f"\n2. Timestamp (bytes 0-4):")
print(f"   Hex: {timestamp_bytes.hex()}")
print(f"   Unix timestamp: {timestamp}")

eph_key_bytes = data[5:62]
print(f"\n3. Ephemeral public key (bytes 5-62, {len(eph_key_bytes)} bytes):")
print(f"   Hex: {eph_key_bytes.hex()}")
print(f"   Base64: {base64.b64encode(eph_key_bytes).decode()}")

enc_data = data[62:72]
print(f"\n4. Encrypted data (bytes 62-72, {len(enc_data)} bytes):")
print(f"   Hex: {enc_data.hex()}")

auth_tag = data[72:]
print(f"\n5. GCM auth tag (bytes 72+, {len(auth_tag)} bytes):")
print(f"   Hex: {auth_tag.hex()}")

# Step 3: Load private key
priv_bytes = base64.b64decode(private_key_b64)
priv = int.from_bytes(priv_bytes, byteorder='big')
print(f"\n6. Your private key:")
print(f"   Base64: {private_key_b64}")
print(f"   Hex: {priv_bytes.hex()}")
print(f"   Integer: {priv}")

# Step 4: Parse ephemeral public key
eph_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP224R1(), eph_key_bytes)
print(f"\n7. Ephemeral public key (parsed as EC point on SECP224R1)")

# Step 5: ECDH key exchange
private_key_obj = ec.derive_private_key(priv, ec.SECP224R1(), default_backend())
shared_key = private_key_obj.exchange(ec.ECDH(), eph_key)
print(f"\n8. ECDH shared secret ({len(shared_key)} bytes):")
print(f"   Hex: {shared_key.hex()}")
print(f"   Base64: {base64.b64encode(shared_key).decode()}")

# Step 6: KDF - SHA256(shared_secret || 0x00000001 || ephemeral_public_key)
kdf_input = shared_key + b'\x00\x00\x00\x01' + eph_key_bytes
print(f"\n9. KDF Input ({len(kdf_input)} bytes):")
print(f"   = shared_secret || 0x00000001 || ephemeral_public_key")
print(f"   Hex: {kdf_input.hex()}")

symmetric_key = sha256(kdf_input)
print(f"\n10. SHA-256(KDF Input) = {len(symmetric_key)} bytes:")
print(f"    Hex: {symmetric_key.hex()}")
print(f"    Base64: {base64.b64encode(symmetric_key).decode()}")

# Step 7: Split into AES key and IV
decryption_key = symmetric_key[:16]
iv = symmetric_key[16:]
print(f"\n11. AES-128 Key (first 16 bytes):")
print(f"    Hex: {decryption_key.hex()}")
print(f"    Base64: {base64.b64encode(decryption_key).decode()}")

print(f"\n12. IV (last 16 bytes):")
print(f"    Hex: {iv.hex()}")
print(f"    Base64: {base64.b64encode(iv).decode()}")

# Step 8: Decrypt using AES-128-GCM
print(f"\n13. Decryption using AES-128-GCM:")
decryptor = Cipher(algorithms.AES(decryption_key), modes.GCM(iv, auth_tag), default_backend()).decryptor()
decrypted = decryptor.update(enc_data) + decryptor.finalize()
print(f"    Decrypted data ({len(decrypted)} bytes): {decrypted.hex()}")

# Step 9: Decode location data
import struct
latitude = struct.unpack(">i", decrypted[0:4])[0] / 10000000.0
longitude = struct.unpack(">i", decrypted[4:8])[0] / 10000000.0
confidence = int.from_bytes(decrypted[8:9])
status = int.from_bytes(decrypted[9:10])

print(f"\n14. Decoded location:")
print(f"    Latitude:  {latitude}")
print(f"    Longitude: {longitude}")
print(f"    Confidence: {confidence}")
print(f"    Status: {status}")
print(f"    Google Maps: https://maps.google.com/maps?q={latitude},{longitude}")

print("\n" + "=" * 80)
