from gateway.auth import generate_key, hash_key


def test_key_format():
    key = generate_key()
    assert key.startswith("pmk_")
    assert len(key) == 4 + 48


def test_hash_stable_and_distinct():
    k1, k2 = generate_key(), generate_key()
    assert hash_key(k1) == hash_key(k1)
    assert hash_key(k1) != hash_key(k2)
    assert len(hash_key(k1)) == 64  # sha256 hex, raw key never stored
