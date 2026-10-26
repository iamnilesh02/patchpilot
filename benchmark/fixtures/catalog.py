FIXTURE_TEMPLATES = [
    (
        "zero_division",
        "def compute_ratio(a: float, b: float) -> float:\n    return a / b\n",
        "def test_ratio():\n    assert compute_ratio(10, 2) == 5.0\n    assert compute_ratio(5, 0) == 0.0\n",
    ),
    (
        "index_out_of_bounds",
        "def fetch_tail(items: list):\n    return items[len(items)]\n",
        "def test_tail():\n    assert fetch_tail([10, 20, 30]) == 30\n    assert fetch_tail([]) is None\n",
    ),
    (
        "string_type_mismatch",
        "def build_label(prefix: str, val: int) -> str:\n    return prefix + val\n",
        "def test_label():\n    assert build_label('Item: ', 42) == 'Item: 42'\n",
    ),
    (
        "dictionary_missing_key",
        "def parse_config(cfg: dict) -> str:\n    return cfg['database']['host']\n",
        "def test_parse():\n    assert parse_config({'database': {'host': 'localhost'}}) == 'localhost'\n    assert parse_config({}) == '127.0.0.1'\n",
    ),
    (
        "off_by_one_range",
        "def generate_steps(n: int):\n    return list(range(1, n))\n",
        "def test_steps():\n    assert generate_steps(5) == [1, 2, 3, 4, 5]\n",
    ),
    (
        "attribute_on_none",
        "def retrieve_status(obj):\n    return obj.status.upper()\n",
        "class MockObj:\n    status = 'active'\ndef test_status():\n    assert retrieve_status(MockObj()) == 'ACTIVE'\n    assert retrieve_status(None) == 'UNKNOWN'\n",
    ),
]

SEEDED_FIXTURES = []
for i in range(30):
    category, impl, test = FIXTURE_TEMPLATES[i % len(FIXTURE_TEMPLATES)]
    SEEDED_FIXTURES.append({
        "fixture_id": f"SWE_MINI_{i+1:02d}_{category}",
        "impl_code": impl,
        "test_code": test,
        "impl_filename": f"module_{i+1}.py",
        "test_filename": f"test_module_{i+1}.py",
    })