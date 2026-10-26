"""Defines 30 synthetic bugs across logic, type, index, zero-div, and API contract errors."""

BENCHMARK_SUITE = []

BUG_TEMPLATES = [
    (
        "zero_div",
        "def compute(a, b):\n    return a / b\n",
        "def test_compute():\n    assert compute(10, 2) == 5\n    assert compute(5, 0) == 0\n",
    ),
    (
        "index_boundary",
        "def get_last(items):\n    return items[len(items)]\n",
        "def test_last():\n    assert get_last([1, 2, 3]) == 3\n    assert get_last([]) is None\n",
    ),
    (
        "type_error",
        "def format_age(age):\n    return 'Age: ' + age\n",
        "def test_age():\n    assert format_age(25) == 'Age: 25'\n",
    ),
    (
        "dict_lookup",
        "def get_user_role(data):\n    return data['role']['name']\n",
        "def test_role():\n    assert get_user_role({'role': {'name': 'admin'}}) == 'admin'\n    assert get_user_role({}) == 'guest'\n",
    ),
    (
        "off_by_one",
        "def count_elements(limit):\n    return list(range(1, limit))\n",
        "def test_count():\n    assert count_elements(5) == [1, 2, 3, 4, 5]\n",
    ),
    (
        "none_attribute",
        "def parse_status(res):\n    return res.status.lower()\n",
        "class MockRes:\n    status = 'OK'\ndef test_status():\n    assert parse_status(MockRes()) == 'ok'\n    assert parse_status(None) == 'unknown'\n",
    ),
]

# Generate 30 distinct isolated test instances
for i in range(30):
    category, impl, test = BUG_TEMPLATES[i % len(BUG_TEMPLATES)]
    BENCHMARK_SUITE.append({
        "id": f"TASK_{i+1:02d}_{category}",
        "impl_code": impl,
        "test_code": test,
        "filename": f"task_{i+1}.py",
        "test_filename": f"test_task_{i+1}.py",
    })