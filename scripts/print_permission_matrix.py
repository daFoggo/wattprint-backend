# Runs the permission matrix and the database role cases for real, then prints them as Markdown.
# docker compose exec -T api python scripts/print_permission_matrix.py > <file>.md

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime

ACTORS = {
    "anonymous": "Chưa đăng nhập",
    "other_owner": "Chủ nhà khác",
    "viewer": "Khách demo",
    "daily_member": "Thành viên theo ngày",
    "member": "Thành viên",
    "owner": "Chủ nhà",
    "admin": "Admin",
}
DB_CASES = {
    "test_copilot_sees_only_own_home": "Scope token của nhà A chỉ thấy dữ liệu nhà A",
    "test_copilot_bad_tokens_return_nothing_without_error": "Token sai, lạ hoặc hết hạn: 0 dòng",
    "test_copilot_unset_token_returns_nothing": "Không có token: 0 dòng",
    "test_copilot_cannot_read_base_tables": "Vai copilot không đọc được bảng gốc",
    "test_copilot_cannot_write": "Vai copilot không ghi được",
    "test_ai_role_reads_reference_data_only": "Vai `wattprint_ai` chỉ đọc dữ liệu tham chiếu",
}


def run(*args: str, env: dict | None = None) -> str:
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rA", "-q", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env).stdout


def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        out = f.name
    try:
        api = run("tests/test_permissions.py", env={**os.environ, "PERMISSION_MATRIX_OUT": out})
        with open(out) as f:
            rows = sorted((json.loads(line) for line in f), key=lambda r: (r["path"], r["method"]))
    finally:
        os.unlink(out)
    expected = len(re.findall(r"test_permission_matrix\[", api))
    if (
        not rows or len(rows) != expected
    ):  # an errored cell writes no row: never print a short table
        sys.exit(f"only {len(rows)} of {expected} operations ran; see pytest:\n{api[-2000:]}")
    cell = r"FAILED tests/test_permissions.py::test_permission_matrix\[(.+?)\]"
    failed = set(re.findall(cell, api))
    db = run("tests/db/test_roles.py", "-k", " or ".join(DB_CASES))

    print(f"Chạy lúc {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, {len(rows)} thao tác API.\n")
    print("| Thao tác | " + " | ".join(ACTORS.values()) + " | Khớp mong đợi |")
    print("|---" * (len(ACTORS) + 2) + "|")
    for r in rows:
        ok = "sai" if f"{r['method']}-{r['path']}" in failed else "đúng"
        cells = " | ".join(str(r["got"][a]) for a in ACTORS)
        print(f"| `{r['method']} {r['path']}` | {cells} | {ok} |")
    print("\n| Ca ở mức database | Kết quả |\n|---|---|")
    for name, label in DB_CASES.items():
        passed = re.findall(rf"PASSED tests/db/test_roles.py::{name}\b", db)
        broke = re.findall(rf"(FAILED|ERROR) tests/db/test_roles.py::{name}\b", db)
        print(f"| {label} | {'đạt' if passed and not broke else 'không đạt'} |")


if __name__ == "__main__":
    main()
